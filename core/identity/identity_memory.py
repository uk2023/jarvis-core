from __future__ import annotations

"""ONE JARVIS, SEPARATE MEMORIES -- BY WHO IS TALKING.

UK's spec (2026-09-14), condensed to what actually changes behaviour:

    owner  -- me, always, permanent, nobody (not even co-owner) can
              change who this is. This is JARVIS's OWN identity
              schema -- when JARVIS speaks about itself, this is the
              record it speaks from.
    co_owner / admin / user
              -- each gets a DEDICATED, PERSISTENT schema, isolated
              from every other identity's.
    guest  -- EPHEMERAL. Exists only for the session. On refresh, only
              the last 30 messages carry forward as context (so a long
              guest session cannot grow without bound). When the
              session ends, the guest's memory is gone -- there is no
              persistent guest record at all.

UK's own words on why: "taaki JARVIS kabhi confuse na ho, kisi ki baat
kisi aur ko na bataye, aur guest ka data overload na ho." Two different
failure modes, two different mechanisms:

  CROSS-CONTAMINATION is prevented by NEVER opening more than one
  identity's database in a request. There is no query in this module
  capable of joining across schemas -- the schema is chosen ONCE, from
  the verified identity, before any read or write happens.

  GUEST OVERLOAD is prevented by never persisting guest memory to disk
  at all. It lives in a bounded in-process ring buffer, keyed by
  session, and is gone the moment the session ends. "Last 30 messages"
  is enforced at write time, not by trimming later -- the 31st message
  evicts the 1st, so the buffer can never grow past its cap.

WHY THIS IS SEPARATE FROM identity_trace.py AND user_memory.py
================================================================
Those modules already exist and do real work: identity_trace.py is the
OPERATIONAL record (who did what turn, for the trace viewer);
user_memory.py is a flat per-username fact store. Neither is what UK is
asking for here, which is a full persistent MEMORY SCHEMA per identity
tier -- the thing Brain actually reasons from, not just a log of past
turns. This module is the schema router; it does not replace the trace
log or duplicate its job.
"""

import os
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

SCHEMA_ROOT = "data/identity_memory"

# Ephemeral guest memory: capped ring buffer per session, in-process
# only. Never touches disk, so there is no file to grow without bound
# and nothing to clean up when a session ends -- it simply falls out of
# the dict when this process's reference to it goes away.
GUEST_MAX_MESSAGES = 30
GUEST_IDLE_EVICT_SECONDS = 3600     # stale guest sessions are dropped

_lock = threading.RLock()
_guest_sessions: Dict[str, "GuestMemory"] = {}


@dataclass
class GuestMemory:
    """A single guest's in-process, bounded, non-persistent memory."""
    session_id: str
    messages: Deque[Dict[str, str]] = field(default_factory=lambda: deque(maxlen=GUEST_MAX_MESSAGES))
    last_touched: float = field(default_factory=time.time)

    def add(self, user_input: str, response: str) -> None:
        self.messages.append({"user_input": user_input, "response": response})
        self.last_touched = time.time()

    def context_lines(self) -> List[str]:
        return [f"user: {m['user_input']} | jarvis: {m['response']}" for m in self.messages]


def _safe_id(value: str) -> str:
    """Filesystem-safe identity key. Never trust a role/username string
    directly as part of a path."""
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", (value or "").strip().lower())[:80] or "unknown"


def resolve_identity(speaker: Dict[str, Any]) -> Dict[str, Any]:
    """The ONE decision that prevents cross-contamination: turn a
    speaker dict into exactly one schema key, made once, up front.

    Owner is special-cased explicitly rather than falling out of the
    general "role -> schema" mapping, because owner is not just another
    tier -- it is JARVIS's own identity record. Every owner-role speaker
    resolves to the SAME schema key regardless of username, because
    per UK: "owner main hi rahunga hamesha, koi nahi badal sakta,
    co-owner bhi nahi" -- there is exactly one owner schema, period.
    """
    role = (speaker or {}).get("role", "guest") or "guest"
    role = role.lower()
    verified = bool((speaker or {}).get("is_verified"))
    username = (speaker or {}).get("username")

    if role == "owner" and verified:
        return {"tier": "owner", "schema_key": "owner", "persistent": True}

    if role == "co_owner" and verified and username:
        return {"tier": "co_owner", "schema_key": f"cowner_{_safe_id(username)}", "persistent": True}

    if role == "admin" and verified and username:
        return {"tier": "admin", "schema_key": f"admin_{_safe_id(username)}", "persistent": True}

    if role == "user" and verified and username:
        return {"tier": "user", "schema_key": f"user_{_safe_id(username)}", "persistent": True}

    # Everyone else -- unverified claims of any role included -- is a
    # guest. An unverified "main owner hoon" must never resolve to the
    # owner schema; this is the same principle as the access-control
    # fix earlier in this project (absence of verification means guest,
    # never an elevated default).
    session_id = (speaker or {}).get("session_id") or "anon"
    return {"tier": "guest", "schema_key": f"guest_{_safe_id(session_id)}", "persistent": False}


