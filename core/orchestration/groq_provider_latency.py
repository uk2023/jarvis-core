"""Capture Groq server-side inference timing from every real response.

Groq publishes queue/prompt/completion/total inference time in the response
usage/metadata when inference metrics are enabled. This module attaches those
provider-reported values to the existing per-key telemetry and keeps a
cumulative counter so behavioral experiments can measure the actual provider
work done during each turn. No client-time estimate is substituted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_TIMING_FIELDS = ("queue_time", "prompt_time", "completion_time", "total_time")
_INSTALLED = False


def extract_provider_timing(response_json: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Extract real Groq timing from `usage` or `metadata`."""
    if not isinstance(response_json, dict):
        return {}
    sources = []
    usage = response_json.get("usage")
    metadata = response_json.get("metadata")
    if isinstance(usage, dict):
        sources.append(usage)
    if isinstance(metadata, dict):
        sources.append(metadata)
    result: Dict[str, float] = {}
    for source in sources:
        for field in _TIMING_FIELDS:
            if field in result:
                continue
            value = source.get(field)
            try:
                if value is not None:
                    result[field] = float(value)
            except (TypeError, ValueError):
                pass
    return result


def _enable_inference_metrics(session: Any) -> None:
    """Enable Groq's detailed inference metrics on the persistent session."""
    headers = getattr(session, "headers", None)
    if headers is None:
        return
    try:
        headers.update({"Groq-Beta": "inference-metrics"})
    except (TypeError, AttributeError):
        pass


def install_groq_latency_capture() -> None:
    """Install idempotent capture around the real Groq request/telemetry path."""
    global _INSTALLED
    if _INSTALLED:
        return

    from .llm_bridge import GroqEngine

    original_record = GroqEngine._record_key_telemetry
    original_post = GroqEngine._post_chat_completion_single_pass

    if not getattr(original_record, "_groq_latency_capture", False):
        def wrapped_record(
            self: Any,
            key_index: int,
            attempt_info: Dict[str, Any],
            response_json: Optional[Dict[str, Any]] = None,
            request_tokens_hint: Optional[int] = None,
        ) -> None:
            original_record(self, key_index, attempt_info, response_json, request_tokens_hint)
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
            last_request["provider_latency_source"] = (
                "groq_response_usage" if isinstance((response_json or {}).get("usage"), dict)
                else "groq_response_metadata"
            )

            total = timing.get("total_time")
            if total is not None:
                self._phase5_provider_timing_total_seconds = (
                    float(getattr(self, "_phase5_provider_timing_total_seconds", 0.0))
                    + float(total)
                )
                self._phase5_provider_timing_calls = (
                    int(getattr(self, "_phase5_provider_timing_calls", 0)) + 1
                )
                last_request["provider_timing_call_index"] = self._phase5_provider_timing_calls

            client_latency = last_request.get("latency_seconds")
            if isinstance(client_latency, (int, float)) and total is not None:
                last_request["network_overhead_seconds"] = max(
                    0.0, float(client_latency) - float(total)
                )

        wrapped_record._groq_latency_capture = True
        GroqEngine._record_key_telemetry = wrapped_record

    if not getattr(original_post, "_groq_latency_capture", False):
        def wrapped_post(self: Any, *args: Any, **kwargs: Any) -> Any:
            _enable_inference_metrics(getattr(self, "_session", None))
            return original_post(self, *args, **kwargs)

        wrapped_post._groq_latency_capture = True
        GroqEngine._post_chat_completion_single_pass = wrapped_post

    _INSTALLED = True


__all__ = ["extract_provider_timing", "install_groq_latency_capture"]
