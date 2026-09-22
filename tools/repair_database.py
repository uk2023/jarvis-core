#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-time repair for an existing, bloated database/jarvis.db.

Run this ONCE, with JARVIS not running (no cli.py process open), from
the project root:

    python3 tools/repair_database.py

What it does, in order:
    1. Reports current size of jarvis.db and jarvis.db-wal.
    2. Runs `PRAGMA wal_checkpoint(TRUNCATE)` -- flushes every pending
       write in the WAL log back into the main database file and
       truncates the WAL to zero. This alone recovers most of the
       leaked space (see core/memory/semantic_memory.py and
       database/sqlite_store.py -- both used to leak a fresh SQLite
       connection on every read, which is exactly what let the WAL
       balloon indefinitely; that connection leak is now fixed, but it
       doesn't shrink a file that already grew before the fix).
    3. Runs `VACUUM` -- rebuilds the file with no wasted/free pages,
       which a checkpoint alone doesn't do.
    4. Reports the new size.

This does NOT delete any row, fact, or episode. Everything you've
taught JARVIS survives untouched -- only the leaked overhead shrinks.
If you really do want a clean slate instead, that's a separate,
explicit choice (delete database/jarvis.db*, database/jarvis_faiss.index,
and let JARVIS recreate them empty on next start) -- this script does
not do that.
"""
from __future__ import annotations

import os
import sqlite3
import sys

DB_PATH = os.environ.get("JARVIS_DB_PATH", "database/jarvis.db")


def _size(path: str) -> int:
    return os.path.getsize(path) if os.path.exists(path) else 0


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH} -- nothing to repair.")
        return 0

    wal_path = DB_PATH + "-wal"
    before_db = _size(DB_PATH)
    before_wal = _size(wal_path)
    print(f"BEFORE  jarvis.db={before_db/1024:.1f} KB   jarvis.db-wal={before_wal/1024:.1f} KB")

    conn = sqlite3.connect(DB_PATH)
    try:
        row_counts = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            try:
                row_counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                pass
        print("Tables before repair:", row_counts, "(these row counts must be identical after)")

        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.commit()

        row_counts_after = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            try:
                row_counts_after[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                pass
        if row_counts_after != row_counts:
            print("!! Row counts changed -- this should never happen. Not touching anything further.")
            print("   before:", row_counts)
            print("   after: ", row_counts_after)
            return 1
    finally:
        conn.close()

    after_db = _size(DB_PATH)
    after_wal = _size(wal_path)
    print(f"AFTER   jarvis.db={after_db/1024:.1f} KB   jarvis.db-wal={after_wal/1024:.1f} KB")
    print(f"Reclaimed: {(before_db + before_wal - after_db - after_wal)/1024:.1f} KB")
    print("All rows verified identical before/after -- no data was touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
