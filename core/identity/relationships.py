from __future__ import annotations

"""WHO IS JARVIS TALKING TO, WHO ARE THEY TO UK, AND WHAT MAY THEY HEAR.

Three things live here because they are the same problem seen from
three sides (2026-09-13, UK's asks):

  1. "JARVIS kabhi bhi kisi ki memory kisi ko na bataye jab tak user
     khud na kahe" -- memory is OWNED by the person it is about.
     Sharing is opt-in per fact, never a default and never inferred
     from how friendly the asker sounds.

  2. "Ek relation family friends tree bhi honi chahiye kyunki ye
     companion hai" -- JARVIS should know Heramb is a dost and
     Akanksha is a girlfriend, as a real graph it can reason over,
     not as loose facts that happen to mention a name.

  3. "Voicemail ki tarah kisi ke liye message chhod sakta hai jo JARVIS
     us particular user ko bata de verify hone pe" -- a message left
     FOR someone is delivered only after that person is verified,
     which is exactly the privacy rule applied to a pending message.

The security posture throughout: a CLAIM of identity ("main Heramb
hoon") grants nothing. Only a verified session (a signed token from
/api/auth/login, see session_tokens.py) establishes who someone is.
An unverified visitor is treated as a stranger no matter what they
assert about themselves.
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path("data/relationships.db")

# Sharing levels a fact can carry.
PRIVATE = "private"        # only the owner of the fact may ever hear it -- the default
SHARED_WITH = "shared_with"  # owner named specific people who may hear it
PUBLIC_SAFE = "public_safe"  # owner explicitly marked it as fine for anyone, e.g. a first name

# What a guest (nobody logged in) may ever receive. Deliberately not a
# list of topics but a hard rule: general knowledge only, nothing that
# came out of anyone's stored memory.
GUEST_ALLOWED_SOURCES = {"general_knowledge", "world_live"}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id TEXT PRIMARY KEY,
                person TEXT NOT NULL,           -- display name, e.g. 'Heramb'
                relation TEXT NOT NULL,         -- 'dost' | 'girlfriend' | 'bhai' | 'papa' ...
                related_to TEXT NOT NULL,       -- whose relation this is, normally the owner
                linked_username TEXT,           -- their account, once they have one
                notes TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fact_sharing (
                knowledge_id TEXT PRIMARY KEY,
                owner_username TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'private',
                shared_with TEXT,               -- JSON list of usernames
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_messages (
                id TEXT PRIMARY KEY,
                from_username TEXT NOT NULL,
                for_person TEXT NOT NULL,       -- display name if they have no account yet
                for_username TEXT,              -- filled in once linked
                message TEXT NOT NULL,
                created_at REAL NOT NULL,
                delivered_at REAL
            )
        """)
        conn.commit()


# ---------------------------------------------------------------- TREE

def add_relationship(person: str, relation: str, related_to: str = "UK",
                     linked_username: Optional[str] = None, notes: Optional[str] = None) -> str:
    """Record that `person` is `relation` to `related_to`."""
    _init()
    rel_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO relationships (id, person, relation, related_to, linked_username, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel_id, person.strip(), relation.strip().lower(), related_to.strip(),
             (linked_username or "").strip().lower() or None, notes, time.time()),
        )
        conn.commit()
    return rel_id


def get_relationship_tree(related_to: str = "UK") -> List[Dict[str, Any]]:
    _init()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT person, relation, linked_username, notes FROM relationships WHERE related_to = ?"
            " ORDER BY relation, person", (related_to.strip(),)
        ).fetchall()
    return [dict(r) for r in rows]


def who_is(person: str, related_to: str = "UK") -> Optional[Dict[str, Any]]:
    _init()
    with _connect() as conn:
        row = conn.execute(
            "SELECT person, relation, linked_username, notes FROM relationships"
            " WHERE LOWER(person) = ? AND related_to = ?",
            (person.strip().lower(), related_to.strip()),
        ).fetchone()
    return dict(row) if row else None


def known_people_count(related_to: str = "UK") -> Dict[str, Any]:
    """"Isse pata hona chahiye iska interaction kitne logo se hota hai."""
    _init()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM relationships WHERE related_to = ?", (related_to,)).fetchone()["c"]
        linked = conn.execute(
            "SELECT COUNT(*) c FROM relationships WHERE related_to = ? AND linked_username IS NOT NULL", (related_to,)
        ).fetchone()["c"]
        by_relation = conn.execute(
            "SELECT relation, COUNT(*) c FROM relationships WHERE related_to = ? GROUP BY relation", (related_to,)
        ).fetchall()
    return {
        "total_known_people": total,
        "with_accounts": linked,
        "by_relation": {r["relation"]: r["c"] for r in by_relation},
    }


# ------------------------------------------------------------- PRIVACY

