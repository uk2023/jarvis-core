"""Milestone 3.1 runtime test: real Brain LLM fallback -> learning intake."""

from __future__ import annotations

from typing import Any

from core.cognition.semantic_understanding.brain_adapter import SemanticBrainAdapter
from core.cognition.semantic_understanding.bridge_to_cognition import SemanticUnderstanding


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_response(self, *, system_prompt: str, user_input: str,
                          max_tokens: int, temperature: float) -> str:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_input": user_input,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return (
            '{"semantic":{"normalized":"explain my new concept",'
            '"intent":{"name":"concept_explanation"},"entities":[],'
            '"relations":[],"events":[],"references":[],"confidence":0.91,'
            '"provenance":{"source":"llm_fallback"},"inferences":[],'
            '"unknowns":[]}}'
        )


class FakeLearning:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], bool]] = []

    def learn(self, experience: dict[str, Any], auto_accept: bool = False) -> dict[str, Any]:
        self.calls.append((experience, auto_accept))
        return {"success": True, "accepted": False, "knowledge": None}


class FakeBrain:
    def __init__(self) -> None:
        self.llm = FakeLLM()
        self.learning_coordinator = FakeLearning()
        self._semantic_understanding_attached = False

    def _perceive(self, user_input: str) -> dict[str, Any]:
        return {
            "user_input": user_input,
            "normalized_text": user_input,
            "language": "en",
            "confidence": 0.9,
            "intent": {"name": "statement"},
            "entities": [],
            "context": {},
        }


def test_adapter_binds_brain_llm_and_learning() -> None:
    brain = FakeBrain()
    semantic = SemanticUnderstanding()
    adapter = SemanticBrainAdapter(semantic=semantic)
    adapter.attach(brain)

    assert semantic.learning_boundary.llm_fallback is not None
    assert semantic.learning_boundary.learning is brain.learning_coordinator


def test_unknown_runtime_case_uses_real_brain_llm_and_intakes_learning() -> None:
    brain = FakeBrain()
    semantic = SemanticUnderstanding()
    adapter = SemanticBrainAdapter(semantic=semantic)
    adapter.attach(brain)

    result = brain._perceive("explain my new concept")
    learning = result["semantic_learning"]

    assert brain.llm.calls, "runtime semantic fallback did not call Brain LLM"
    assert brain.llm.calls[0]["user_input"] == "explain my new concept"
    assert learning["source"] == "llm_fallback"
    assert learning["fallback_used"] is True
    assert learning["candidate"]["status"] == "CANDIDATE"
    assert learning["intake"]["learning"]["success"] is True
    assert learning["intake"]["learning"]["accepted"] is False
    assert len(brain.learning_coordinator.calls) == 1
    experience, auto_accept = brain.learning_coordinator.calls[0]
    assert experience["event_type"] == "SEMANTIC_FALLBACK_INTERPRETATION"
    assert experience["semantic_candidate"]["source"] == "llm_fallback"
    assert auto_accept is False


def test_malformed_llm_output_is_rejected_before_learning() -> None:
    brain = FakeBrain()

    def malformed(**_kwargs: Any) -> str:
        return "not json"

    brain.llm.generate_response = malformed  # type: ignore[method-assign]
    semantic = SemanticUnderstanding()
    adapter = SemanticBrainAdapter(semantic=semantic)
    adapter.attach(brain)

    try:
        brain._perceive("unknown semantic input")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed LLM semantic output was accepted")
    assert brain.learning_coordinator.calls == []


def main() -> None:
    tests = [
        test_adapter_binds_brain_llm_and_learning,
        test_unknown_runtime_case_uses_real_brain_llm_and_intakes_learning,
        test_malformed_llm_output_is_rejected_before_learning,
    ]
    for test in tests:
        test()
    print("PASS: M3.1 adapter binds the existing Brain LLM and LearningCoordinator")
    print("PASS: unknown runtime semantic case uses real LLM fallback and enters learning intake")
    print("PASS: fallback candidate remains untrusted and is not auto-accepted")
    print("PASS: malformed LLM semantic output is rejected before learning")


if __name__ == "__main__":
    main()
