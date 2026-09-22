"""M3.2 semantic candidate evaluation, knowledge acceptance and promotion."""

from __future__ import annotations

from typing import Any, Dict

from .learning_boundary import SemanticLearningBoundary


class SemanticKnowledgePromotion:
    VERSION = "0.1.0"

    def __init__(self, boundary: SemanticLearningBoundary, learning_coordinator: Any):
        self.boundary = boundary
        self.learning = learning_coordinator

    @staticmethod
    def _experience(candidate: Dict[str, Any]) -> Dict[str, Any]:
        semantic = dict(candidate.get("semantic") or {})
        return {
            "event_type": "SEMANTIC_FALLBACK_INTERPRETATION",
            "context": {
                "semantic": semantic,
                "source": candidate.get("source", "unknown"),
            },
            "action": {
                "subject": "semantic_understanding",
                "predicate": "interpreted",
            },
            "outcome": {
                "success": True,
                "score": float(candidate.get("confidence", 0.0)),
                "subject": "semantic_understanding",
                "predicate": "interprets",
                "value": semantic,
                "knowledge": {
                    "subject": candidate.get("input_text", "").strip(),
                    "predicate": "semantic_intent",
                    "value": semantic,
                },
            },
            "semantic_candidate": candidate,
        }

    def evaluate_and_build(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self.boundary.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if candidate.status != "CANDIDATE":
            raise ValueError("Only a CANDIDATE may enter M3.2 evaluation")
        if self.learning is None:
            raise RuntimeError("LearningCoordinator is required to build accepted knowledge")

        result = self.learning.learn(
            experience=self._experience(candidate.as_dict()),
            auto_accept=False,
        )
        return {
            "candidate": candidate.as_dict(),
            "evaluation": result.get("evaluation"),
            "knowledge": result.get("knowledge"),
            "learning": result,
        }

    def accept_and_promote(self, candidate_id: str) -> Dict[str, Any]:
        result = self.evaluate_and_build(candidate_id)
        knowledge = result.get("knowledge")
        if not isinstance(knowledge, dict) or not knowledge.get("id"):
            raise ValueError("Learning did not produce a knowledge candidate")

        accepted = self.learning.accept_knowledge(knowledge["id"])
        if accepted.get("status") != "ACCEPTED":
            raise ValueError("Knowledge candidate was not accepted")

        candidate = self.boundary.accept_candidate(candidate_id)
        candidate["semantic_knowledge_id"] = accepted.get("semantic_knowledge_id")
        return {
            "candidate": candidate,
            "evaluation": result["evaluation"],
            "knowledge": accepted,
            "promoted_capability": self.boundary.promote(candidate_id),
        }

    def reject(self, candidate_id: str, reason: str = "") -> Dict[str, Any]:
        """Reject a candidate without creating or persisting knowledge.

        Rejection is deliberately terminal at the semantic boundary. If a
        LearningCoordinator is present, it may record the evaluation/rejection;
        otherwise the candidate can still be safely rejected without inventing
        a knowledge object or bypassing the memory architecture.
        """
        candidate = self.boundary.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if candidate.status != "CANDIDATE":
            raise ValueError("Only a CANDIDATE may be rejected")

        rejected_candidate = self.boundary.reject_candidate(candidate_id, reason=reason)
        return {
            "candidate": rejected_candidate,
            "evaluation": {
                "status": "REJECTED",
                "reason": reason,
            },
            "knowledge": None,
            "promoted_capability": None,
        }