def set_fact_visibility(knowledge_id: str, owner_username: str, visibility: str,
                        shared_with: Optional[List[str]] = None) -> None:
    """Opt-in sharing. Nothing calls this except an explicit instruction
    from the fact's owner -- there is deliberately no inference path
    that can widen a fact's visibility on its own."""
    if visibility not in {PRIVATE, SHARED_WITH, PUBLIC_SAFE}:
        raise ValueError("visibility must be private, shared_with or public_safe")
    _init()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO fact_sharing (knowledge_id, owner_username, visibility, shared_with, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(knowledge_id) DO UPDATE SET visibility=excluded.visibility,"
            " shared_with=excluded.shared_with, updated_at=excluded.updated_at",
            (knowledge_id, owner_username.strip().lower(), visibility,
             json.dumps([u.strip().lower() for u in (shared_with or [])]), time.time()),
        )
        conn.commit()


def may_disclose(knowledge_id: str, owner_username: str, asker_username: Optional[str],
                 asker_is_verified: bool) -> bool:
    """THE CORE PRIVACY RULE. Default is NO.

    Note what is NOT a reason to disclose: the asker being friendly,
    the asker claiming to be the owner, the asker being an admin, or
    the fact seeming harmless. Admin deliberately gets nothing here --
    admin is an operational role over the SYSTEM, not a licence to read
    people's lives. Only the owner of a fact, or someone that owner
    explicitly named, ever hears it.
    """
    if not asker_is_verified or not asker_username:
        return False                      # a stranger, or a mere claim -- never
    asker = asker_username.strip().lower()
    owner = (owner_username or "").strip().lower()
    if asker == owner:
        return True                       # your own memory is always yours
    _init()
    with _connect() as conn:
        row = conn.execute("SELECT visibility, shared_with FROM fact_sharing WHERE knowledge_id = ?",
                           (knowledge_id,)).fetchone()
    if row is None:
        return False                      # unmarked means private, not "fine to share"
    if row["visibility"] == PUBLIC_SAFE:
        return True
    if row["visibility"] == SHARED_WITH:
        try:
            return asker in set(json.loads(row["shared_with"] or "[]"))
        except Exception:
            return False
    return False


def filter_facts_for_asker(facts: List[Dict[str, Any]], owner_username: str,
                           asker_username: Optional[str], asker_is_verified: bool) -> List[Dict[str, Any]]:
    """Applied when the brief is BUILT, not when the reply is worded --
    a fact that never enters the brief cannot leak through a clever
    prompt, whereas filtering the finished sentence can always be
    talked around."""
    return [
        f for f in (facts or [])
        if may_disclose(str(f.get("knowledge_id") or ""), owner_username, asker_username, asker_is_verified)
    ]


# ---------------------------------------------------------- MESSAGE DROP

def leave_message(from_username: str, for_person: str, message: str,
                  for_username: Optional[str] = None) -> str:
    """Voicemail. Held, not delivered, until the recipient is VERIFIED --
    so telling JARVIS "main Heramb hoon" does not hand over Heramb's
    message."""
    _init()
    msg_id = str(uuid.uuid4())
    # If the recipient already has an account linked in the relationship
    # tree, resolve it now. Without this a message left for "Heramb" by
    # name sits with for_username NULL forever and never reaches him,
    # even after he verifies -- caught by the delivery test.
    if not for_username:
        known = who_is(for_person)
        if known and known.get("linked_username"):
            for_username = known["linked_username"]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pending_messages (id, from_username, for_person, for_username, message, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, from_username.strip().lower(), for_person.strip(),
             (for_username or "").strip().lower() or None, message, time.time()),
        )
        conn.commit()
    return msg_id


def collect_messages_for(username: str, is_verified: bool) -> List[Dict[str, Any]]:
    """Returns and marks delivered. Returns nothing at all for an
    unverified session -- same rule as every other private thing."""
    if not is_verified or not username:
        return []
    _init()
    user = username.strip().lower()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, from_username, message, created_at FROM pending_messages"
            " WHERE for_username = ? AND delivered_at IS NULL ORDER BY created_at", (user,)
        ).fetchall()
        out = [dict(r) for r in rows]
        if out:
            conn.executemany("UPDATE pending_messages SET delivered_at = ? WHERE id = ?",
                             [(time.time(), r["id"]) for r in out])
            conn.commit()
    return out


def link_person_to_account(person: str, username: str) -> bool:
    """Once someone in the tree signs up, tie their account to their
    node so messages held for them can be delivered."""
    _init()
    user = username.strip().lower()
    with _connect() as conn:
        updated = conn.execute(
            "UPDATE relationships SET linked_username = ? WHERE LOWER(person) = ?",
            (user, person.strip().lower()),
        ).rowcount
        conn.execute(
            "UPDATE pending_messages SET for_username = ? WHERE LOWER(for_person) = ? AND for_username IS NULL",
            (user, person.strip().lower()),
        )
        conn.commit()
    return updated > 0
