from __future__ import annotations

"""ONE MEMORY PER PERSON, NEVER SHARED.

UK (2026-09-13): "saare users jo login honge unka separate data rahega,
memory wagera -- kyunki JARVIS evolve hoga self, use kisi ki bhi memory
padhne ka responsibility dene ka unse, unki behaviour ki tarah adapt
karke baat karne ka hona chahiye."

Two requirements that must not be confused with each other:

  * ADAPT to each person -- learn how they write, how much detail they
    want, what they keep coming back to.
  * ISOLATE each person -- what JARVIS learns from Heramb must never
    surface while talking to Rohit, and neither may ever surface UK's
    private life.

The isolation is enforced by storage, not by prompting. Every read and
write is keyed on username at the SQL level, so there is no query in
this module capable of returning another user's rows. Asking the model
nicely not to leak would be the weaker design: a persona instruction can
be argued with, a WHERE clause cannot.

Owner data lives under the same mechanism. Admin role grants NO read
access here -- being able to operate the system is not the same as
being allowed to read the people using it. That matches the earlier
decision in relationships.py, for the same reason.

What is learned is deliberately shallow: interaction style and recurring
topics, not inferred personality or sensitive traits. A system that
silently builds a psychological profile of its users, on UK's phone,
with no way for them to see it, is not something worth building -- so
export_for_user() exists to let any person see everything held on them.
"""

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

USER_MEMORY_DB = Path("data/user_memory.db")

MAX_FACTS_PER_USER = 500
MAX_TOPICS = 40


