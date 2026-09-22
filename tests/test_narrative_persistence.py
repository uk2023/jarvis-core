"""Real round-trip test for narrative persistence.

UK's explicit follow-up (2026-09-19): "narrative text abhi persist nahi
hota -- ise bhi completely wire karo". This verifies the full path with
a REAL temp SQLite database (no mocking of the DB layer) --
attach_thinking_steps_to_last_message() writes narratives into
trace_log, and a fresh read reconstructs them exactly, the same way
/api/history's row-mapping does.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.config as config

# Point at a throwaway temp DB BEFORE importing database.py's connection
# helpers do anything -- get_db_connection() reads config.DB_PATH at
# call time (not import time), so this is safe to set here.
_tmp_dir = tempfile.mkdtemp(prefix="jarvis_narrative_test_")
config.DB_PATH = os.path.join(_tmp_dir, "test.db")

# STUB ws_manager (2026-09-19) -- database.py imports debug_log/
# broadcast_to_clients from it purely for logging/websocket side
# effects that this test's functions under test (attach_thinking_
# steps_to_last_message, get_history_rows) never actually call. The
# real ws_manager transitively imports fastapi, which this sandbox
# does not have installed (no network to pip install it) -- stubbing
# it here tests the real database.py logic without needing a web
# server dependency this test has no use for.
import types as _types
_fake_ws_manager = _types.ModuleType("backend.ws_manager")
_fake_ws_manager.debug_log = lambda *a, **k: None
_fake_ws_manager.broadcast_to_clients = lambda *a, **k: None
sys.modules["backend.ws_manager"] = _fake_ws_manager

import backend.database as database


def _seed_jarvis_message(session_id: str) -> None:
    database.init_db()
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_messages (session_id, sender, text, source, timestamp, trace_log) "
        "VALUES (?, 'jarvis', 'a real reply', 'web', '2026-09-19T00:00:00', NULL)",
        (session_id,),
    )
    conn.commit()
    conn.close()


def test_narratives_persist_and_read_back():
    session_id = "narrative_test_session_1"
    _seed_jarvis_message(session_id)

    narratives = [
        {"content": "Let's write and run: create calculator.py", "chunk_id": 0},
        {"content": "Found an issue — subtraction not implemented. Let me fix this:", "chunk_id": 1},
    ]
    steps = [
        {"stage": "write", "content": "def add(a,b): return a+b", "ok": True, "chunk_id": 0},
    ]

    ok = database.attach_thinking_steps_to_last_message(session_id, steps, narratives)
    assert ok is True

    rows = database.get_history_rows(session_id)
    assert len(rows) == 1
    trace = json.loads(rows[0]["trace_log"])
    assert trace["thinking_narratives"] == narratives
    assert trace["thinking_steps"] == steps


def test_narratives_extend_not_replace_on_second_attach():
    """A message can get MULTIPLE attach calls in some flows (retry,
    partial stream) -- narratives must accumulate like thinking_steps
    already does, never silently overwrite the first batch."""
    session_id = "narrative_test_session_2"
    _seed_jarvis_message(session_id)

    first = [{"content": "First narrative", "chunk_id": 0}]
    second = [{"content": "Second narrative", "chunk_id": 1}]

    database.attach_thinking_steps_to_last_message(session_id, [], first)
    database.attach_thinking_steps_to_last_message(session_id, [], second)

    rows = database.get_history_rows(session_id)
    trace = json.loads(rows[0]["trace_log"])
    assert trace["thinking_narratives"] == first + second


def test_no_narratives_leaves_key_absent_or_empty():
    """Calling with no narratives (the common case -- most turns have
    none) must not fabricate an empty narratives list where the caller
    passed none at all, and must not break plain thinking_steps saves
    that predate this feature."""
    session_id = "narrative_test_session_3"
    _seed_jarvis_message(session_id)

    ok = database.attach_thinking_steps_to_last_message(session_id, [{"stage": "understand", "content": "x"}])
    assert ok is True

    rows = database.get_history_rows(session_id)
    trace = json.loads(rows[0]["trace_log"])
    assert trace.get("thinking_narratives") in (None, [])
    assert trace["thinking_steps"] == [{"stage": "understand", "content": "x"}]


if __name__ == "__main__":
    test_narratives_persist_and_read_back()
    test_narratives_extend_not_replace_on_second_attach()
    test_no_narratives_leaves_key_absent_or_empty()
    print("✓ ALL NARRATIVE PERSISTENCE TESTS PASSED (real SQLite round-trip)")
