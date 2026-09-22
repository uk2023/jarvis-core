from __future__ import annotations

"""WHO IS TALKING RIGHT NOW -- and when JARVIS was up.

UK (2026-09-14): "main chahta hoon JARVIS ko pata ho kaun login karke
baat kar raha hai + ek time me kai log login kar sakte hain... jo IP
record se dikhe ya username ya guest se, poora trace ho monitor.py me."
Plus: "JARVIS kab on hua kab band hua, sabka hisaab ho JARVIS ke paas."

Two things live here because they answer the same question -- what was
actually happening at a given moment:

  SESSIONS  Every active caller, keyed by their session token, with
            username, role, source IP and last-seen time. Concurrent by
            design: several people can be talking at once and each turn
            is attributed to the right one.

  LIFECYCLE Start, clean shutdown, and -- the useful one -- CRASH
            DETECTION. A run that has a start with no matching stop was
            killed. Termux went down five times last night with no
            record of it anywhere, so the next time it happens there
            will at least be a timestamped row saying so.

ON TIMESTAMPS
=============
Everything here is written in IST, 24-hour, as UK asked. The raw epoch
is kept alongside, because a stored local-time string alone cannot be
compared across a timezone change or sorted reliably -- the formatted
string is for reading, the epoch is for computing.

ON IP ADDRESSES
===============
An IP is stored per session so concurrent callers can be told apart and
so a strange session is visible. It is not identity: on one phone every
caller is 127.0.0.1, and behind a tunnel they all share the exit IP.
Identity comes from the verified session token; the IP is a hint.
"""

import hashlib
import os
import sqlite3
import uuid
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

SESSIONS_DB = "data/sessions.db"

_lock = threading.RLock()
# Live, in-process view. The DB is the durable record; this is what the
# monitor reads every refresh, so it must never touch disk.
_active: Dict[str, Dict[str, Any]] = {}
_run_id: Optional[str] = None

IDLE_TIMEOUT_SECONDS = 900          # 15 min without a turn = gone


