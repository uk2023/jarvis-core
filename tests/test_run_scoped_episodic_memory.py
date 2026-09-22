"""Regression test for run-scoped episodic recap (2026-09-18).

UK verified on-device that a fresh JARVIS process still "remembered"
(and hallucinated around) content from earlier, unrelated sessions,
because EpisodicMemory.recent() had no concept of "this run" at all --
memory_manager.py reloads the ENTIRE lifetime of episodes from SQLite
on every boot with no session boundary. This locks in the fix: each
episode is tagged with the process's current run_id (see
core/runtime/session_registry.py's record_start()/current_run_id()),
and recent(same_run_only=True) -- what memory_manager.build_context()
now calls -- only returns episodes from the CURRENT run, while older
episodes stay in memory for anything that still wants full history.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.runtime import session_registry as sr
from core.memory.episodic_memory import EpisodicMemory


def _fresh_sessions_db():
    tmpdir = tempfile.mkdtemp()
    sr.SESSIONS_DB = os.path.join(tmpdir, "sessions.db")


def test_new_run_starts_with_empty_recap_even_with_prior_history():
    _fresh_sessions_db()
    sr._run_id = None
    sr.record_start()

    mem = EpisodicMemory()
    mem.remember("USER_INPUT", context={"user_input": "hello from an old session"})
    assert len(mem.recent(limit=5, same_run_only=True)) == 1

    # simulate a restart: new process, new run_id, SAME reloaded memory
    sr.record_stop("clean")
    sr._run_id = None
    sr.record_start()

    assert mem.recent(limit=5, same_run_only=True) == []
    # but nothing was deleted -- full history is intact for other consumers
    assert len(mem.recent(limit=5)) == 1


def test_current_run_episodes_are_visible_immediately():
    _fresh_sessions_db()
    sr._run_id = None
    sr.record_start()

    mem = EpisodicMemory()
    mem.remember("USER_INPUT", context={"user_input": "first turn this run"})
    recap = mem.recent(limit=5, same_run_only=True)
    assert len(recap) == 1
    assert recap[0].context["user_input"] == "first turn this run"


def test_same_run_only_false_returns_full_history_unfiltered():
    _fresh_sessions_db()
    sr._run_id = None
    sr.record_start()
    mem = EpisodicMemory()
    mem.remember("USER_INPUT", context={"user_input": "a"})
    sr.record_stop("clean")
    sr._run_id = None
    sr.record_start()
    mem.remember("USER_INPUT", context={"user_input": "b"})
    assert len(mem.recent(limit=5)) == 2
    assert len(mem.recent(limit=5, same_run_only=True)) == 1


if __name__ == "__main__":
    test_new_run_starts_with_empty_recap_even_with_prior_history()
    test_current_run_episodes_are_visible_immediately()
    test_same_run_only_false_returns_full_history_unfiltered()
    print("all run-scoped episodic memory tests passed")
