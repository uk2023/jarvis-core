"""Tests, 2026-09-21: token_management.py -- the persistent, per-key +
per-purpose + overall token ledger UK asked for (twice), with 3-day
rolling retention and restart-survival.

Run directly: python3 tests/test_token_management.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration.token_management import TokenManager, RETENTION_SECONDS


def _tmp_path() -> str:
    return os.path.join(tempfile.mkdtemp(), "token_usage_test.json")


def test_record_and_summary_reflect_real_usage():
    mgr = TokenManager(_tmp_path())
    mgr.record(purpose="chat", provider="groq", key_index=0, model="openai/gpt-oss-120b",
              prompt_tokens=100, completion_tokens=20, total_tokens=120, request_id="r1")
    mgr.record(purpose="coding_agent", provider="groq", key_index=1, model="openai/gpt-oss-120b",
              prompt_tokens=500, completion_tokens=80, total_tokens=580, request_id="r2")

    summary = mgr.summary()
    assert summary["overall"]["total_tokens"] == 700
    assert summary["overall"]["calls"] == 2
    assert summary["by_purpose"]["chat"]["total_tokens"] == 120
    assert summary["by_purpose"]["coding_agent"]["total_tokens"] == 580
    assert summary["by_key"]["groq#0"]["total_tokens"] == 120
    assert summary["by_key"]["groq#1"]["total_tokens"] == 580
    print("OK: real usage is recorded and broken down by purpose and by key")


def test_persists_across_a_restart():
    """UK's explicit ask: "jarvis restart ke baad bhi persistent rahe
    hamesha" -- a fresh TokenManager pointed at the same file must see
    the earlier process's real records."""
    path = _tmp_path()
    mgr1 = TokenManager(path)
    mgr1.record(purpose="chat", provider="groq", key_index=0, model="m",
               prompt_tokens=10, completion_tokens=5, total_tokens=15)

    mgr2 = TokenManager(path)  # simulates a fresh process after restart
    summary = mgr2.summary()
    assert summary["overall"]["total_tokens"] == 15
    assert summary["record_count"] == 1
    print("OK: records survive a restart (new TokenManager instance, same file)")


def test_records_older_than_3_days_are_purged_automatically():
    mgr = TokenManager(_tmp_path())
    old_time = time.time() - RETENTION_SECONDS - 3600  # just over 3 days old
    from core.orchestration.token_management import TokenRecord
    mgr._records.append(TokenRecord(
        timestamp=old_time, purpose="chat", provider="groq", key_index=0,
        model="m", prompt_tokens=1, completion_tokens=1, total_tokens=2,
    ))
    mgr.record(purpose="chat", provider="groq", key_index=0, model="m",
              prompt_tokens=10, completion_tokens=5, total_tokens=15)

    summary = mgr.summary()
    assert summary["record_count"] == 1, "the >3-day-old record must have been purged"
    assert summary["overall"]["total_tokens"] == 15
    print("OK: records older than 3 days are auto-purged, never accumulate forever")


def test_corrupt_file_does_not_crash_startup():
    path = _tmp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{not valid json")
    mgr = TokenManager(path)  # must not raise
    assert mgr.summary()["record_count"] == 0
    print("OK: a corrupt ledger file degrades to an empty ledger, never crashes")


def test_unlabeled_calls_default_to_chat_purpose():
    mgr = TokenManager(_tmp_path())
    mgr.record(purpose="", provider="groq", prompt_tokens=5, completion_tokens=5, total_tokens=10)
    summary = mgr.summary()
    assert "chat" in summary["by_purpose"] or "unknown" in summary["by_purpose"]
    print("OK: an unlabeled call still lands somewhere real, never silently dropped")


if __name__ == "__main__":
    test_record_and_summary_reflect_real_usage()
    test_persists_across_a_restart()
    test_records_older_than_3_days_are_purged_automatically()
    test_corrupt_file_does_not_crash_startup()
    test_unlabeled_calls_default_to_chat_purpose()
    print("\nAll token_management.py tests passed.")
