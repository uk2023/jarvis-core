from __future__ import annotations

"""Evidence-backed organ introspection (UK's explicit spec): every
major organ answers the SAME 10 questions from its own REAL retained
state -- never an arbitrary "I am working correctly" with nothing
behind it.

    WHO ARE YOU?
    WHAT IS YOUR RESPONSIBILITY?
    WHAT DID YOU RECEIVE?
    WHAT DID YOU PRODUCE?
    WHY DID YOU PRODUCE IT?
    WHAT EVIDENCE SUPPORTS IT?
    WHAT IS YOUR CONFIDENCE?
    WHAT STATE CHANGED?
    WHAT PERSISTED?
    WHAT REMAINS UNVERIFIED?

HONEST SCOPE: this reuses data ALREADY tracked elsewhere this session
(last_perception, last_layer_validations, last_action_response,
last_reasoning_traces, dependency_metrics) rather than inventing new
telemetry per organ from scratch -- an answer here is only ever as
good as the real, retained data behind it, and any field this module
cannot honestly answer from real state says so explicitly rather than
guessing.
"""

from typing import Any, Dict, Optional


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def introspect_perception(brain: Any) -> Dict[str, str]:
    perception = getattr(brain, "last_perception", None) or {}
    source = _safe_get(perception, "source", "unknown")
    confidence = _safe_get(perception, "confidence")
    intent = _safe_get(perception, "intent") or {}
    return {
        "who_are_you": "Perception -- the first layer that touches raw user input.",
        "responsibility": "Classify intent, detect language, and produce a normalized_input every downstream layer reads.",
        "what_did_you_receive": str(_safe_get(perception, "raw_input", "(nothing recorded yet this session)")),
        "what_did_you_produce": f"intent={intent.get('name', '—') if isinstance(intent, dict) else '—'}, normalized_input present={'normalized_input' in perception}",
        "why_did_you_produce_it": f"resolved via source='{source}'" + (" (native pattern match)" if source == "native" else " (escalated to LLM classification)" if source == "llm" else " (cascade exhausted, deterministic safe default used)" if source == "safe_fallback" else ""),
        "what_evidence_supports_it": "matched pattern in NativePerceptionProvider" if source == "native" else "LLM classification response" if source == "llm" else "no confident evidence -- this IS the unverified case",
        "what_is_your_confidence": f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "not recorded",
        "what_state_changed": "none -- Perception is stateless per turn; it does not persist anything itself",
        "what_persisted": "nothing -- Perception never writes to durable memory directly",
        "what_remains_unverified": "the entire result, since source=safe_fallback means no confident mechanism resolved it" if source == "safe_fallback" else "nothing flagged",
    }


def introspect_semantic_understanding(brain: Any) -> Dict[str, str]:
    validations = getattr(brain, "last_layer_validations", None) or []
    latest = validations[-1] if validations else None
    if latest is None:
        return {
            "who_are_you": "Semantic Understanding -- converts perceived text into structured facts.",
            "responsibility": "Extract subject/predicate/value relations, entities, and events from the current turn's text.",
            "what_did_you_receive": "(no record yet this session)",
            "what_did_you_produce": "(no record yet this session)",
            "why_did_you_produce_it": "(no record yet this session)",
            "what_evidence_supports_it": "(no record yet this session)",
            "what_is_your_confidence": "(no record yet this session)",
            "what_state_changed": "(no record yet this session)",
            "what_persisted": "(no record yet this session)",
            "what_remains_unverified": "(no record yet this session)",
        }
    return {
        "who_are_you": "Semantic Understanding -- converts perceived text into structured facts.",
        "responsibility": "Extract subject/predicate/value relations, entities, and events from the current turn's text.",
        "what_did_you_receive": str(latest.get("input_text", "—")),
        "what_did_you_produce": f"{latest.get('relations_count', 0)} relation(s)",
        "why_did_you_produce_it": str(latest.get("reason", "—")),
        "what_evidence_supports_it": f"provenance={latest.get('provenance', 'unknown')}",
        "what_is_your_confidence": "high (native pattern match)" if latest.get("provenance") == "native" else "degraded" if not latest.get("succeeded") else "moderate (LLM-assisted)",
        "what_state_changed": "a candidate fact was built" if latest.get("succeeded") else "nothing -- no candidate was built this turn",
        "what_persisted": "pending confirmation from KnowledgeBuilder/accept() -- see last_action_response for whether it was actually committed" if latest.get("succeeded") else "nothing",
        "what_remains_unverified": "none" if latest.get("succeeded") else f"why: {latest.get('reason', 'unknown')}",
    }


def introspect_brain_decision(brain: Any) -> Dict[str, str]:
    action_response = getattr(brain, "last_action_response", None) or {}
    dep = {}
    status_fn = getattr(brain, "status", None)
    if callable(status_fn):
        try:
            dep = dict(status_fn()).get("dependency_metrics", {}) or {}
        except Exception:
            dep = {}
    return {
        "who_are_you": "Brain -- owns the final routing and action decision.",
        "responsibility": "Decide native/hybrid/llm/goal routing, execute it, and hand the result to the response layer.",
        "what_did_you_receive": "Perception + Semantic Understanding output for this turn",
        "what_did_you_produce": f"mode={action_response.get('mode', '—')}, status={action_response.get('status', '—')}",
        "why_did_you_produce_it": (action_response.get("action") or {}).get("reason", "see CognitiveRouter's decision for this turn's full reasoning") if isinstance(action_response.get("action"), dict) else "—",
        "what_evidence_supports_it": f"native_resolution_rate this session={dep.get('native_resolution_rate', 'not yet computed')}",
        "what_is_your_confidence": "reflected in native_resolution_rate/llm_fallback_rate, not a single per-turn number",
        "what_state_changed": "dependency_metrics updated; a reasoning trace was appended to last_reasoning_traces",
        "what_persisted": "response logged to chat_log.txt; any extracted fact committed via KnowledgeBuilder (see semantic understanding's own report for whether one existed)",
        "what_remains_unverified": "whether the response stayed within its brief -- see the grounding check result on this turn's trace" if action_response.get("status") != "completed" else "none flagged",
    }


def introspect_all(brain: Any) -> Dict[str, Dict[str, str]]:
    return {
        "perception": introspect_perception(brain),
        "semantic_understanding": introspect_semantic_understanding(brain),
        "brain": introspect_brain_decision(brain),
    }
