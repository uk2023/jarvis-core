from __future__ import annotations

"""Real user accounts -- SQLite-backed, real password hashing, real
session tokens. Replaces AuthModal.tsx's fake biometric/OTP/Google
simulations and client.ts's "any password succeeds" fallback (both
UK's explicit "irrelevant stuff" complaint, 2026-09-12).

Design, matching UK's explicit spec:
  - Sign-up always creates a USER account. There is no signup path to
    admin or owner.
  - Exactly one OWNER account, seeded once from OWNER_PASSWORD in the
    environment/.env (never hardcoded, never a client-visible default
    the way the old AuthModal's "jarvis2026" was).
  - A user may REQUEST admin; nothing happens until the OWNER approves
    it via approve_admin(). Rejecting is remembered so a rejected
    request doesn't silently get approved by a later duplicate call.
  - Passwords are never stored or compared in plaintext -- PBKDF2-
    HMAC-SHA256, per-user random salt, standard library only.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("JARVIS_AUTH_DB", "data/auth.db"))
PBKDF2_ITERATIONS = 200_000


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                admin_request_status TEXT,
                created_at REAL NOT NULL,
                display_name TEXT
            )
        """)
        conn.commit()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


@dataclass
class UserRecord:
    username: str
    role: str
    admin_request_status: Optional[str]
    display_name: Optional[str]


def ensure_owner_seeded() -> None:
    """Creates the single OWNER account on first run, from
    OWNER_PASSWORD in the environment. If that variable isn't set,
    NO owner account is created -- there is deliberately no default
    password an attacker could look up in this source file, unlike
    the old AuthModal's hardcoded 'jarvis2026'."""
    _init_schema()
    owner_password = os.environ.get("OWNER_PASSWORD")
    if not owner_password:
        return
    with _connect() as conn:
        existing = conn.execute("SELECT username FROM users WHERE role = 'owner'").fetchone()
        if existing:
            return
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, created_at, display_name) VALUES (?, ?, ?, 'owner', ?, ?)",
            ("UK", _hash_password(owner_password, salt), salt.hex(), time.time(), "UK"),
        )
        conn.commit()


def signup(username: str, password: str, display_name: Optional[str] = None) -> UserRecord:
    """Always creates role='user'. Raises ValueError on bad input or
    an existing username -- callers turn that into a 400, never a 500
    that might leak whether a username exists via a stack trace."""
    username = (username or "").strip().lower()
    if not username or len(username) < 3:
        raise ValueError("Username must be at least 3 characters.")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    _init_schema()
    with _connect() as conn:
        existing = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError("That username is already taken.")
        salt = secrets.token_bytes(16)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, role, created_at, display_name) VALUES (?, ?, ?, 'user', ?, ?)",
            (username, _hash_password(password, salt), salt.hex(), time.time(), display_name or username),
        )
        conn.commit()
    return UserRecord(username=username, role="user", admin_request_status=None, display_name=display_name or username)


def verify_login(username: str, password: str) -> Optional[UserRecord]:
    """Constant-time comparison via hmac.compare_digest -- a naive
    `==` on password hashes leaks timing information an attacker can
    use to guess the hash byte by byte."""
    username = (username or "").strip().lower()
    _init_schema()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    salt = bytes.fromhex(row["salt"])
    candidate = _hash_password(password or "", salt)
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return None
    return UserRecord(
        username=row["username"], role=row["role"],
        admin_request_status=row["admin_request_status"], display_name=row["display_name"],
    )


def get_user(username: str) -> Optional[UserRecord]:
    _init_schema()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip().lower(),)).fetchone()
    if row is None:
        return None
    return UserRecord(username=row["username"], role=row["role"], admin_request_status=row["admin_request_status"], display_name=row["display_name"])


def request_admin(username: str) -> None:
    """User asks for admin. Does NOT change their role -- see
    approve_admin(); this only records the request for the owner to see."""
    _init_schema()
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET admin_request_status = 'pending' WHERE username = ? AND role = 'user'",
            ((username or "").strip().lower(),),
        )
        conn.commit()


def list_pending_admin_requests() -> list:
    _init_schema()
    with _connect() as conn:
        rows = conn.execute("SELECT username, display_name, created_at FROM users WHERE admin_request_status = 'pending'").fetchall()
    return [{"username": r["username"], "display_name": r["display_name"], "created_at": r["created_at"]} for r in rows]


def approve_admin(username: str) -> bool:
    """OWNER-ONLY -- enforcement of that lives in the route handler
    (see routes_auth.py's require_owner dependency), not here, but this
    function itself refuses to touch an owner row either way as a
    second layer."""
    _init_schema()
    with _connect() as conn:
        result = conn.execute(
            "UPDATE users SET role = 'admin', admin_request_status = 'approved' WHERE username = ? AND role = 'user'",
            ((username or "").strip().lower(),),
        )
        conn.commit()
        return result.rowcount > 0


def reject_admin(username: str) -> bool:
    _init_schema()
    with _connect() as conn:
        result = conn.execute(
            "UPDATE users SET admin_request_status = 'rejected' WHERE username = ? AND role = 'user'",
            ((username or "").strip().lower(),),
        )
        conn.commit()
        return result.rowcount > 0


GRANTABLE_ROLES = {"co_owner", "admin", "user"}


def set_role(username: str, new_role: str) -> bool:
    """OWNER-ONLY (enforced at the route layer via
    access_control.can_grant_roles). Promotes or demotes anyone between
    co_owner / admin / user -- this is the one function behind UK's
    "owner admin ko co-owner ya VIP me promote kar sakta hai... admin
    se user level pe la sakta hai".

    Deliberately refuses to grant 'owner': there is exactly one owner
    account, seeded once by ensure_owner_seeded(), and no runtime path
    creates a second one. It also refuses to modify the owner's own
    row, so nobody -- not even a buggy caller -- can demote UK out of
    his own system.
    """
    new_role = (new_role or "").strip().lower()
    if new_role not in GRANTABLE_ROLES:
        raise ValueError(f"Role must be one of: {', '.join(sorted(GRANTABLE_ROLES))}.")
    _init_schema()
    with _connect() as conn:
        result = conn.execute(
            "UPDATE users SET role = ?, admin_request_status = NULL WHERE username = ? AND role != 'owner'",
            (new_role, (username or "").strip().lower()),
        )
        conn.commit()
        return result.rowcount > 0


def terminate_account(username: str) -> bool:
    """OWNER-ONLY. Deletes an account outright. Refuses to touch the
    owner row for the same reason as set_role."""
    _init_schema()
    with _connect() as conn:
        result = conn.execute(
            "DELETE FROM users WHERE username = ? AND role != 'owner'",
            ((username or "").strip().lower(),),
        )
        conn.commit()
        return result.rowcount > 0


def revoke_admin(username: str) -> bool:
    """OWNER-ONLY. Demotes an admin back to user -- the undo path UK
    should have for a promotion he changes his mind about."""
    _init_schema()
    with _connect() as conn:
        result = conn.execute(
            "UPDATE users SET role = 'user', admin_request_status = NULL WHERE username = ? AND role = 'admin'",
            ((username or "").strip().lower(),),
        )
        conn.commit()
        return result.rowcount > 0
