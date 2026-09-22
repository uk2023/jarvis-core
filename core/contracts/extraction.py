from __future__ import annotations

"""Structured-extraction fallback cascade.

Problem this fixes (reproduced against the pre-fix code):

    A weak/offline LLM asked to "return only JSON" instead rambles in
    natural language. The old perception provider caught the JSON
    parse failure and returned a *zero-confidence, empty-intent*
    PerceptionResult -- which PerceptionEngine then accepted as the
    final answer because it was merely "a PerceptionResult instance",
    not because it was actually valid. No retry, no contract
    validation, no deterministic safe payload. Every downstream layer
    (router, brain, memory) then had to defend against silently
    malformed input instead of being able to trust the contract.

This module is the fix: a small, dependency-free, three-stage
cascade that every LLM-backed extraction point in the pipeline
(perception, semantic understanding, etc.) can share.

    Stage 1 -- PRIMARY EXTRACTION
        Run the caller's primary extractor (usually: one LLM call
        with the normal system prompt) and validate the result
        against a registered contract (core.contracts.schemas).

    Stage 2 -- REFINED EXTRACTION
        If Stage 1 produced no result or failed validation, run the
        caller's refined extractor. The refined extractor receives
        the Stage 1 failure reason so it can inject a stronger,
        more explicit instruction ("your last output was invalid
        JSON because X; return ONLY compact JSON matching exactly
        this shape") into its own prompt. Validated the same way.

    Stage 3 -- DETERMINISTIC SAFE FALLBACK
        If Stage 2 also fails, no further LLM calls are made. The
        caller's safe_default_factory builds a deterministic,
        always-valid payload (e.g. an empty/low-confidence intent)
        so downstream components NEVER receive raw, unstructured, or
        partially-shaped text. This is what actually guarantees "raw
        LLM text must never leak into state storage or execution".

Every stage transition is recorded (both returned to the caller and
mirrored into the runtime state bus, best-effort) so `monitor.py` can
show "Recent Schema Extractions" and the CLI can show which stage a
given turn actually used.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from .schemas import ContractError
from .validator import validate_output

ExtractorFn = Callable[[Optional[str]], Any]
"""An extractor stage: takes the previous-stage failure reason (None
on the first attempt) and returns EITHER a dict payload OR an object
exposing .as_contract_payload() -> dict (e.g. PerceptionResult)."""


@dataclass
class ExtractionAttempt:
    stage: str
    ok: bool
    reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExtractionResult:
    schema_name: str
    stage_used: str  # "primary" | "refined" | "safe_fallback"
    payload: Any
    contract_payload: dict
    attempts: list = field(default_factory=list)
    fallback_active: bool = False

    def as_log_dict(self) -> dict:
        return {
            "schema": self.schema_name,
            "stage_used": self.stage_used,
            "fallback_active": self.fallback_active,
            "attempts": [
                {"stage": a.stage, "ok": a.ok, "reason": a.reason, "timestamp": a.timestamp}
                for a in self.attempts
            ],
        }


def _extract_contract_payload(schema_name: str, candidate: Any) -> dict:
    """Normalize a stage's raw return value into a validated contract dict.

    Accepts either a plain dict (validated directly against the
    registered output contract) or an object exposing
    as_contract_payload() (which is expected to have already called
    the validator itself, e.g. PerceptionResult.as_contract_payload).
    """
    if candidate is None:
        raise ContractError(f"{schema_name}: extractor produced no result")
    as_payload = getattr(candidate, "as_contract_payload", None)
    if callable(as_payload):
        return as_payload()
    if isinstance(candidate, Mapping):
        return validate_output(schema_name, candidate)
    raise ContractError(
        f"{schema_name}: extractor returned unsupported type {type(candidate).__name__}"
    )


def extract_first_json_object(text: str) -> Any:
    """Find and parse the first balanced {...} JSON object anywhere in
    text, not just when the WHOLE string is JSON.

    THE ACTUAL FIX for extraction still failing ~25% of turns even
    after response_format={"type":"json_object"} was added (2026-09-11
    trace-log audit, Bug 2): json_object mode guarantees the message
    IS valid JSON when the model emits pure JSON, but it does not stop
    a reasoning model (openai/gpt-oss-120b) from wrapping that JSON in
    its own explanation/preamble text anyway -- the whole-string
    `json.loads()` callers used before this rejected the entire
    response the moment there was ANY surrounding text, even though a
    perfectly valid JSON object was sitting right there in the middle
    of it. Brace-matching (with proper string/escape awareness, not a
    naive regex) finds that object regardless of what's around it.
    """
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in text")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("no balanced JSON object found in text")


def run_extraction_cascade(
    schema_name: str,
    *,
    primary: ExtractorFn,
    refined: Optional[ExtractorFn] = None,
    safe_default: Callable[[str], Any],
) -> ExtractionResult:
    """Run the 3-stage cascade for one schema-bound extraction.

    `safe_default(reason)` MUST always return a value that validates
    cleanly -- it is the deterministic floor, not another guess.
    """
    attempts: list[ExtractionAttempt] = []

    # ---------------------------------------------------------------
    # Stage 1: primary extraction
    # ---------------------------------------------------------------
    try:
        candidate = primary(None)
        contract_payload = _extract_contract_payload(schema_name, candidate)
        attempts.append(ExtractionAttempt("primary", True))
        result = ExtractionResult(schema_name, "primary", candidate, contract_payload, attempts)
        _publish(result)
        return result
    except Exception as exc:  # noqa: BLE001 - any extractor/validator failure escalates
        reason = str(exc)
        attempts.append(ExtractionAttempt("primary", False, reason))

    # ---------------------------------------------------------------
    # Stage 2: refined extraction (stronger context/schema rules)
    # ---------------------------------------------------------------
    if refined is not None:
        try:
            candidate = refined(reason)
            contract_payload = _extract_contract_payload(schema_name, candidate)
            attempts.append(ExtractionAttempt("refined", True))
            result = ExtractionResult(schema_name, "refined", candidate, contract_payload, attempts)
            _publish(result)
            return result
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)
            attempts.append(ExtractionAttempt("refined", False, reason))

    # ---------------------------------------------------------------
    # Stage 3: deterministic safe fallback -- always valid, no LLM call
    # ---------------------------------------------------------------
    candidate = safe_default(reason)
    contract_payload = _extract_contract_payload(schema_name, candidate)
    attempts.append(ExtractionAttempt("safe_fallback", True))
    result = ExtractionResult(
        schema_name, "safe_fallback", candidate, contract_payload, attempts, fallback_active=True
    )
    _publish(result)
    return result


def _publish(result: ExtractionResult) -> None:
    """Best-effort mirror into the state bus; never raises."""
    try:
        from core.runtime.state_bus import get_state_bus

        bus = get_state_bus(create=False)
        if bus is not None:
            bus.record_extraction(result.as_log_dict())
    except Exception:
        pass