def _conn(schema_key: str) -> sqlite3.Connection:
    os.makedirs(SCHEMA_ROOT, exist_ok=True)
    path = os.path.join(SCHEMA_ROOT, f"{schema_key}.db")
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, predicate TEXT, value TEXT,
            confidence REAL DEFAULT 0.8,
            created_at REAL, updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, user_input TEXT, response TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_facts_subj ON facts(subject, predicate);
        """
    )
    conn.commit()
    return conn


def remember_turn(speaker: Dict[str, Any], user_input: str, response: str) -> None:
    """Record one turn against the caller's OWN schema only.

    Guest: bounded in-process buffer, evicts oldest at 30. Everyone
    else: their dedicated SQLite schema, unbounded (persistent by
    design -- UK's spec).
    """
    identity = resolve_identity(speaker)

    if not identity["persistent"]:
        with _lock:
            key = identity["schema_key"]
            guest = _guest_sessions.get(key)
            if guest is None:
                guest = GuestMemory(session_id=key)
                _guest_sessions[key] = guest
            guest.add(user_input, response)
            _evict_stale_guests()
        return

    try:
        with _conn(identity["schema_key"]) as conn:
            conn.execute(
                "INSERT INTO turns (ts, user_input, response) VALUES (?,?,?)",
                (time.time(), user_input, response),
            )
            conn.commit()
    except Exception:
        pass


def _evict_stale_guests() -> None:
    """Guests who never came back lose their in-process buffer -- there
    is nothing on disk to clean up in the first place."""
    cutoff = time.time() - GUEST_IDLE_EVICT_SECONDS
    stale = [k for k, v in _guest_sessions.items() if v.last_touched < cutoff]
    for k in stale:
        _guest_sessions.pop(k, None)


def context_for(speaker: Dict[str, Any], limit: int = 12) -> Dict[str, Any]:
    """What Brain should see for THIS identity, and only this identity.

    Returns a dict rather than a bare list so the caller can tell a
    guest's bounded, disposable context apart from a persistent
    identity's -- the prompt wording should be honest about which one
    it is looking at.
    """
    identity = resolve_identity(speaker)

    if not identity["persistent"]:
        with _lock:
            guest = _guest_sessions.get(identity["schema_key"])
        lines = guest.context_lines() if guest else []
        return {
            "tier": "guest",
            "persistent": False,
            "lines": lines[-limit:],
            "note": (f"Guest session -- sirf last {min(len(lines), GUEST_MAX_MESSAGES)} messages "
                    "yaad hain, session khatam hote hi yeh gayab ho jaayega."),
        }

    try:
        with _conn(identity["schema_key"]) as conn:
            rows = conn.execute(
                "SELECT user_input, response, ts FROM turns ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception:
        rows = []

    lines = [f"user: {r['user_input']} | jarvis: {r['response']}" for r in reversed(rows)]
    return {
        "tier": identity["tier"],
        "persistent": True,
        "lines": lines,
        "note": f"{identity['tier']} ki apni persistent memory se ({len(lines)} recent turns).",
    }


def remember_fact(speaker: Dict[str, Any], subject: str, predicate: str, value: str,
                  confidence: float = 0.8) -> Dict[str, Any]:
    """A durable fact, scoped to this identity's own schema.

    Guests never get durable facts -- there is no schema to put them in,
    by design. A guest who states a fact has it available for the rest
    of THIS session (via context_for) and nowhere after that.
    """
    identity = resolve_identity(speaker)
    if not identity["persistent"]:
        return {"ok": False, "reason": "Guest ke liye persistent fact store nahi hai -- sirf session tak yaad rehta hai."}

    now = time.time()
    try:
        with _conn(identity["schema_key"]) as conn:
            existing = conn.execute(
                "SELECT id FROM facts WHERE subject=? AND predicate=?", (subject, predicate)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE facts SET value=?, confidence=?, updated_at=? WHERE id=?",
                    (value, confidence, now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO facts (subject, predicate, value, confidence, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (subject, predicate, value, confidence, now, now),
                )
            conn.commit()
        return {"ok": True, "tier": identity["tier"]}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def recall_facts(speaker: Dict[str, Any], subject: Optional[str] = None) -> List[Dict[str, Any]]:
    """Facts from THIS identity's schema only -- never another
    identity's, regardless of who is asking. An admin asking to see a
    user's facts must go through the trace viewer's explicit,
    permissioned scope (identity_trace.py), not through this function,
    which has no cross-identity read path at all."""
    identity = resolve_identity(speaker)
    if not identity["persistent"]:
        return []
    try:
        with _conn(identity["schema_key"]) as conn:
            if subject:
                rows = conn.execute("SELECT * FROM facts WHERE subject=?", (subject,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM facts ORDER BY updated_at DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def schema_overview() -> Dict[str, Any]:
    """For the monitor/owner view: which schemas exist, sizes, and how
    many guest sessions are currently live in memory."""
    persistent = []
    try:
        if os.path.isdir(SCHEMA_ROOT):
            for name in sorted(os.listdir(SCHEMA_ROOT)):
                if name.endswith(".db"):
                    full = os.path.join(SCHEMA_ROOT, name)
                    persistent.append({
                        "schema": name[:-3],
                        "size_kb": round(os.path.getsize(full) / 1024, 1),
                    })
    except Exception:
        pass
    with _lock:
        _evict_stale_guests()
        live_guests = len(_guest_sessions)
    return {
        "persistent_schemas": persistent,
        "live_guest_sessions": live_guests,
        "guest_max_messages": GUEST_MAX_MESSAGES,
    }
