# -*- coding: utf-8 -*-
"""
All SQLite access lives here: connection setup, the write-serialization
lock (the actual fix for "database is locked" / pin-rename-delete not
working), and every read/write query used by the HTTP + websocket routes.
"""
import json
import os
import sqlite3
import threading
import time
import traceback
from datetime import datetime

from . import config
from .ws_manager import debug_log, broadcast_to_clients

# ---------------------------------------------------------------------------
# Global DB write-serialization lock + WAL mode.
#
# ROOT CAUSE of pin/rename/delete "not working" and sessions not
# auto-refreshing: multiple threads (FastAPI request handlers, the
# websocket message handler running the executor in a thread, and the
# 1-second file-watcher loop) were all opening their own sqlite3
# connections and writing concurrently. On Android's emulated storage this
# very easily produces "database is locked" (sqlite3.OperationalError),
# which the old code caught, logged quietly, and returned as a plain 500 --
# so from the UI it just looked like "nothing happened" with zero feedback.
#
# Fix: (a) turn on WAL journal mode + a busy_timeout so sqlite itself waits
# instead of failing immediately, (b) serialize ALL writes behind one
# process-wide lock so two write transactions never race each other, and
# (c) wrap writes in a small retry helper as a second safety net.
# ---------------------------------------------------------------------------
db_write_lock = threading.RLock()


def get_db_connection():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # WAL lets readers and a single writer coexist without "database is
        # locked" errors, and busy_timeout makes sqlite retry internally for
        # up to 8s instead of throwing immediately if a write is briefly held.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=8000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn


def db_write(fn, *args, retries: int = 5, base_delay: float = 0.15, **kwargs):
    """Run a DB-writing function under the global write lock, retrying a
    couple of times if sqlite still reports 'database is locked'."""
    last_err = None
    for attempt in range(retries):
        try:
            with db_write_lock:
                return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
    raise last_err


def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT
                );
            """)

        cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    sender TEXT,
                    text TEXT,
                    source TEXT,
                    timestamp TEXT,
                    trace_log TEXT
                );
            """)

        # --- Lightweight migration: add pinned / updated_at columns if missing ---
        cursor.execute("PRAGMA table_info(chat_sessions)")
        existing_cols = {col[1] for col in cursor.fetchall()}
        if "pinned" not in existing_cols:
            cursor.execute(
                "ALTER TABLE chat_sessions ADD COLUMN pinned INTEGER DEFAULT 0"
            )
        if "updated_at" not in existing_cols:
            cursor.execute("ALTER TABLE chat_sessions ADD COLUMN updated_at TEXT")
            cursor.execute(
                "UPDATE chat_sessions SET updated_at = created_at WHERE"
                " updated_at IS NULL"
            )

        # --- Migration: extracted_fact column, added for the web
        # frontend's per-message "memory signal" display (V6 UI).
        # Stores the structured {subject, predicate, value} candidate
        # fact that Brain.think_and_respond() produced for that turn,
        # JSON-encoded, or NULL if none was detected. ---
        cursor.execute("PRAGMA table_info(chat_messages)")
        existing_msg_cols = {col[1] for col in cursor.fetchall()}
        if "extracted_fact" not in existing_msg_cols:
            cursor.execute(
                "ALTER TABLE chat_messages ADD COLUMN extracted_fact TEXT"
            )

        cursor.execute("SELECT COUNT(*) FROM chat_sessions")
        if cursor.fetchone()[0] == 0:
            now = config.get_local_ist_timestamp()
            cursor.execute(
                "INSERT INTO chat_sessions (session_id, title, created_at,"
                " updated_at, pinned) VALUES (?, ?, ?, ?, 0)",
                ("main_session", "General Conversation", now, now),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB INIT ERROR] {e}")


def _derive_title_from_text(text: str, max_len: int = 40) -> str:
    """Turns the first user message into a clean, ChatGPT/Gemini-style title."""
    clean = " ".join((text or "").strip().split())
    if not clean:
        return "New Conversation"
    if len(clean) <= max_len:
        return clean
    truncated = clean[:max_len].rsplit(" ", 1)[0].strip()
    return (truncated or clean[:max_len]) + "..."


