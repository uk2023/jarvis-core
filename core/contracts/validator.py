"""Central enforcement point for all JARVIS layer contracts."""

from __future__ import annotations

import threading
import time
from typing import Any, Mapping

from .schemas import CONTRACTS, ContractError


_TRACE_LOCK = threading.Lock()
_VALIDATION_EVENTS: list[dict[str, Any]] = []


def begin_validation_trace() -> None:
    """Start a fresh process-local validation trace for one runtime turn."""
    with _TRACE_LOCK:
        _VALIDATION_EVENTS.clear()


def get_validation_trace() -> list[dict[str, Any]]:
    """Return a snapshot of real validation events observed by the validator."""
    with _TRACE_LOCK:
        return [dict(event) for event in _VALIDATION_EVENTS]


def _record(schema_name: str, status: str, error: str | None = None) -> None:
    event = {"schema": schema_name, "status": status, "timestamp": time.time()}
    if error:
        event["error"] = error
    with _TRACE_LOCK:
        _VALIDATION_EVENTS.append(event)


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "any":
        return True
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, (list, tuple))
    return False


def validate(schema_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a payload against one registered contract and record the real result."""
    try:
        if schema_name not in CONTRACTS:
            raise ContractError(f"Unknown contract: {schema_name}")
        if not isinstance(payload, Mapping):
            raise ContractError(f"{schema_name}: payload must be an object")

        schema = CONTRACTS[schema_name]
        missing = [key for key in schema["required"] if key not in payload]
        if missing:
            raise ContractError(f"{schema_name}: missing required fields: {', '.join(missing)}")

        for key, expected in schema["fields"].items():
            if key in payload and not _matches_type(payload[key], expected):
                actual = type(payload[key]).__name__
                raise ContractError(
                    f"{schema_name}: field '{key}' must be {expected}, got {actual}"
                )

        result = dict(payload)
        _record(schema_name, "PASS")
        return result
    except ContractError as exc:
        _record(schema_name, "FAIL", str(exc))
        raise


def validate_input(layer: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate(f"{layer}.input", payload)


def validate_output(layer: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return validate(f"{layer}.output", payload)


def validate_transition(
    from_layer: str,
    to_layer: str,
    output_payload: Mapping[str, Any],
    input_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate both sides of a layer-to-layer transition."""
    output_result = validate_output(from_layer, output_payload)
    input_result = validate_input(to_layer, input_payload)
    return output_result, input_result
