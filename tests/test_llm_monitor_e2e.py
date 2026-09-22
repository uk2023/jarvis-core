"""End-to-end smoke test, 2026-09-20: proves the REAL chain UK asked
for actually works -- a real GroqEngine attempt's telemetry reaches
the state bus IPC file, and llm_monitor.py (the root-level file) can
read and render it, with real numbers, not fabricated ones.

Run directly: python3 tests/test_llm_monitor_e2e.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["JARVIS_STATE_IPC"] = os.path.join(tempfile.mkdtemp(), "jarvis_state_test.ipc")

from core.orchestration.llm_bridge import GroqEngine  # noqa: E402
from core.runtime.state_bus import get_state_bus  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code, text="", headers=None, body=None):
        self.status_code = status_code
        self._text = text
        self.headers = headers or {}
        self._body = body or {"id": "req_e2e_1", "model": "test-model",
                               "usage": {"prompt_tokens": 55, "completion_tokens": 21, "total_tokens": 76},
                               "choices": [{"message": {"content": "ok"}}]}

    @property
    def text(self):
        return self._text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def post(self, url, headers=None, json=None, timeout=None):
        return _FakeResponse(200, headers={
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "917",
            "x-ratelimit-reset-requests": "40s",
            "x-ratelimit-limit-tokens": "120000",
            "x-ratelimit-remaining-tokens": "104200",
            "x-ratelimit-reset-tokens": "2.1s",
        })


def _load_llm_monitor():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm_monitor.py")
    spec = importlib.util.spec_from_file_location("llm_monitor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_telemetry_reaches_state_bus_and_renders():
    engine = GroqEngine.__new__(GroqEngine)
    engine.api_keys = ["k1"]
    engine._current_index = 0
    engine.model = "test-model"
    engine.base_url = "https://api.groq.com/openai/v1"
    engine.timeout = 15.0
    engine._session = _FakeSession()
    engine._last_attempts = []
    engine._last_used_key_index = None
    engine._last_response_headers = {}
    engine._last_retry_after = None
    engine._key_telemetry = {}
    engine._request_timestamps = {}
    engine._last_selection = {}
    engine._rate_limit_cooldown_seconds = 0.01

    result = engine._post_chat_completion({"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 500})
    assert result["choices"][0]["message"]["content"] == "ok"

    bus = get_state_bus(create=True)
    assert bus is not None, "state bus must be constructible"
    snapshot = bus.snapshot() if hasattr(bus, "snapshot") else None
    quota = (snapshot or {}).get("llm_provider_quota") if snapshot else None
    assert quota, "GroqEngine's telemetry must actually reach the state bus snapshot"
    assert "groq" in quota.get("providers", {}), quota

    llm_monitor = _load_llm_monitor()
    lines = llm_monitor.lines_for(snapshot, "test-source")
    text = "\n".join(lines)
    assert "917" in text, "real remaining-requests number must render, not a placeholder"
    assert "104200" in text or "104,200" in text, "real remaining-tokens number must render"
    assert "req_e2e_1" in text, "real request id must render"
    assert "NOT PUBLISHED" not in text.split("LAST REQUEST")[1].split("model:")[0], (
        "fields Groq actually published must not show as NOT PUBLISHED"
    )
    print("OK: real GroqEngine telemetry reaches the state bus and renders correctly in llm_monitor.py")


def test_unpublished_fields_render_honestly_not_fabricated():
    """A key that has NEVER been called must render its capacity fields
    as NOT PUBLISHED, never a fabricated 0 or a fabricated full value."""
    llm_monitor = _load_llm_monitor()
    snapshot = {
        "llm_provider_quota": {
            "providers": {"groq": {"model": "test", "keys": [{"key_index": 0}]}},
            "updated_at": None,
        }
    }
    lines = llm_monitor.lines_for(snapshot, "test-source")
    text = "\n".join(lines)
    assert "NOT PUBLISHED" in text
    print("OK: a never-called key's capacity renders as NOT PUBLISHED, not a guess")


if __name__ == "__main__":
    test_real_telemetry_reaches_state_bus_and_renders()
    test_unpublished_fields_render_honestly_not_fabricated()
    print("\nAll llm_monitor.py end-to-end tests passed.")
