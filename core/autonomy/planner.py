from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event


class Planner:
    """
    Turns a goal (or a curiosity candidate) into an ordered list of
    small executable steps.

    Two modes:
      - Deterministic mode (default): rule-based decomposition for the
        goal "types" the organism already understands. No LLM call,
        fully predictable, always available.
      - Reasoning mode: if an llm_bridge is provided, ambiguous or
        novel goals are handed to it with a constrained prompt that
        forces a JSON step list back out. This keeps the LLM as a
        *tool the planner uses*, not the thing doing the deciding.

    A step is a plain dict:
        {"action": str, "detail": str, "requires_confirmation": bool}
    """

    SYSTEM_PROMPT = (
        "You are the planning module of an autonomous local agent. "
        "Given a goal, output ONLY a JSON array of steps. "
        "Each step is an object: "
        '{"action": "<short_verb_phrase>", "detail": "<one sentence>", '
        '"requires_confirmation": true|false}. '
        "Mark requires_confirmation=true for anything that modifies files, "
        "runs code, or affects the outside world. Output JSON only, "
        "no prose, no markdown fences."
    )

    def __init__(self, llm_bridge=None, max_steps: int = 8):
        self.llm_bridge = llm_bridge
        self.max_steps = max_steps

    def plan(self, goal: Any) -> List[Dict[str, Any]]:
        if goal is None:
            return []

        text = goal.get("text") if isinstance(goal, dict) else str(goal)

        if not text:
            return []

        rule_based = self._rule_based_plan(text)

        if rule_based is not None:
            return rule_based

        if self.llm_bridge is not None:
            return self._llm_plan(text)

        # No rule matched and no reasoning model available: return a
        # single, honest step rather than pretending to have a plan.
        return [
            {
                "action": "clarify_goal",
                "detail": f"No known strategy for: '{text}'. Ask the user for more detail.",
                "requires_confirmation": False,
            }
        ]

    # =============================================================
    # DETERMINISTIC RULES
    # =============================================================

    def _rule_based_plan(self, text: str) -> Optional[List[Dict[str, Any]]]:
        lowered = text.lower()

        if lowered.startswith("verify_knowledge") or "low confidence" in lowered:
            return [
                {
                    "action": "search_supporting_evidence",
                    "detail": f"Look for evidence relevant to: {text}",
                    "requires_confirmation": False,
                },
                {
                    "action": "update_confidence",
                    "detail": "Adjust confidence score based on findings.",
                    "requires_confirmation": False,
                },
            ]

        if lowered.startswith("learn ") or lowered.startswith("understand "):
            topic = text.split(" ", 1)[1] if " " in text else text
            return [
                {
                    "action": "gather_information",
                    "detail": f"Collect information about {topic}.",
                    "requires_confirmation": False,
                },
                {
                    "action": "summarize",
                    "detail": f"Summarize what was learned about {topic} into semantic memory.",
                    "requires_confirmation": False,
                },
                {
                    "action": "self_test",
                    "detail": f"Check understanding of {topic} against a small self-quiz.",
                    "requires_confirmation": False,
                },
            ]

        return None

    # =============================================================
    # REASONING-ASSISTED PLANNING
    # =============================================================

    def _llm_plan(self, text: str) -> List[Dict[str, Any]]:
        try:
            raw = self.llm_bridge.generate_response(self.SYSTEM_PROMPT, text)
            steps = json.loads(raw)

            if not isinstance(steps, list):
                raise ValueError("Planner LLM did not return a list.")

            cleaned = []

            for step in steps[: self.max_steps]:
                if not isinstance(step, dict) or "action" not in step:
                    continue

                cleaned.append(
                    {
                        "action": str(step.get("action")),
                        "detail": str(step.get("detail", "")),
                        "requires_confirmation": bool(
                            step.get("requires_confirmation", True)
                        ),
                    }
                )

            return cleaned or self._fallback_step(text)

        except Exception as exc:
            log_event("planner", f"LLM planning failed: {exc}", level="warning")
            return self._fallback_step(text)

    @staticmethod
    def _fallback_step(text: str) -> List[Dict[str, Any]]:
        return [
            {
                "action": "clarify_goal",
                "detail": f"Planning failed for: '{text}'. Ask the user for more detail.",
                "requires_confirmation": False,
            }
        ]
