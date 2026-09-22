from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class CognitiveDecision:
    mode: str
    confidence: float
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    llm_required: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "llm_required": self.llm_required,
        }


class CognitiveRouter:
    """Evidence-driven route authority. It consumes Cognition output only."""

    VERSION = "0.8.0"
    EXECUTABLE_MODES = frozenset({"goal", "native", "hybrid", "llm"})
    LEGACY_NON_EXECUTABLE_MODES = frozenset({"known", "tool"})

    def __init__(self, minimum_confidence: Optional[float] = None) -> None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config_path = os.path.join(root, "config", "cognition.json")
        configured = None
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                configured = json.load(handle).get("routing", {}).get("minimum_confidence")
        except (OSError, ValueError, AttributeError):
            pass
        value = minimum_confidence if minimum_confidence is not None else configured
        if value is None:
            raise RuntimeError("Cognitive routing policy is not configured")
        self.minimum_confidence = max(0.0, min(1.0, float(value)))

    @staticmethod
    def _count(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, Mapping):
            return len(value)
        if isinstance(value, (str, bytes)):
            return 1 if value else 0
        try:
            return len(value)
        except TypeError:
            return 1

    def decide(
        self,
        *,
        user_input: str,
        cognition_input: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
        skills: Any = None,
        identity: Any = None,
        goals: Any = None,
        perception: Optional[Mapping[str, Any]] = None,
        explicit_intent: Optional[Mapping[str, Any]] = None,
        brain_directive: Optional[Mapping[str, Any]] = None,
    ) -> CognitiveDecision:
        """Choose the canonical executable Brain route from Cognition evidence.

        AUTHORITY INVERSION (2026-09-13, UK: "router ko brain bataye kab
        native use karna hai"): when Brain supplies a directive (see
        information_need.decide_information_need), that directive WINS.
        The router's own evidence counting below is a fallback for turns
        Brain did not classify -- it no longer gets to overrule Brain on
        where an answer should come from.

        Why the inversion matters: counting matches can only say "I found
        3 things", never "this question is about the conversation itself".
        Brain knows the KIND of knowing required; the router only ever saw
        quantities, which is why 95% of turns used to end up on the LLM.

        NATIVE is the canonical route for an available organism capability.
        """
        if brain_directive:
            directive_route = str(brain_directive.get("route") or "").strip().lower()
            if directive_route in {"native", "hybrid", "llm", "goal", "clarify"}:
                evidence = {
                    "decided_by": "brain",
                    "information_source": brain_directive.get("source"),
                    "requires_live_data": bool(brain_directive.get("requires_live_data")),
                    "brain_signals": brain_directive.get("signals"),
                }
                return CognitiveDecision(
                    directive_route,
                    float(brain_directive.get("confidence") or 0.0),
                    str(brain_directive.get("reason") or "Brain directed this route."),
                    evidence,
                    directive_route == "llm",
                )

        if cognition_input is not None:
            c = dict(cognition_input)
            semantic = dict(c.get("semantic") or {})
            intent = dict(semantic.get("intent") or {})
            memory_context = dict(c.get("memory") or {})
            knowledge_context = dict(c.get("knowledge") or {})
            state_context = dict(c.get("state") or {})
            capability_context = c.get("capabilities") or {}
            available_skills = capability_context.get("skills") if isinstance(capability_context, Mapping) else capability_context
            available_skills = available_skills or skills
            active_goals = c.get("goals") or goals
            perceived_goal = semantic.get("goal") or intent.get("goal")
            confidence = float(semantic.get("confidence", 0.0) or 0.0)
            normalized_text = semantic.get("normalized_text") or user_input
            evidence_source = "cognition"
            ctx = {**memory_context, **knowledge_context}
            if state_context:
                ctx["state"] = state_context
        else:
            p = dict(perception or {})
            intent = dict(p.get("intent") or explicit_intent or {})
            p_input = p.get("user_input") or p.get("source_input")
            input_matches = (p_input == user_input) if p_input is not None else explicit_intent is not None
            confidence = float(p.get("confidence", intent.get("confidence", 0.0)) or 0.0)
            if explicit_intent is not None and "confidence" not in p and "confidence" not in intent:
                confidence = 1.0
            confidence = max(0.0, min(1.0, confidence))
            ctx = dict(context or {})
            available_skills = skills
            active_goals = goals
            perceived_goal = p.get("goal")
            normalized_text = p.get("normalized_text") or user_input
            evidence_source = "compatibility"
            if not input_matches:
                confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))
        memory_count = self._count(ctx.get("recent_experiences"))
        knowledge_count = self._count(ctx.get("relevant_knowledge"))
        graph_count = self._count(ctx.get("graph_relations"))
        skill_count = self._count(available_skills)
        goal_count = self._count(active_goals)
        requested_mode = str(intent.get("execution_mode") or intent.get("route") or "").strip().lower()
        evidence = {
            "memory_matches": memory_count,
            "knowledge_matches": knowledge_count,
            "graph_relations": graph_count,
            "available_skills": skill_count,
            "active_goals": goal_count,
            "structured_intent": bool(intent),
            "semantic_source": evidence_source,
            "semantic_confidence": confidence,
            "input_present": bool((normalized_text or "").strip()),
            "requested_execution_mode": requested_mode or None,
            "perceived_goal": perceived_goal,
        }
        usable = bool(intent) and confidence >= self.minimum_confidence
        if usable and intent.get("requires_confirmation") is True:
            return CognitiveDecision(
                "clarify",
                confidence,
                "Cognition requires confirmation before native execution.",
                evidence,
                False,
            )
        if usable and perceived_goal:
            return CognitiveDecision("goal", confidence, "Cognition identified an explicit user goal.", evidence, False)
        if usable and requested_mode == "hybrid":
            if skill_count and intent.get("skill"):
                return CognitiveDecision("hybrid", confidence, "Cognition selected hybrid execution with an available native capability.", evidence, True)
            return CognitiveDecision("llm", confidence, "Hybrid was requested but no usable native capability is available; using LLM cognition.", evidence, True)
        if usable and skill_count:
            return CognitiveDecision("native", confidence, "Cognition identified a usable organism capability; NATIVE is the canonical execution route.", evidence, False)
        if usable and requested_mode in self.LEGACY_NON_EXECUTABLE_MODES:
            return CognitiveDecision("llm", confidence, "No usable native capability is available; LLM is the genuine fallback route.", evidence, True)
        return CognitiveDecision("llm", confidence, "Cognition requires language cognition for this turn; no executable native capability was selected.", evidence, True)
