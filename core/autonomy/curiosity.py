from __future__ import annotations

import time
from typing import Any, Dict, List


class Curiosity:
    """
    Generates safe, non-executing learning *candidates* from signals
    already present in the organism: unresolved uncertainty, stalled
    goals, and repeated low-confidence knowledge.

    Curiosity never acts by itself. It only proposes candidates that
    the Planner/IdleLoop may later turn into real, sandboxed steps.
    Every candidate carries a reason so behaviour stays inspectable
    instead of being an opaque "the AI decided to..." black box.
    """

    def __init__(self, min_confidence: float = 0.55, max_candidates: int = 5):
        self.min_confidence = min_confidence
        self.max_candidates = max_candidates

    def candidates(
        self,
        state: Any = None,
        goals: List[Dict[str, Any]] = None,
        knowledge_gaps: List[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        goals = goals or []
        knowledge_gaps = knowledge_gaps or []

        found: List[Dict[str, Any]] = []

        # ---------------------------------------------------------
        # 1) Uncertainty reported by InternalState
        # ---------------------------------------------------------
        uncertainty = self._get(state, "uncertainty", None)

        if isinstance(uncertainty, (int, float)) and uncertainty > 0.6:
            found.append(
                {
                    "type": "reduce_uncertainty",
                    "reason": f"Internal uncertainty is high ({uncertainty:.2f}).",
                    "priority": min(1.0, uncertainty),
                }
            )

        # ---------------------------------------------------------
        # 2) Stalled goals (created a while ago, still pending)
        # ---------------------------------------------------------
        now = time.time()

        for goal in goals:
            if goal.get("status") not in ("pending", "active"):
                continue

            age_hours = (now - goal.get("created_at", now)) / 3600.0

            if age_hours > 6 and not goal.get("progress"):
                found.append(
                    {
                        "type": "revisit_stalled_goal",
                        "reason": f"Goal '{goal.get('text')}' has had no progress in {age_hours:.1f}h.",
                        "priority": 0.4 + min(0.4, age_hours / 48.0),
                        "goal_id": goal.get("id"),
                    }
                )

        # ---------------------------------------------------------
        # 3) Low-confidence knowledge worth re-checking
        # ---------------------------------------------------------
        for item in knowledge_gaps:
            confidence = item.get("confidence", 1.0)

            if confidence < self.min_confidence:
                found.append(
                    {
                        "type": "verify_knowledge",
                        "reason": (
                            f"Knowledge about '{item.get('subject')}' has low "
                            f"confidence ({confidence:.2f})."
                        ),
                        "priority": 1.0 - confidence,
                        "knowledge_id": item.get("knowledge_id"),
                    }
                )

        found.sort(key=lambda c: -c["priority"])
        return found[: self.max_candidates]

    @staticmethod
    def _get(state: Any, attr: str, default: Any) -> Any:
        if state is None:
            return default

        if isinstance(state, dict):
            return state.get(attr, default)

        return getattr(state, attr, default)