def ist(ts: Optional[float] = None) -> str:
    """IST, 24-hour. The format UK asked for."""
    return datetime.fromtimestamp(ts if ts is not None else time.time(), IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SESSIONS_DB), exist_ok=True)
    conn = sqlite3.connect(SESSIONS_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            started_at_ist TEXT,
            stopped_at REAL,
            stopped_at_ist TEXT,
            stop_kind TEXT,
            pid INTEGER
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_key TEXT PRIMARY KEY,
            username TEXT,
            role TEXT,
            ip TEXT,
            channel TEXT,
            started_at REAL,
            started_at_ist TEXT,
            last_seen REAL,
            last_seen_ist TEXT,
            turns INTEGER DEFAULT 0,
            run_id TEXT
        );
        """
    )
    conn.commit()
    return conn


# ------------------------------------------------------------- lifecycle
def record_start(pid: Optional[int] = None) -> str:
    """Mark JARVIS as up, and flag any previous run that never stopped.

    A run row with no stopped_at is a crash: the process died without
    getting to write its shutdown. That is exactly what happened during
    the Termux crashes, and nothing recorded it.
    """
    global _run_id
    # uuid, not time+pid: two starts in the same second from the same
    # process produced an IDENTICAL run_id, the INSERT hit the primary
    # key, and the whole start was swallowed by the except. Crash
    # detection silently recorded nothing.
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = time.time()
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "UPDATE runs SET stop_kind = 'crash_or_kill' "
                "WHERE stopped_at IS NULL AND run_id != ?",
                (run_id,),
            )
            conn.execute(
                "INSERT INTO runs (run_id, started_at, started_at_ist, pid) VALUES (?,?,?,?)",
                (run_id, now, ist(now), pid or os.getpid()),
            )
            conn.commit()
    except Exception:
        pass
    _run_id = run_id
    return run_id


def current_run_id() -> Optional[str]:
    """The run_id of THIS process's own lifetime, set by record_start().

    2026-09-18, added so episodic memory can tag each episode with the
    run it happened in -- see EpisodicMemory.remember()/recent() in
    core/memory/episodic_memory.py, UK's "har chat ki apni alag session
    memory honi chahiye" ask. None before record_start() has run (e.g.
    imported for a one-off script, not a real JARVIS process).
    """
    return _run_id


def record_stop(kind: str = "clean") -> None:
    if not _run_id:
        return
    now = time.time()
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "UPDATE runs SET stopped_at=?, stopped_at_ist=?, stop_kind=? WHERE run_id=?",
                (now, ist(now), kind, _run_id),
            )
            conn.commit()
    except Exception:
        pass


def lifecycle_summary(limit: int = 20) -> Dict[str, Any]:
    """Uptime and crash history -- what JARVIS can honestly say about
    its own availability."""
    try:
        with _lock, _conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
    except Exception:
        return {"runs": [], "crashes": 0, "current_uptime_seconds": 0}

    runs = []
    crashes = 0
    for r in rows:
        crashed = r["stop_kind"] == "crash_or_kill"
        crashes += 1 if crashed else 0
        ended = r["stopped_at"] or (time.time() if r["run_id"] == _run_id else None)
        runs.append(
            {
                "run_id": r["run_id"],
                "started": r["started_at_ist"],
                "stopped": r["stopped_at_ist"],
                "duration_seconds": round((ended - r["started_at"]), 1) if ended else None,
                "outcome": "running" if r["run_id"] == _run_id and not r["stopped_at"]
                else ("CRASHED" if crashed else (r["stop_kind"] or "unknown")),
            }
        )

    current = next((r for r in rows if r["run_id"] == _run_id), None)
    return {
        "runs": runs,
        "crashes": crashes,
        "current_run": _run_id,
        "current_uptime_seconds": round(time.time() - current["started_at"], 1) if current else 0,
        "note": (
            f"{crashes} run bina clean shutdown ke khatam hue -- woh crash ya kill the."
            if crashes else "Ab tak har run cleanly band hua."
        ),
    }


# -------------------------------------------------------------- sessions
def touch_session(
    session_key: str,
    *,
    username: Optional[str] = None,
    role: str = "guest",
    ip: Optional[str] = None,
    channel: str = "web",
    counts_as_turn: bool = False,
) -> Dict[str, Any]:
    """Register or refresh a caller. Safe to call on every request."""
    if not session_key:
        session_key = f"anon:{ip or 'unknown'}"
    now = time.time()

    with _lock:
        existing = _active.get(session_key)
        if existing:
            existing.update(
                last_seen=now,
                username=username or existing.get("username"),
                role=role or existing.get("role"),
                ip=ip or existing.get("ip"),
                channel=channel or existing.get("channel"),
            )
            if counts_as_turn:
                existing["turns"] = existing.get("turns", 0) + 1
            record = existing
        else:
            record = {
                "session_key": session_key,
                "username": username,
                "role": role,
                "ip": ip,
                "channel": channel,
                "started_at": now,
                "last_seen": now,
                "turns": 1 if counts_as_turn else 0,
            }
            _active[session_key] = record

    # Durable copy, best-effort. A failure here must never break a turn.
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "INSERT INTO sessions (session_key, username, role, ip, channel,"
                " started_at, started_at_ist, last_seen, last_seen_ist, turns, run_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(session_key) DO UPDATE SET"
                " username=excluded.username, role=excluded.role, ip=excluded.ip,"
                " last_seen=excluded.last_seen, last_seen_ist=excluded.last_seen_ist,"
                " turns=excluded.turns",
                (
                    session_key, record.get("username"), record.get("role"), record.get("ip"),
                    record.get("channel"), record["started_at"], ist(record["started_at"]),
                    now, ist(now), record.get("turns", 0), _run_id,
                ),
            )
            conn.commit()
    except Exception:
        pass

    return record


def end_session(session_key: str) -> None:
    with _lock:
        _active.pop(session_key, None)


def _prune() -> None:
    cutoff = time.time() - IDLE_TIMEOUT_SECONDS
    with _lock:
        for key in [k for k, v in _active.items() if v.get("last_seen", 0) < cutoff]:
            _active.pop(key, None)


def active_sessions() -> List[Dict[str, Any]]:
    """Everyone currently connected. In-memory only -- the monitor calls
    this on every refresh and must not hit the disk."""
    _prune()
    with _lock:
        out = []
        for record in _active.values():
            out.append(
                {
                    **record,
                    "last_seen_ist": ist(record.get("last_seen")),
                    "idle_seconds": round(time.time() - record.get("last_seen", 0), 1),
                    # Never expose the token, not even a prefix -- a
                    # prefix is still credential material, and the first
                    # characters of a token are enough to narrow a guess.
                    # A hash is stable (so one session stays recognisable
                    # across refreshes) and reveals nothing.
                    "session_key": hashlib.sha256(
                        (record.get("session_key") or "").encode()
                    ).hexdigest()[:10],
                }
            )
        return sorted(out, key=lambda r: r.get("last_seen", 0), reverse=True)


def who_is_talking() -> Dict[str, Any]:
    """Compact summary for the monitor and for JARVIS's own answers."""
    sessions = active_sessions()
    named = [s for s in sessions if s.get("username")]
    guests = [s for s in sessions if not s.get("username")]
    return {
        "active_count": len(sessions),
        "verified": [
            {"username": s["username"], "role": s.get("role"), "ip": s.get("ip"),
             "turns": s.get("turns", 0), "last_seen": s["last_seen_ist"]}
            for s in named
        ],
        "guests": len(guests),
        "sessions": sessions,
    }
