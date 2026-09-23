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


def test_metadata_is_supported_and_missing_values_are_not_invented():
    payload = {"metadata": {"total_time": "2.5", "queue_time": "0.1"}}
    assert extract_provider_timing(payload) == {
        "total_time": 2.5,
        "queue_time": 0.1,
    }


def test_invalid_provider_timing_is_ignored():
    assert extract_provider_timing({"usage": {"total_time": "unknown"}}) == {}
    assert extract_provider_timing({}) == {}


def test_inference_metrics_header_is_enabled_on_persistent_session():
    session = SimpleNamespace(headers={"Authorization": "Bearer test"})
    _enable_inference_metrics(session)
    assert session.headers["Groq-Beta"] == "inference-metrics"
