"""Regression tests for real Groq server-side latency capture."""

from types import SimpleNamespace

from core.orchestration.groq_provider_latency import (
    _enable_inference_metrics,
    extract_provider_timing,
)


def test_extracts_chat_completion_usage_timing():
    payload = {
        "usage": {
            "queue_time": 0.018,
            "prompt_time": 0.004,
            "completion_time": 1.234,
            "total_time": 1.256,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }
    }
    assert extract_provider_timing(payload) == {
        "queue_time": 0.018,
        "prompt_time": 0.004,
        "completion_time": 1.234,
        "total_time": 1.256,
    }


def test_extracts_metadata_timing_even_when_usage_has_no_timing():
    payload = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        "metadata": {
            "queue_time": "0.1",
            "prompt_time": "0.02",
            "completion_time": "1.8",
            "total_time": "1.92",
        },
    }
    assert extract_provider_timing(payload) == {
        "queue_time": 0.1,
        "prompt_time": 0.02,
        "completion_time": 1.8,
        "total_time": 1.92,
    }


def test_usage_timing_takes_precedence_over_metadata_for_same_field():
    payload = {
        "usage": {"total_time": 1.25},
        "metadata": {"total_time": 9.99, "queue_time": 0.1},
    }
    assert extract_provider_timing(payload) == {"total_time": 1.25, "queue_time": 0.1}


def test_invalid_provider_timing_is_ignored():
    assert extract_provider_timing({"usage": {"total_time": "unknown"}}) == {}
    assert extract_provider_timing({}) == {}


def test_inference_metrics_header_is_enabled_on_persistent_session():
    session = SimpleNamespace(headers={"Authorization": "Bearer test"})
    _enable_inference_metrics(session)
    assert session.headers["Groq-Beta"] == "inference-metrics"
