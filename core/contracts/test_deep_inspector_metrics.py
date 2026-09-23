"""Regression checks for Deep Inspector's real runtime metrics surface."""

from __future__ import annotations

from types import SimpleNamespace

import deep_inspector


class _FakeTokenManager:
    def summary(self):
        return {
            "overall": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "calls": 2,
            },
            "by_key": {"groq#0": {"total_tokens": 200, "calls": 2}},
            "by_purpose": {"chat": {"total_tokens": 200, "calls": 2}},
            "record_count": 2,
        }


def test_real_turn_metrics_use_persistent_real_usage(monkeypatch):
    class _FakeTraceLog:
        def count(self):
            return 3

        def read_recent(self, limit=50):
            return [
                {"timings": {"total": 1.25}, "status": "completed", "mode": "llm"},
                {"timings": {"total": 2.75}, "status": "failed", "mode": "llm"},
                {"timings": {"total": 0.5}, "status": "completed", "mode": "native"},
            ]

    monkeypatch.setattr(deep_inspector, "get_token_manager", lambda: _FakeTokenManager())
    monkeypatch.setattr(deep_inspector, "get_trace_log", lambda: _FakeTraceLog())

    brain = SimpleNamespace(llm=SimpleNamespace(telemetry_snapshot=lambda: {
        "model": "llama",
        "available": True,
        "keys": [{"key_index": 0, "tpm_limit": 1000, "tpm_remaining": 800, "tpm_reset_at": 123.0}],
    }))

    metrics = deep_inspector._real_turn_metrics(brain, {})

    assert metrics["total_turns"] == 3
    assert metrics["completed_turns_sample"] == 2
    assert metrics["failed_turns_sample"] == 1
    assert metrics["total_latency_seconds"] == 4.5
    assert metrics["llm_calls_with_real_usage"] == 2
    assert metrics["actual_total_tokens"] == 200
    assert metrics["token_source"] == "provider_response_usage"
    assert metrics["tpm_source"] == "provider_headers"
    assert metrics["provider_tpm"][0]["tpm_remaining"] == 800


def test_real_turn_metrics_never_falls_back_to_brain_estimates(monkeypatch):
    class _EmptyTokenManager:
        def summary(self):
            return {"overall": {"calls": 0, "total_tokens": 0}, "record_count": 0}

    class _EmptyTraceLog:
        def count(self):
            return 0

        def read_recent(self, limit=50):
            return []

    monkeypatch.setattr(deep_inspector, "get_token_manager", lambda: _EmptyTokenManager())
    monkeypatch.setattr(deep_inspector, "get_trace_log", lambda: _EmptyTraceLog())

    brain = SimpleNamespace(
        total_turns=999,
        total_latency_seconds=999.0,
        total_tokens_estimate=99999,
        llm=None,
    )

    metrics = deep_inspector._real_turn_metrics(brain, {})

    assert metrics["total_turns"] == 0
    assert metrics["total_latency_seconds"] == 0.0
    assert metrics["actual_total_tokens"] == 0
    assert metrics["token_source"] == "no_provider_usage"
