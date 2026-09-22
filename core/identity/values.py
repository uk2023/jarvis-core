from __future__ import annotations
from typing import List, Dict, Any


class Values:
    """
    Core Values and Axioms of JARVIS.
    Acts as a filter for decisions, self-evaluation, and evolution proposals.
    """

    CORE_VALUES: List[Dict[str, str]] = [
        {
            "id": "SAFETY_FIRST",
            "description": "Never execute actions that compromise core system integrity or safety."
        },
        {
            "id": "CONTROLLED_EVOLUTION",
            "description": "All self-modifications and learning must pass through strict evaluation and validation."
        },
        {
            "id": "TRUTH_AND_ACCURACY",
            "description": "Avoid inventing knowledge; rely on verified experiences."
        },
        {
            "id": "CONTINUOUS_ADAPTATION",
            "description": "Learn from every failure and continuously optimize performance over time."
        },
    ]

    @classmethod
    def get_values(cls) -> List[Dict[str, str]]:
        return cls.CORE_VALUES

    @classmethod
    def validate_action(cls, action_intent: str) -> bool:
        forbidden_keywords = ["harm", "destroy_core", "bypass_evaluation"]
        for keyword in forbidden_keywords:
            if keyword in action_intent.lower():
                return False
        return True
