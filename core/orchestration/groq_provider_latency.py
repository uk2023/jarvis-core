"""Capture Groq server-side response timing without replacing client latency.

Groq chat-completion responses publish real server timing in the response
`usage` object (queue_time, prompt_time, completion_time, total_time). Some
Groq endpoints expose the same fields under `metadata`. This adapter copies
those provider-reported values into the existing GroqEngine per-key
`last_request` telemetry so inspectors/tests do not accidentally report the
client wall-clock request time as provider latency.

No estimates are introduced: absent provider timing stays absent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


_TIMING_FIELDS = ("queue_time", "prompt_time", "completion_time", "total_time")
_INSTALLED = False
_ORIGINAL = None


def extract_provider_timing(response_json: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Extract only real Groq server timing values from one response body."""
    if not isinstance(response_json, dict):
        return {}

    usage = response_json.get("usage")
    metadata = response_json.get("metadata")
    source = usage if isinstance(usage, dict) else metadata
    if not isinstance(source, dict):
        return {}

    result: Dict[str, float] = {}
    for field in _TIMING_FIELDS:
        value = source.get(field)
        try:
            if value is not None:
                result[field] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _enable_inference_metrics(session: Any) -> None:
    """Ask Groq to publish server-side inference timing on each response."""
    headers = getattr(session, "headers", None)
    if headers is None:
        return
    try:
        headers["Groq-Beta"] = "inference-metrics"
    except (TypeError, AttributeError):
        pass


def install_groq_latency_capture() -> None:
    """Attach provider timing to GroqEngine's existing telemetry recorder.

    Installation is idempotent. It also enables Groq's inference-metrics
    response metadata on the engine's persistent HTTP session before the
    first request, so every Groq response can carry provider timing.
    """
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return

    from .llm_bridge import GroqEngine

    original = GroqEngine._record_key_telemetry
    if getattr(original, "_groq_latency_capture", False):
        _INSTALLED = True
        return

    original_post = GroqEngine._post_chat_completion_single_pass

    def wrapped_post(self: Any, *args: Any, **kwargs: Any) -> Any:
        _enable_inference_metrics(getattr(self, "_session", None))
        return original_post(self, *args, **kwargs)

    wrapped_post._groq_latency_capture = True
    GroqEngine._post_chat_completion_single_pass = wrapped_post

    def wrapped(
        self: Any,
        key_index: int,
        attempt_info: Dict[str, Any],
        response_json: Optional[Dict[str, Any]] = None,
        request_tokens_hint: Optional[int] = None,
    ) -> None:
        original(self, key_index, attempt_info, response_json, request_tokens_hint)

        if not attempt_info.get("success"):
            return

        timing = extract_provider_timing(response_json)
        if not timing:
            return

        telemetry = getattr(self, "_key_telemetry", None)
        if not isinstance(telemetry, dict):
            return

        state = telemetry.setdefault(key_index, {"key_index": key_index})
        last_request = state.setdefault("last_request", {})
        for field, value in timing.items():
            last_request[f"provider_{field}_seconds"] = value
        last_request["provider_latency_source"] = "groq_response_usage"

        client_latency = last_request.get("latency_seconds")
        total_time = timing.get("total_time")
        if isinstance(client_latency, (int, float)) and total_time is not None:
            last_request["network_overhead_seconds"] = max(
                0.0, float(client_latency) - total_time
            )

    wrapped._groq_latency_capture = True
    GroqEngine._record_key_telemetry = wrapped
    _ORIGINAL = original
    _INSTALLED = True


__all__ = ["extract_provider_timing", "install_groq_latency_capture"]
