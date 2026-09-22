"""End-to-end runtime contract test for the actual BlueprintBrain path."""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from ..orchestration.blueprint_brain import BlueprintBrain
from ..orchestration.cognitive_router import CognitiveDecision
from ..orchestration.perception import PerceptionEngine, PerceptionResult
from ..cognition.semantic_understanding import SemanticUnderstanding


class StubPerceptionProvider:
    name = "contract_runtime_stub"

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> PerceptionResult:
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "statement", "confidence": 0.95, "source": self.name},
            entities={}, language="en", confidence=0.95, uncertainty=0.05,
            source=self.name, reason="contract runtime test",
        )


class CapturingRouter:
    def __init__(self) -> None:
        self.last_input = None

    def decide(self, *, cognition_input=None, **kwargs):
        self.last_input = cognition_input
        confidence = float((cognition_input.get("semantic") or {}).get("confidence", 0.0))
        return CognitiveDecision("llm", confidence, "contract test", {"source": "test"}, True)


class StubLLM:
    def generate(self, system_prompt: str, user_input: str) -> str:
        return "contract runtime response"


class StubExperience:
    def process(self, **kwargs):
        return {"episode_id": "contract-episode", "experience": kwargs}


class StubLearning:
    def __init__(self) -> None:
        self.calls = 0
        self.last_result = None

    def learn(self, *, experience, auto_accept=True):
        self.calls += 1
        self.last_result = {
            "success": True,
            "experience": experience,
            "evaluation": {"success": True},
            "knowledge": None,
            "accepted": False,
        }
        return self.last_result


def test_full_runtime_contract_chain() -> None:
    router = CapturingRouter()
    learning = StubLearning()
    brain = BlueprintBrain(
        perception_engine=PerceptionEngine(providers=[StubPerceptionProvider()]),
        cognitive_router=router,
        llm_bridge=StubLLM(),
        experience_engine=StubExperience(),
        learning_coordinator=learning,
        semantic_understanding=SemanticUnderstanding(semantic_memory=None),
    )
    brain.start()
    try:
        response = brain.think_and_respond("I like Python")
        assert response == "contract runtime response"
        deadline = time.time() + 2.0
        while time.time() < deadline and brain._learning_queue.processed < 1:
            time.sleep(0.01)

        contracts = brain.last_contracts
        required = {
            "perception.input", "perception.output",
            "semantic_understanding.input", "semantic_understanding.output",
            "cognition.input", "cognition.output",
            "cognitive_router.input", "cognitive_router.output",
            "brain.input", "brain.output",
            "experience.input", "experience.output",
            "learning.input", "learning.output",
            "self_evaluation.input", "self_evaluation.output",
            "memory.input", "memory.output",
        }
        assert required <= set(contracts)
        assert router.last_input == contracts["cognitive_router.input"]["cognitive_context"]
        assert contracts["brain.input"]["cognitive_context"] == contracts["cognition.input"]
        assert contracts["brain.output"]["response"] == response
        assert contracts["experience.input"]["outcome"]
        assert contracts["learning.input"]["experience"] == contracts["experience.output"]["experience"]
        assert contracts["self_evaluation.output"]["evaluation"]["success"] is True
        assert contracts["memory.input"]["learning_result"] == contracts["learning.output"]["learning_result"]
        assert brain._learning_queue.failed == 0
        assert learning.calls == 1
    finally:
        brain.stop()


def main() -> None:
    test_full_runtime_contract_chain()
    print("PASS: direct BlueprintBrain runtime contract chain")
    print("PASS: Perception -> Semantic Understanding -> Cognition -> Router")
    print("PASS: Brain -> Experience -> Learning -> SelfEvaluation -> Memory")
    print("PASS: no ContractEnforcedBlueprintBrain proxy is used")
    print("PASS: full runtime contract chain completed")


if __name__ == "__main__":
    main()
