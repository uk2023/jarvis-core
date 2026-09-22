#!/usr/bin/env python3
"""JARVIS -- owner account setup and recovery.

WHY THIS EXISTS
===============
The auth system was built so that no password is ever hardcoded in the
source: ensure_owner_seeded() only creates the OWNER account if the
OWNER_PASSWORD environment variable is set. That part was right -- a
default password sitting in a public file is worthless.

What was wrong was shipping that without any way to actually set it. If
OWNER_PASSWORD was never exported, NO owner account was created at all,
and UK -- who built the system and owns it -- had nothing to log in
with. A lock with no key is not security, it is a bug.

This script is the key. Run it directly; it does not need the server to
be up.

USAGE
=====
    python3 setup_owner.py                 # create or reset the owner
    python3 setup_owner.py --status        # who exists, and with what role
    python3 setup_owner.py --reset-password # owner forgot the password

HOW THE THREE LOGINS DIFFER
===========================
There is ONE login form and ONE endpoint for everyone. What differs is
the ROLE stored on the account, not the way you sign in. This is
deliberate: separate "admin login" pages are a classic weak point,
because the page itself tells an attacker where the privileged door is.

  OWNER  -- created only by this script. Exactly one exists. Cannot be
            demoted or deleted by anyone, including itself. Only a
            verified owner can grant roles to others.
  ADMIN  -- a normal signup, promoted afterwards by the owner
            (`python3 setup_owner.py --promote <username> admin`, or
            the /api/auth/set_role endpoint). An admin operates the
            system but cannot read users' private memory, cannot run
            system-level tasks, and cannot grant roles.
  USER   -- what every signup gets. No promotion needed.

So: everybody signs up and logs in the same way. UK's account is simply
the one this script marked as owner.
"""

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.identity import user_store  # noqa: E402

MIN_PASSWORD_LENGTH = 8


def _print_status() -> int:
    user_store._init_schema()
    with user_store._connect() as conn:
        rows = conn.execute(
            "SELECT username, role, display_name, created_at FROM users ORDER BY role, username"
        ).fetchall()

    if not rows:
        print("\n  Koi account nahi hai abhi.")
        print("  Owner banane ke liye:  python3 setup_owner.py\n")
        return 0

    print(f"\n  {len(rows)} account:\n")
    print(f"  {'USERNAME':<20} {'ROLE':<10} {'DISPLAY NAME'}")
    print(f"  {'-'*20} {'-'*10} {'-'*20}")
    for r in rows:
        print(f"  {r['username']:<20} {r['role']:<10} {r['display_name'] or ''}")
    print()
    if not any(r["role"] == "owner" for r in rows):
        print("  Owner account NAHI hai. Banane ke liye: python3 setup_owner.py\n")
    return 0


def _read_password(prompt: str) -> str:
    """Read a password twice, without echoing it to the terminal."""
    while True:
        first = getpass.getpass(prompt)
        if len(first) < MIN_PASSWORD_LENGTH:
            print(f"  Password kam se kam {MIN_PASSWORD_LENGTH} characters ka hona chahiye.")
            continue
        second = getpass.getpass("  Dobara likhiye: ")
        if first != second:
            print("  Dono match nahi kiye. Phir se.")
            continue
        return first


def _create_or_reset(username: str, reset_only: bool = False) -> int:
    user_store._init_schema()

    with user_store._connect() as conn:
        owner = conn.execute("SELECT username FROM users WHERE role = 'owner'").fetchone()

    if reset_only and not owner:
        print("\n  Koi owner account hai hi nahi -- reset karne ko kuch nahi.")
        print("  Pehle banao:  python3 setup_owner.py\n")
        return 1

    if owner and not reset_only:
        print(f"\n  Owner account pehle se hai: '{owner['username']}'")
        answer = input("  Password reset karna hai? [y/N]: ").strip().lower()
        if answer != "y":
            print("  Kuch nahi badla.\n")
            return 0
        username = owner["username"]
    elif owner:
        username = owner["username"]

    # verify_login() lowercases the username before its lookup, so the
    # stored row must be lowercase too. Storing "UK" and logging in as
    # "uk" silently never matched -- the account existed and the
    # password was right, and login still failed.
    display_name = username
    username = username.strip().lower()

    print(f"\n  Owner username: {username}")
    password = _read_password("  Naya password: ")

    import secrets
    import time

    salt = secrets.token_bytes(16)
    hashed = user_store._hash_password(password, salt)

    with user_store._connect() as conn:
        existing = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ?, role = 'owner' WHERE username = ?",
                (hashed, salt.hex(), username),
            )
            action = "update"
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, created_at, display_name)"
                " VALUES (?, ?, ?, 'owner', ?, ?)",
                (username, hashed, salt.hex(), time.time(), display_name),
            )
            action = "create"
        conn.commit()

    print(f"\n  Owner account {'bana diya' if action == 'create' else 'update ho gaya'}.")
    print(f"  Ab web UI ya CLI pe username '{username}' aur yeh password se login karo.")
    print("  Login form sabke liye wahi ek hai -- role account pe stored hai, alag page nahi.\n")
    return 0


def _promote(username: str, role: str) -> int:
    valid = {"co_owner", "admin", "user"}
    if role not in valid:
        print(f"\n  Role '{role}' valid nahi hai. Ye ho sakte hain: {', '.join(sorted(valid))}")
        print("  'owner' yahan se nahi de sakte -- ek hi owner hota hai, aur woh")
        print("  --reset-password se manage hota hai.\n")
        return 1

    user_store._init_schema()
    with user_store._connect() as conn:
        username = (username or "").strip().lower()
        target = conn.execute("SELECT username, role FROM users WHERE username = ?", (username,)).fetchone()
        if not target:
            print(f"\n  '{username}' naam ka koi account nahi hai.")
            print("  Us insaan ko pehle normal signup karne do, phir promote karo.\n")
            return 1
        if target["role"] == "owner":
            print("\n  Owner ka role badla nahi ja sakta -- jaan-boojh kar, taaki koi")
            print("  aapko apne hi system se bahar na kar sake.\n")
            return 1
        conn.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
        conn.commit()

    print(f"\n  '{username}' ab '{role}' hai.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS owner account setup")
    parser.add_argument("--status", action="store_true", help="Show all accounts and roles")
    parser.add_argument("--reset-password", action="store_true", help="Reset the owner's password")
    parser.add_argument("--username", default="UK", help="Owner username (default: UK)")
    parser.add_argument("--promote", nargs=2, metavar=("USERNAME", "ROLE"),
                        help="Promote an existing account: co_owner | admin | user")
    args = parser.parse_args()

    print("=" * 60)
    print("  JARVIS -- Account Setup")
    print("=" * 60)

    if args.status:
        return _print_status()
    if args.promote:
        return _promote(args.promote[0], args.promote[1])
    return _create_or_reset(args.username, reset_only=args.reset_password)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancel kar diya.\n")
        sys.exit(130)
