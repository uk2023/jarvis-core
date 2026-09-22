from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol

from ..contracts import validate_output
from ..contracts.extraction import run_extraction_cascade
from .llm_bridge import can_afford_another_llm_call


@dataclass(frozen=True)
class PerceptionResult:
    """Stable machine-readable meaning passed from perception to Brain/router."""
    user_input: str
    normalized_text: str
    intent: Dict[str, Any] = field(default_factory=dict)
    entities: Dict[str, Any] = field(default_factory=dict)
    goal: Optional[Any] = None
    requested_capability: Optional[str] = None
    speech_act: Optional[str] = None
    language: Optional[str] = None
    confidence: float = 0.0
    uncertainty: float = 1.0
    source: str = "unknown"
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    # Cost-minimization: when the LLM cascade below fires, it now asks
    # for relations/events/references TOO (semantic understanding's
    # fields, not just perception's own) -- so ONE call can satisfy
    # both layers' needs instead of two separate ones. These are
    # deliberately NOT part of perception.output's formal contract
    # (see as_contract_payload below); they exist purely so
    # blueprint_brain.py's semantic-understanding fallback can reuse
    # them instead of making its own redundant LLM call.
    relations: list = field(default_factory=list)
    events: list = field(default_factory=list)
    references: list = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()

    def as_contract_payload(self) -> Dict[str, Any]:
        """Return the canonical Perception output contract."""
        entities = self.entities
        if isinstance(entities, dict):
            entities = [entities] if entities else []
        elif not isinstance(entities, list):
            entities = []

        return validate_output(
            "perception",
            {
                "normalized_input": self.normalized_text,
                "language": self.language or "unknown",
                "confidence": float(self.confidence),
                "basic_intent": self.intent,
                "entities": entities,
                "metadata": {
                    "source": self.source,
                    "uncertainty": float(self.uncertainty),
                    "goal": self.goal,
                    "requested_capability": self.requested_capability,
                    "speech_act": self.speech_act,
                    "reason": self.reason,
                },
            },
        )


class PerceptionProvider(Protocol):
    """Replaceable provider; LLM is only one possible implementation."""
    name: str

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> PerceptionResult:
        ...


class NativePerceptionProvider:
    """Deterministic Level-0 perception (blueprint section 4: LEVEL 0 —
    deterministic normalization, tried before any LLM/SLM escalation).

    Handles a small set of unambiguous conversational patterns (greetings,
    status checks, thanks, farewells) without any LLM call. Returns None
    for anything it doesn't confidently recognize, so PerceptionEngine
    falls through to the next provider (LLM) -- this is a genuine
    escalation cascade, not a replacement for LLM perception.
    """
    name = "native"

    _PATTERNS: tuple = (
        ("greeting", re.compile(r"^(hi|hello|hey|hlo|yo|namaste|namaskar)\b", re.I)),
        ("status_check", re.compile(r"^(status|health|ping|are you (online|there|up)|you there)\b", re.I)),
        ("thanks", re.compile(r"^(thanks|thank you|shukriya|dhanyavad)\b", re.I)),
        ("farewell", re.compile(r"^(bye|goodbye|see you|tata|good night)\b", re.I)),
    )

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> Optional[PerceptionResult]:
        normalized = (user_input or "").strip()
        if not normalized:
            return None
        for intent_name, pattern in self._PATTERNS:
            if pattern.match(normalized):
                return PerceptionResult(
                    user_input=user_input,
                    normalized_text=normalized,
                    intent={"name": intent_name, "confidence": 0.95},
                    language="unknown",
                    confidence=0.95,
                    uncertainty=0.05,
                    source=self.name,
                    reason=f"Matched deterministic pattern: {intent_name}",
                )
        return None


