"""Integration tests for the Perception -> Semantic Understanding -> Cognition boundary.

Run from repository root:
    python3 -m core.contracts.test_pipeline_integration
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..cognition.semantic_understanding import SemanticUnderstanding
from ..orchestration.blueprint_brain import BlueprintBrain
from ..orchestration.perception import PerceptionEngine, PerceptionResult
from . import validate_input, validate_output


class StubPerceptionProvider:
    """Deterministic provider used to exercise the real runtime wiring."""

    name = "integration_stub"

    def perceive(
        self,
        user_input: str,
        context: Optional[Mapping[str, Any]] = None,
    ) -> PerceptionResult:
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "statement", "confidence": 0.95, "source": self.name},
            entities=[{"text": "Python", "type": "topic", "confidence": 0.9}],
            language="en",
            confidence=0.95,
            uncertainty=0.05,
            source=self.name,
            reason="deterministic integration provider",
        )


def _make_brain() -> BlueprintBrain:
    return BlueprintBrain(
        perception_engine=PerceptionEngine(providers=[StubPerceptionProvider()]),
        semantic_understanding=SemanticUnderstanding(semantic_memory=None),
    )


def test_runtime_pipeline_contracts() -> None:
    """Exercise the actual direct BlueprintBrain semantic path.

    SemanticBrainAdapter was an integration proxy and is intentionally gone:
    BlueprintBrain is now the live owner of the Perception -> Semantic
    Understanding boundary, so this test inspects the same runtime contract
    records rather than recreating the removed adapter.
    """
    brain = _make_brain()
    result = brain._perceive("I like Python")

    perception_contract = validate_output(
        "perception", brain.last_contracts["perception.output"]
    )
    semantic_input = validate_input(
        "semantic_understanding", brain.last_contracts["semantic_understanding.input"]
    )
    semantic_contract = validate_output(
        "semantic_understanding", brain.last_contracts["semantic_understanding.output"]
    )
    cognition_input = validate_input(
        "cognition", brain._build_cognition_input("I like Python", result)
    )

    assert result["semantic_understanding"] == semantic_contract
    assert brain.last_contracts["cognition.input"] == cognition_input
    assert semantic_input["perception"] == perception_contract
    assert semantic_contract["normalized_text"] == "I like Python"
    assert semantic_contract["intent"]["name"] == "statement"


def test_semantic_layer_is_authoritative_and_not_legacy_double_parsed() -> None:
    brain = _make_brain()

    first = brain._perceive("I am learning Python")
    second = brain._perceive("I am learning Python")

    assert first["semantic_understanding"]["events"]
    assert first["semantic_understanding"]["events"][0]["event_type"] == "learning_started"
    assert second["semantic_understanding"]["events"]
    assert "legacy_semantic" not in first["semantic_understanding"]
    assert "legacy_semantic" not in second["semantic_understanding"]


def main() -> None:
    test_runtime_pipeline_contracts()
    test_semantic_layer_is_authoritative_and_not_legacy_double_parsed()
    print("PASS: runtime Perception -> Semantic Understanding -> Cognition integration")
    print("PASS: all three runtime boundaries validated against canonical contracts")
    print("PASS: legacy double-parsing path is absent from the authoritative semantic payload")


if __name__ == "__main__":
    main()
