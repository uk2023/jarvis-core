from __future__ import annotations

"""IDENTITY-TAGGED TRACES, AND WHO IS ALLOWED TO READ THEM.

From UK's spec (JARVIS_Multi_User_Upgraded_v2):

    "Every important trace event should carry identifying metadata such
     as: user_id, username, role, session_id, request_id, timestamp,
     IP/connection metadata... This allows the system to answer: WHO
     generated this trace? WHICH ROLE? WHICH SESSION? WHICH REQUEST?"

Before this, traces were one undifferentiated stream. With several
people talking at once that stream is unreadable, and worse, a normal
user's frontend turn was indistinguishable from the owner's CLI turn --
which is exactly the mixup the spec calls out.

TWO PERMISSION CATEGORIES, KEPT SEPARATE
========================================
The spec is explicit that these are different things:

    OPERATIONAL TRACE  -- routing, timings, budget, which tools ran
    PRIVATE CHAT       -- what the person actually said

An admin may read the first and must NOT automatically read the second.
So every entry stores them in separate fields and `visible_to()` can
return a trace with its content redacted. A single "can this person see
this trace" boolean would have collapsed the distinction the spec spent
three sections drawing.

WHY IP IS NOT IDENTITY
======================
The spec says it directly, and it is right: several people share an IP,
and on this phone every caller is 127.0.0.1. IP is stored as connection
metadata. Identity comes from the authenticated session, always.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))
TRACE_DB = "data/traces.db"
MAX_FIELD_CHARS = 3000
RETENTION_DAYS = 14

_lock = threading.RLock()

ROLE_RANK = {"guest": 1, "user": 2, "admin": 3, "co_owner": 4, "owner": 5}


def ist(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(TRACE_DB), exist_ok=True)
    conn = sqlite3.connect(TRACE_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS traces (
            request_id TEXT PRIMARY KEY,
            ts REAL NOT NULL,
            ts_ist TEXT,
            username TEXT,
            role TEXT NOT NULL,
            session_id TEXT,
            channel TEXT,
            ip TEXT,
            -- private: the actual conversation
            user_input TEXT,
            response TEXT,
            -- operational: how the turn was handled
            workflow TEXT,
            duration_ms REAL,
            status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_traces_user ON traces(username, ts);
        CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(ts);
        """
    )
    conn.commit()
    return conn


def _clip(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
    except Exception:
        text = str(value)
    return text[:MAX_FIELD_CHARS]


def record(
    *,
    request_id: str,
    speaker: Dict[str, Any],
    user_input: Optional[str] = None,
    response: Optional[str] = None,
    workflow: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
    status: str = "completed",
) -> None:
    """Write one turn, tagged with who generated it. Never raises."""
    now = time.time()
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces (request_id, ts, ts_ist, username, role,"
                " session_id, channel, ip, user_input, response, workflow, duration_ms, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id, now, ist(now),
                    (speaker or {}).get("username"),
                    ((speaker or {}).get("role") or "guest").lower(),
                    (speaker or {}).get("session_id"),
                    (speaker or {}).get("channel", "web"),
                    (speaker or {}).get("ip"),
                    _clip(user_input), _clip(response), _clip(workflow),
                    duration_ms, status,
                ),
            )
            conn.execute("DELETE FROM traces WHERE ts < ?", (now - RETENTION_DAYS * 86400,))
            conn.commit()
    except Exception:
        pass


def _can_see(viewer_role: str, viewer_name: Optional[str],
             row_role: str, row_name: Optional[str]) -> Optional[str]:
    """Returns 'full', 'operational' (chat redacted), or None.

    The three-way return is the point: the spec separates operational
    trace access from private chat access, so "can see" alone would be
    the wrong answer shape.
    """
    viewer_role = (viewer_role or "guest").lower()
    row_role = (row_role or "guest").lower()

    # Guests get no trace viewer at all. Section 16.
    if viewer_role == "guest":
        return None

    # Your own turns are always fully yours.
    if viewer_name and row_name and viewer_name == row_name:
        return "full"

    if viewer_role in ("owner", "co_owner"):
        return "full"

    if viewer_role == "admin":
        # Admin sees normal users' OPERATIONAL traces only, and never
        # the owner's or a co-owner's at all. Section 14: admin "cannot
        # use trace access to automatically read private chat messages".
        if row_role in ("owner", "co_owner"):
            return None
        return "operational"

    # Normal user: own only, which was handled above.
    return None


