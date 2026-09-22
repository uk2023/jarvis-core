#!/usr/bin/env python3
"""Audit / purge low-quality knowledge rows already sitting in jarvis.db.

This exists because the fix in core/cognition/semantic_understanding/engine.py
and core/contracts only stops *new* garbage facts from being written -- it
does not touch rows that were already saved before the fix (e.g. the
"faviurite" -> whole-sentence rows visible in /memory_inspect).

Usage (run this ON THE DEVICE, against the real database -- the DB shipped
in this archive is empty, the live one is at the path your CLI header shows,
e.g. /root/Jarvis_Work/database/jarvis.db):

    # Dry run: only prints what WOULD be deleted. Always start here.
    python3 scripts/purge_low_quality_facts.py

    # Point at a specific db file if it's not the default relative path.
    python3 scripts/purge_low_quality_facts.py --db /root/Jarvis_Work/database/jarvis.db

    # Actually delete the rows that fail the quality bar.
    python3 scripts/purge_low_quality_facts.py --db /root/Jarvis_Work/database/jarvis.db --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.contracts.validator import item_is_valid  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="database/jarvis.db", help="Path to jarvis.db")
    parser.add_argument("--apply", action="store_true", help="Actually delete bad rows (default is dry-run/report only)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"No such database: {args.db}", file=sys.stderr)
        return 1

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT knowledge_id, subject, predicate, value_json, confidence, evidence_count FROM knowledge"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"Could not read 'knowledge' table: {exc}", file=sys.stderr)
        return 1

    bad_ids = []
    print(f"Scanned {len(rows)} knowledge rows in {args.db}\n")
    for row in rows:
        try:
            value = json.loads(row["value_json"]) if row["value_json"] is not None else None
        except (TypeError, ValueError):
            value = row["value_json"]

        item = {"subject": row["subject"], "predicate": row["predicate"], "value": value, "confidence": row["confidence"]}
        ok, error = item_is_valid("relation_fact", item)
        if not ok:
            bad_ids.append(row["knowledge_id"])
            print(f"[BAD] {row['knowledge_id']}: subject={row['subject']!r} predicate={row['predicate']!r} value={value!r}")
            print(f"       reason: {error}\n")

    print(f"\n{len(bad_ids)} of {len(rows)} rows fail the quality bar.")

    if not bad_ids:
        print("Nothing to do.")
        return 0

    if not args.apply:
        print("\nDry run only -- nothing deleted. Re-run with --apply to delete these rows.")
        return 0

    con.executemany("DELETE FROM knowledge WHERE knowledge_id = ?", [(kid,) for kid in bad_ids])
    con.commit()
    print(f"\nDeleted {len(bad_ids)} low-quality rows from {args.db}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