class LLMPerceptionProvider:
    """LLM-backed perception provider, guarded by a 3-stage extraction
    cascade (core.contracts.extraction.run_extraction_cascade):

        Stage 1 (primary)   -- one call with the normal system prompt.
        Stage 2 (refined)   -- if Stage 1's output fails contract
                                validation (invalid JSON, wrong shape,
                                bad types), retry once with a stronger,
                                explicit prompt that quotes back the
                                validator's own failure reason.
        Stage 3 (fallback)  -- if Stage 2 also fails, return a
                                deterministic, always-valid low-
                                confidence PerceptionResult. No further
                                LLM calls are made, and the router/
                                Brain always receives a structurally
                                valid perception -- never raw text.

    Before this cascade existed, a weak/offline model that rambled
    instead of returning JSON produced a *silently accepted* zero-
    confidence result with no retry -- this is what actually fixes
    that.
    """
    name = "llm"

    SYSTEM_PROMPT = (
        "Convert a user's message into one structured perception. "
        "Return ONLY valid JSON. Never answer the user and never invent facts. "
        "Use an empty intent name and low confidence when meaning is unclear. "
        "Required keys: intent, entities, goal, requested_capability, "
        "speech_act, language, confidence, reason, relations, events, references. "
        "relations/events/references may be empty arrays if none are present -- "
        "they are used by a downstream layer, so include them even though they "
        "are not the main focus of this task."
    )

    # Retrieval-based context bound (blueprint Phase 4): perception runs
    # on every single turn, so an unbounded context dict here means every
    # message -- including a bare "hello" -- pays for the full memory/
    # knowledge/graph payload. Cap item count and per-item length before
    # the dict is ever stringified into the prompt, rather than relying
    # solely on the downstream token budgeter (whose word-count estimate
    # can diverge from the real byte size of dense/structured content).
    _CONTEXT_MAX_ITEMS = 3
    _CONTEXT_MAX_ITEM_CHARS = 150

    def __init__(self, llm_bridge: Any):
        self.llm = llm_bridge

    @classmethod
    def _bounded_context(cls, context: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        if not context:
            return {}
        bounded: Dict[str, Any] = {}
        for key, value in dict(context).items():
            if isinstance(value, (list, tuple)):
                items = []
                for item in list(value)[: cls._CONTEXT_MAX_ITEMS]:
                    text = str(item)
                    if len(text) > cls._CONTEXT_MAX_ITEM_CHARS:
                        text = text[: cls._CONTEXT_MAX_ITEM_CHARS] + "…"
                    items.append(text)
                bounded[key] = items
            else:
                text = str(value)
                if len(text) > cls._CONTEXT_MAX_ITEM_CHARS:
                    text = text[: cls._CONTEXT_MAX_ITEM_CHARS] + "…"
                bounded[key] = text
        return bounded

    @staticmethod
    def _json_shape_hint() -> str:
        return (
            'JSON shape: {"intent":{"name":"...","confidence":0.0},'
            '"entities":{},"goal":null,"requested_capability":null,'
            '"speech_act":null,"language":"...","confidence":0.0,"reason":"...",'
            '"relations":[],"events":[],"references":[]}'
        )

    def _build_prompt(self, user_input: str, context: Optional[Mapping[str, Any]], reinforced_reason: Optional[str]) -> str:
        base = (
            f"User message: {user_input}\n"
            f"Context: {self._bounded_context(context)}\n"
            f"{self._json_shape_hint()}"
        )
        if reinforced_reason is None:
            return base
        # Stage 2: inject stronger, explicit context rules -- quote the
        # validator's own failure reason back so the retry targets the
        # actual defect instead of guessing blind.
        return (
            f"Your previous output was REJECTED by the schema validator: {reinforced_reason}\n"
            "This time return ONLY compact, single-line JSON -- no prose, "
            "no markdown code fences, nothing before or after the JSON "
            "object. Every required key must be present even when its "
            "value is null, {} or 0.0.\n"
            f"{base}"
        )

    def _system_prompt(self, reinforced: bool) -> str:
        if not reinforced:
            return self.SYSTEM_PROMPT
        return self.SYSTEM_PROMPT + " STRICT MODE: output ONLY the JSON object and absolutely nothing else."

    def _can_afford_another_call(self) -> bool:
        """True if the shared per-turn LLM call budget has room for one
        more call here AND still leaves at least one call free for
        whatever needs the LLM after perception finishes this turn --
        semantic understanding's own LLM fallback, or the main
        response-generation call. Without this, perception's own
        Stage-2 retry could greedily spend the entire shared per-turn
        budget on itself, starving everything downstream (this is
        exactly what produced "LLM call budget exceeded" crashes for
        almost any non-trivial message once the cascade in this file
        started making up to 2 calls instead of at most 1).
        See core/orchestration/llm_bridge.py's can_afford_another_llm_call
        -- shared with semantic understanding's own retry now too."""
        return can_afford_another_llm_call(self.llm)

    def _call_llm_and_parse(
        self,
        user_input: str,
        context: Optional[Mapping[str, Any]],
        reinforced_reason: Optional[str] = None,
    ) -> PerceptionResult:
        """One extraction attempt. Raises on any contract violation so
        the cascade in perceive() can decide whether to escalate --
        this method must NOT swallow failures into a fake success."""
        if reinforced_reason is not None and not self._can_afford_another_call():
            # Skip the refined retry rather than spend the turn's last
            # shared call on it -- the cascade catches this exactly like
            # any other Stage-2 failure and falls through to the
            # deterministic safe default (no LLM call, always valid).
            raise RuntimeError(
                "skipping refined retry: insufficient remaining per-turn LLM "
                "call budget to retry without starving the rest of this turn"
            )
        prompt = self._build_prompt(user_input, context, reinforced_reason)
        raw = self.llm.generate_response(
            system_prompt=self._system_prompt(reinforced_reason is not None),
            user_input=prompt,
            max_tokens=300,
            temperature=0.0,
            level="perception_and_understanding",
            # THE ACTUAL FIX for "primary:fail -> refined:fail ->
            # safe_fallback" on nearly every turn (found 2026-09-11
            # from real monitor.py output): openai/gpt-oss-120b is a
            # reasoning model and does NOT reliably emit bare JSON
            # from a system-prompt instruction alone. json_object mode
            # makes the API itself guarantee syntactically valid JSON.
            response_format={"type": "json_object"},
            # Bug 13 (latency): classification, not deep reasoning --
            # see llm_bridge.py's GroqEngine.generate() comment.
            reasoning_effort="low",
            # UK's explicit instruction after the model-override
            # feature caused a real production bug (see llm_bridge.py's
            # GroqEngine.generate() fix): always use the configured
            # default model (openai/gpt-oss-120b), no per-call override.
        )
        cleaned = re.sub(r"^```(?:json)?|```$", "", str(raw).strip(), flags=re.MULTILINE).strip()
        from ..contracts.extraction import extract_first_json_object
        data = extract_first_json_object(cleaned)  # raises -> cascade escalates
        if not isinstance(data, dict):
            raise ValueError("provider JSON did not decode to an object")

        intent = data.get("intent") if isinstance(data.get("intent"), dict) else {}
        confidence = float(data.get("confidence", intent.get("confidence", 0.0)) or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        stage_label = "llm" if reinforced_reason is None else "llm_refined"
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent=intent,
            entities=data.get("entities") if isinstance(data.get("entities"), dict) else {},
            goal=data.get("goal"),
            requested_capability=data.get("requested_capability"),
            speech_act=data.get("speech_act"),
            language=data.get("language"),
            confidence=confidence,
            uncertainty=1.0 - confidence,
            source=stage_label,
            reason=str(data.get("reason", "LLM structured perception")),
            relations=data.get("relations") if isinstance(data.get("relations"), list) else [],
            events=data.get("events") if isinstance(data.get("events"), list) else [],
            references=data.get("references") if isinstance(data.get("references"), list) else [],
        )

    def _safe_default(self, user_input: str, reason: str) -> PerceptionResult:
        """Stage 3: deterministic, always-valid floor. No LLM call."""
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={},
            entities={},
            language="unknown",
            confidence=0.0,
            uncertainty=1.0,
            source="safe_fallback",
            reason=f"Extraction cascade exhausted after primary + refined attempts: {reason}",
        )

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> PerceptionResult:
        result = run_extraction_cascade(
            "perception",
            primary=lambda _reason: self._call_llm_and_parse(user_input, context),
            refined=lambda reason: self._call_llm_and_parse(user_input, context, reinforced_reason=reason),
            safe_default=lambda reason: self._safe_default(user_input, reason),
        )
        return result.payload


class PerceptionEngine:
    """Provider-agnostic perception organ with explicit provider ordering."""
    VERSION = "0.3.0"

    def __init__(self, providers=None, state=None):
        self.providers = list(providers or [])
        self.state = state
        self.last_result: Optional[PerceptionResult] = None
        self.last_contract: Optional[Dict[str, Any]] = None

    def add_provider(self, provider: PerceptionProvider) -> None:
        self.providers.append(provider)

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> PerceptionResult:
        for provider in self.providers:
            try:
                result = provider.perceive(user_input, context=context)
                if not isinstance(result, PerceptionResult):
                    continue
                self.last_contract = result.as_contract_payload()
                self.last_result = result
                self._publish_state(result)
                return result
            except Exception:
                continue

        result = PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            language="unknown",
            source="none",
            reason="No perception provider produced a result.",
        )
        self.last_contract = result.as_contract_payload()
        self.last_result = result
        self._publish_state(result)
        return result

    def _publish_state(self, result: PerceptionResult) -> None:
        if self.state is None:
            return
        try:
            self.state.update(last_perception=result.as_dict())
        except Exception:
            pass