def _shape(row: sqlite3.Row, access: str) -> Dict[str, Any]:
    entry = {
        "request_id": row["request_id"],
        "timestamp": row["ts_ist"],
        "username": row["username"] or "guest",
        "role": row["role"],
        "session_id": (row["session_id"] or "")[:10] or None,
        "channel": row["channel"],
        "duration_ms": row["duration_ms"],
        "status": row["status"],
    }
    try:
        entry["workflow"] = json.loads(row["workflow"]) if row["workflow"] else None
    except Exception:
        entry["workflow"] = row["workflow"]

    if access == "full":
        entry["user_input"] = row["user_input"]
        entry["response"] = row["response"]
    else:
        # Operational access: the turn is visible, its content is not.
        entry["user_input"] = "[private -- operational access only]"
        entry["response"] = "[private -- operational access only]"
        entry["ip"] = row["ip"]
    if access == "full":
        entry["ip"] = row["ip"]
    return entry


def view(
    viewer: Dict[str, Any],
    *,
    scope: str = "mine",
    username: Optional[str] = None,
    role: Optional[str] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Traces this viewer is allowed to see.

    scope: mine | all | user | role | session | request
    The owner's DEFAULT is 'mine' (section 13) -- monitoring everyone is
    something they switch to deliberately, not the thing they get by
    accident every time they open the CLI.
    """
    viewer_role = ((viewer or {}).get("role") or "guest").lower()
    viewer_name = (viewer or {}).get("username")

    if viewer_role == "guest":
        return {
            "allowed": False,
            "entries": [],
            "reason": "Guest ke liye trace viewer nahi hai -- sirf chat.",
        }

    clauses: List[str] = []
    params: List[Any] = []

    if scope == "mine" or not viewer_name and scope == "all" and viewer_role not in ("owner", "co_owner"):
        clauses.append("username IS ?")
        params.append(viewer_name)
    elif scope == "user" and username:
        clauses.append("username = ?")
        params.append(username)
    elif scope == "role" and role:
        clauses.append("role = ?")
        params.append(role.lower())
    elif scope == "session" and session_id:
        clauses.append("session_id LIKE ?")
        params.append(f"{session_id}%")
    elif scope == "request" and request_id:
        clauses.append("request_id = ?")
        params.append(request_id)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        with _lock, _conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM traces{where} ORDER BY ts DESC LIMIT ?",
                (*params, max(1, min(int(limit), 200))),
            ).fetchall()
    except Exception as exc:
        return {"allowed": True, "entries": [], "error": str(exc)}

    entries = []
    redacted = 0
    for row in rows:
        access = _can_see(viewer_role, viewer_name, row["role"], row["username"])
        if access is None:
            continue
        if access == "operational":
            redacted += 1
        entries.append(_shape(row, access))

    return {
        "allowed": True,
        "scope": scope,
        "viewer": {"username": viewer_name, "role": viewer_role},
        "entries": entries,
        "count": len(entries),
        "redacted_count": redacted,
        "note": (
            f"{redacted} turn operational-only dikhe -- unka content private hai."
            if redacted else None
        ),
    }


def active_overview(viewer: Dict[str, Any], minutes: int = 30) -> Dict[str, Any]:
    """Who has been active recently, within what this viewer may see."""
    viewer_role = ((viewer or {}).get("role") or "guest").lower()
    viewer_name = (viewer or {}).get("username")
    if viewer_role == "guest":
        return {"allowed": False, "users": []}

    cutoff = time.time() - minutes * 60
    try:
        with _lock, _conn() as conn:
            # GROUPED BY SESSION TOO (2026-09-16). Grouping only by
            # username collapsed every guest into a single "guest" row,
            # which made them unselectable in the filter -- a guest has
            # no username, and each guest session is a separate
            # identity that resets. Including session_id means each
            # guest session shows up on its own and can be opened.
            rows = conn.execute(
                "SELECT username, role, channel, session_id, COUNT(*) turns, MAX(ts) last_ts"
                " FROM traces WHERE ts >= ? GROUP BY username, role, channel, session_id"
                " ORDER BY last_ts DESC",
                (cutoff,),
            ).fetchall()
    except Exception:
        return {"allowed": True, "users": []}

    users = []
    for r in rows:
        if _can_see(viewer_role, viewer_name, r["role"], r["username"]) is None:
            continue
        users.append({
            "username": r["username"] or "guest",
            "role": r["role"],
            "channel": r["channel"],
            "session_id": r["session_id"],
            "turns": r["turns"],
            "last_seen": ist(r["last_ts"]),
        })
    return {"allowed": True, "users": users, "window_minutes": minutes}