def _save_message_to_db_impl(
    session_id: str,
    sender: str,
    text: str,
    source: str = "web",
    trace_log: str = None,
    extracted_fact: str = None,
):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, title FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        )
        existing_session = cursor.fetchone()
        current_time = config.get_local_ist_timestamp()
        auto_title = None

        if not existing_session:
            title = (
                _derive_title_from_text(text) if sender == "user" else "New Conversation"
            )
            cursor.execute(
                "INSERT INTO chat_sessions (session_id, title, created_at,"
                " updated_at, pinned) VALUES (?, ?, ?, ?, 0)",
                (session_id, title, current_time, current_time),
            )
        else:
            if sender == "user" and (
                existing_session["title"] or ""
            ).strip() in config.DEFAULT_SESSION_TITLES:
                auto_title = _derive_title_from_text(text)
                cursor.execute(
                    "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE"
                    " session_id = ?",
                    (auto_title, current_time, session_id),
                )
            else:
                cursor.execute(
                    "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                    (current_time, session_id),
                )

        cursor.execute(
            """
                INSERT INTO chat_messages
                (session_id, sender, text, source, timestamp, trace_log, extracted_fact)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, sender, text, source, current_time, trace_log, extracted_fact),
        )
        conn.commit()
        return auto_title, cursor.lastrowid
    finally:
        conn.close()


def save_message_to_db(
    session_id: str,
    sender: str,
    text: str,
    source: str = "web",
    trace_log: str = None,
    extracted_fact: str = None,
):
    try:
        auto_title, message_id = db_write(
            _save_message_to_db_impl,
            session_id=session_id,
            sender=sender,
            text=text,
            source=source,
            trace_log=trace_log,
            extracted_fact=extracted_fact,
        )
        if auto_title:
            broadcast_to_clients({
                "type": "session_renamed",
                "session_id": session_id,
                "title": auto_title,
            })
        return message_id
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"DB Save Error: {e}", "bold red")
        broadcast_to_clients({
            "type": "system_error",
            "source": "save_message_to_db",
            "error": str(e),
            "traceback": err_str,
        })
        return None


def list_sessions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
            SELECT s.session_id, s.title, s.created_at, s.updated_at,
                   s.pinned, COUNT(m.id) as msg_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON s.session_id = m.session_id
            GROUP BY s.session_id
            ORDER BY s.pinned DESC, COALESCE(s.updated_at, s.created_at) DESC
        """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def _attach_thinking_steps_to_last_message_impl(session_id: str, thinking_steps: list, narratives: list = None) -> bool:
    """Persist the Extended Thinking panel's steps (2026-09-17, UK's
    repeated report: the 'Socha -- N steps' panel renders live and
    vanishes on refresh). Root cause: it's driven by a SEPARATE SSE
    stream (/api/think/stream, see ExtendedThinking.tsx/streamThinking)
    that runs alongside the normal chat reply purely for display --
    unrelated to the run_coding_task/run_coding_agent tool-call trace
    that derive_thinking_steps() already persists. The frontend
    collects these steps client-side and previously only attached them
    to the in-memory message object; this is the missing write-back
    that folds them into the SAME jarvis row's trace_log the coding-
    tool path already uses, so /api/history's existing thinking_steps
    read-back (routes_http.py) picks them up identically either way.

    narratives (2026-09-19, UK: the chunk-boundary prose task_loop.py's
    stream() now yields -- see its docstring -- was reaching the live
    panel but never persisted, so a reloaded past message showed the
    same step groups with the commentary between them gone). Stored the
    same way as thinking_steps, under its own trace_log key, extended
    not replaced on a second attach for the same message.

    Returns True if a row was updated."""
    import json as _json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
            SELECT id, trace_log FROM chat_messages
            WHERE session_id = ? AND sender = 'jarvis'
            ORDER BY id DESC LIMIT 1
        """,
        (session_id,),
    )
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return False
    message_id, existing_raw = row["id"], row["trace_log"]
    try:
        trace = _json.loads(existing_raw) if existing_raw else {}
        if not isinstance(trace, dict):
            trace = {}
    except Exception:
        trace = {}
    # Don't overwrite steps the coding-tool path may already have
    # derived for this same message -- extend instead of replace.
    existing_steps = trace.get("thinking_steps")
    if isinstance(existing_steps, list) and existing_steps:
        trace["thinking_steps"] = existing_steps + list(thinking_steps)
    else:
        trace["thinking_steps"] = list(thinking_steps)

    if narratives:
        existing_narratives = trace.get("thinking_narratives")
        if isinstance(existing_narratives, list) and existing_narratives:
            trace["thinking_narratives"] = existing_narratives + list(narratives)
        else:
            trace["thinking_narratives"] = list(narratives)

    cursor.execute(
        "UPDATE chat_messages SET trace_log = ? WHERE id = ?",
        (_json.dumps(trace, ensure_ascii=False, default=str), message_id),
    )
    conn.commit()
    conn.close()
    return True


def attach_thinking_steps_to_last_message(session_id: str, thinking_steps: list, narratives: list = None) -> bool:
    try:
        return db_write(_attach_thinking_steps_to_last_message_impl,
                         session_id=session_id, thinking_steps=thinking_steps, narratives=narratives)
    except Exception:
        return False


def get_history_rows(session_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
            SELECT id, session_id, sender, text, source, timestamp, trace_log, extracted_fact
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
        """,
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def _timestamp_to_epoch_ms(timestamp_str: str) -> int:
    """config.get_local_ist_timestamp() writes 'YYYY-MM-DD HH:MM:SS.ffffff'
    in IST -- parse that back into an epoch-ms int for the web frontend
    (ActivityHistoryItem.startTime expects epoch millis, same units as
    JS Date.now()). Returns 0 (never raises) if the row predates this
    format or is otherwise unparseable, so one bad row can't break the
    whole trace history endpoint."""
    if not timestamp_str:
        return 0
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=config.IST)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def get_recent_traces(limit: int = 50):
    """Every jarvis reply that has a real trace_log (the exact
    brain.last_turn_trace JSON produced this turn -- see
    backend/trace_utils.py), paired with the user message that
    triggered it, most recent first, across ALL sessions. This is what
    powers the web Trace Inspector's turn history -- the SAME per-turn
    data cli.py's /trace_inspect and deep_inspector.py render, not a
    second, simulated trace.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, sender, text, source, timestamp, trace_log
            FROM chat_messages
            WHERE sender = 'jarvis' AND trace_log IS NOT NULL AND trace_log != ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        jarvis_rows = cursor.fetchall()

        results = []
        for row in jarvis_rows:
            try:
                trace = json.loads(row["trace_log"])
            except (ValueError, TypeError):
                trace = None
            if not isinstance(trace, dict):
                continue

            cursor.execute(
                """
                SELECT text FROM chat_messages
                WHERE session_id = ? AND sender = 'user' AND id < ?
                ORDER BY id DESC LIMIT 1
                """,
                (row["session_id"], row["id"]),
            )
            user_row = cursor.fetchone()

            results.append({
                "id": row["id"],
                "session_id": row["session_id"],
                "query": user_row["text"] if user_row else (trace.get("query") or ""),
                "response": row["text"],
                "source": row["source"],
                "start_ms": _timestamp_to_epoch_ms(row["timestamp"]),
                "trace": trace,
            })
        return results
    finally:
        conn.close()


def get_trace_by_message_id(message_id):
    """Single jarvis message row (by chat_messages.id) with its real
    parsed trace -- backs GET /api/trace/{turn_id}."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, sender, text, source, timestamp, trace_log
            FROM chat_messages
            WHERE id = ? AND sender = 'jarvis'
            """,
            (message_id,),
        )
        row = cursor.fetchone()
        if not row or not row["trace_log"]:
            return None
        try:
            trace = json.loads(row["trace_log"])
        except (ValueError, TypeError):
            return None
        if not isinstance(trace, dict):
            return None

        cursor.execute(
            """
            SELECT text FROM chat_messages
            WHERE session_id = ? AND sender = 'user' AND id < ?
            ORDER BY id DESC LIMIT 1
            """,
            (row["session_id"], row["id"]),
        )
        user_row = cursor.fetchone()

        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "query": user_row["text"] if user_row else (trace.get("query") or ""),
            "response": row["text"],
            "source": row["source"],
            "start_ms": _timestamp_to_epoch_ms(row["timestamp"]),
            "trace": trace,
        }
    finally:
        conn.close()


def _create_new_session_impl(session_id: str):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now = config.get_local_ist_timestamp()
        cursor.execute(
            "INSERT INTO chat_sessions (session_id, title, created_at,"
            " updated_at, pinned) VALUES (?, ?, ?, ?, 0)",
            (session_id, "New Conversation", now, now),
        )
        conn.commit()
    finally:
        conn.close()


def create_new_session(session_id: str):
    db_write(_create_new_session_impl, session_id)


def _rename_session_impl(session_id: str, new_title: str) -> int:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
            (new_title, config.get_local_ist_timestamp(), session_id),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def rename_session(session_id: str, new_title: str) -> int:
    return db_write(_rename_session_impl, session_id, new_title)


def _pin_session_impl(session_id: str, payload: dict):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pinned FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        if payload and "pinned" in payload:
            new_pinned = 1 if payload["pinned"] else 0
        else:
            new_pinned = 0 if row["pinned"] else 1  # toggle

        cursor.execute(
            "UPDATE chat_sessions SET pinned = ?, updated_at = ? WHERE session_id = ?",
            (new_pinned, config.get_local_ist_timestamp(), session_id),
        )
        conn.commit()
        return new_pinned
    finally:
        conn.close()


def pin_session(session_id: str, payload: dict):
    return db_write(_pin_session_impl, session_id, payload)


def _delete_session_impl(session_id: str) -> int:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def delete_session(session_id: str) -> int:
    return db_write(_delete_session_impl, session_id)