def _conn() -> sqlite3.Connection:
    USER_MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USER_MEMORY_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            username TEXT PRIMARY KEY,
            created_at REAL,
            last_seen REAL,
            turns INTEGER DEFAULT 0,
            avg_message_words REAL DEFAULT 0,
            language TEXT,
            prefers_brief INTEGER DEFAULT 0,
            technical_level TEXT
        );
        CREATE TABLE IF NOT EXISTS user_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            fact TEXT NOT NULL,
            source TEXT,
            created_at REAL,
            confidence REAL DEFAULT 0.5
        );
        CREATE TABLE IF NOT EXISTS user_topics (
            username TEXT NOT NULL,
            topic TEXT NOT NULL,
            hits INTEGER DEFAULT 1,
            last_seen REAL,
            PRIMARY KEY (username, topic)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_user ON user_facts(username);
    """)
    conn.commit()
    return conn


def _normalise(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "", username.strip().lower())
    return clean or None


def observe_turn(username: Optional[str], message: str,
                 language_hint: Optional[str] = None) -> None:
    """Record how this person writes. Cheap, no LLM, runs every turn."""
    user = _normalise(username)
    if not user or not (message or "").strip():
        return
    words = len(message.split())
    try:
        with _conn() as conn:
            row = conn.execute("SELECT turns, avg_message_words FROM user_profile WHERE username = ?",
                               (user,)).fetchone()
            now = time.time()
            if row:
                turns = row["turns"] + 1
                avg = ((row["avg_message_words"] or 0) * row["turns"] + words) / turns
                conn.execute(
                    "UPDATE user_profile SET turns=?, avg_message_words=?, last_seen=?,"
                    " prefers_brief=?, language=COALESCE(?, language) WHERE username=?",
                    (turns, avg, now, 1 if avg < 15 else 0, language_hint, user))
            else:
                conn.execute(
                    "INSERT INTO user_profile (username, created_at, last_seen, turns,"
                    " avg_message_words, language, prefers_brief) VALUES (?,?,?,?,?,?,?)",
                    (user, now, now, 1, words, language_hint, 1 if words < 15 else 0))
            conn.commit()
    except Exception as exc:
        log_event("user_memory", f"observe_turn failed: {exc}", level="warning")


def note_topic(username: Optional[str], topic: str) -> None:
    user = _normalise(username)
    topic = (topic or "").strip().lower()[:60]
    if not user or not topic:
        return
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO user_topics (username, topic, hits, last_seen) VALUES (?,?,1,?)"
                " ON CONFLICT(username, topic) DO UPDATE SET hits = hits + 1, last_seen = excluded.last_seen",
                (user, topic, time.time()))
            conn.commit()
    except Exception:
        pass


def remember_about_user(username: Optional[str], fact: str, source: str = "conversation",
                        confidence: float = 0.6) -> Dict[str, Any]:
    """Store a fact about THIS user, in their own partition."""
    user = _normalise(username)
    if not user:
        return {"ok": False, "error": "Username ke bina kuch store nahi hoga."}
    fact = (fact or "").strip()
    if not fact:
        return {"ok": False, "error": "Khali fact."}
    try:
        with _conn() as conn:
            dup = conn.execute(
                "SELECT id FROM user_facts WHERE username=? AND lower(fact)=lower(?)",
                (user, fact)).fetchone()
            if dup:
                return {"ok": True, "duplicate": True, "id": dup["id"]}
            count = conn.execute("SELECT COUNT(*) c FROM user_facts WHERE username=?", (user,)).fetchone()["c"]
            if count >= MAX_FACTS_PER_USER:
                conn.execute(
                    "DELETE FROM user_facts WHERE id IN (SELECT id FROM user_facts WHERE username=?"
                    " ORDER BY confidence ASC, created_at ASC LIMIT 1)", (user,))
            cur = conn.execute(
                "INSERT INTO user_facts (username, fact, source, created_at, confidence) VALUES (?,?,?,?,?)",
                (user, fact, source, time.time(), max(0.0, min(1.0, float(confidence)))))
            conn.commit()
            return {"ok": True, "id": cur.lastrowid}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def recall_for_user(username: Optional[str], limit: int = 25) -> Dict[str, Any]:
    """Everything JARVIS knows about this ONE person.

    There is deliberately no function in this module that reads across
    users. The username is not an optional filter -- it is the key.
    """
    user = _normalise(username)
    if not user:
        return {"username": None, "known": False, "facts": [], "topics": [], "style": {}}
    try:
        with _conn() as conn:
            profile = conn.execute("SELECT * FROM user_profile WHERE username=?", (user,)).fetchone()
            facts = conn.execute(
                "SELECT fact, source, confidence, created_at FROM user_facts WHERE username=?"
                " ORDER BY confidence DESC, created_at DESC LIMIT ?", (user, limit)).fetchall()
            topics = conn.execute(
                "SELECT topic, hits FROM user_topics WHERE username=? ORDER BY hits DESC LIMIT ?",
                (user, MAX_TOPICS)).fetchall()
        return {
            "username": user,
            "known": bool(profile),
            "style": {
                "turns": profile["turns"] if profile else 0,
                "avg_message_words": round(profile["avg_message_words"], 1) if profile else 0,
                "language": profile["language"] if profile else None,
                "prefers_brief": bool(profile["prefers_brief"]) if profile else False,
                "technical_level": profile["technical_level"] if profile else None,
            } if profile else {},
            "facts": [dict(f) for f in facts],
            "topics": [dict(t) for t in topics],
        }
    except Exception as exc:
        return {"username": user, "known": False, "facts": [], "topics": [], "style": {}, "error": str(exc)}


def context_block(username: Optional[str], role: str = "user") -> str:
    """Compact block for the system prompt -- this user only.

    Called with the SPEAKER's username. Because recall is keyed on that
    username, there is no path by which another person's memory can
    enter this prompt.
    """
    data = recall_for_user(username, limit=12)
    if not data.get("known"):
        return ""
    lines = [f"WHAT YOU KNOW ABOUT {data['username']} (this person only -- never mention other users' data):"]
    style = data.get("style") or {}
    if style.get("turns"):
        lines.append(f"- You have spoken {style['turns']} times before.")
    if style.get("prefers_brief"):
        lines.append("- They write briefly; keep replies short unless they ask for depth.")
    if style.get("language"):
        lines.append(f"- They usually write in {style['language']}.")
    for f in data.get("facts", [])[:10]:
        lines.append(f"- {f['fact']}")
    topics = [t["topic"] for t in data.get("topics", [])[:5]]
    if topics:
        lines.append(f"- Recurring topics: {', '.join(topics)}.")
    return "\n".join(lines)


def export_for_user(username: Optional[str]) -> Dict[str, Any]:
    """Let a person see everything held about them. Exists because
    storing behavioural notes on someone with no way for them to look
    is not acceptable, however useful the notes are."""
    return recall_for_user(username, limit=MAX_FACTS_PER_USER)


def forget_user(username: Optional[str], requester_role: str = "user",
                requester_username: Optional[str] = None) -> Dict[str, Any]:
    """Delete a person's memory. Allowed for the person themselves, or
    for a verified owner. Admin cannot delete other people's data."""
    user = _normalise(username)
    requester = _normalise(requester_username)
    if not user:
        return {"ok": False, "error": "Username chahiye."}
    if not (requester == user or (requester_role or "").lower() in {"owner", "co_owner"}):
        return {"ok": False, "error": "Apni memory aap delete kar sakte ho; kisi aur ki sirf owner."}
    try:
        with _conn() as conn:
            for table in ("user_facts", "user_topics", "user_profile"):
                conn.execute(f"DELETE FROM {table} WHERE username=?", (user,))
            conn.commit()
        log_event("user_memory", f"erased memory for {user} (by {requester or 'owner'})", level="info")
        return {"ok": True, "username": user, "note": f"{user} ki memory poori tarah delete ho gayi."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def known_users() -> List[Dict[str, Any]]:
    """Usernames and counts ONLY -- no facts. For the owner's overview
    of who uses the system, without exposing what anyone said."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT p.username, p.turns, p.last_seen,"
                " (SELECT COUNT(*) FROM user_facts f WHERE f.username = p.username) AS fact_count"
                " FROM user_profile p ORDER BY p.last_seen DESC").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
