"""Runtime regression tests for the Cognition boundary and learning queue.

Run from repository root:
    python3 -m core.contracts.test_p2_p3_runtime
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from ..cognition.semantic_understanding import SemanticUnderstanding
from ..orchestration.blueprint_brain import BlueprintBrain
from ..orchestration.cognitive_router import CognitiveDecision
from ..orchestration.perception import PerceptionEngine, PerceptionResult


class StubPerceptionProvider:
    name = "runtime_stub"

    def perceive(self, user_input: str, context: Optional[Mapping[str, Any]] = None) -> PerceptionResult:
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "statement", "confidence": 0.95, "source": self.name},
            entities=[{"text": "Python", "type": "topic", "confidence": 0.9}],
            language="en",
            confidence=0.95,
            uncertainty=0.05,
            source=self.name,
            reason="deterministic runtime provider",
        )


class CapturingRouter:
    def __init__(self) -> None:
        self.cognition_input = None

    def decide(self, *, cognition_input=None, **kwargs):
        self.cognition_input = cognition_input
        semantic = cognition_input["semantic"]
        return CognitiveDecision("llm", float(semantic.get("confidence", 0.0)), "runtime test route", {"source": "test"}, True)


class StubLLM:
    def generate(self, system_prompt: str, user_input: str) -> str:
        return "runtime response"


class StubExperience:
    def __init__(self) -> None:
        self.calls = 0

    def process(self, **kwargs):
        self.calls += 1
        return {"episode_id": f"episode-{self.calls}", "experience": kwargs}


class StubLearning:
    def __init__(self) -> None:
        self.calls = 0

    def learn(self, *, experience, auto_accept=True):
        self.calls += 1
        return {"success": True, "experience": experience, "evaluation": {"success": True}, "knowledge": None, "accepted": False}


def test_p2_router_consumes_cognition_contract() -> None:
    router = CapturingRouter()
    perception = PerceptionEngine(providers=[StubPerceptionProvider()])
    semantic = SemanticUnderstanding(semantic_memory=None)
    brain = BlueprintBrain(
        perception_engine=perception,
        cognitive_router=router,
        semantic_understanding=semantic,
    )

    perceived = brain._perceive("I like Python")
    brain._route_cognition("I like Python", perceived)

    assert router.cognition_input is not None
    assert "semantic" in router.cognition_input
    assert router.cognition_input["semantic"] == brain.last_contracts["cognition.input"]["semantic"]
    assert "memory" in router.cognition_input
    assert "perception_source" not in router.cognition_input


def test_p3_normal_turn_reaches_async_learning_queue() -> None:
    router = CapturingRouter()
    perception = PerceptionEngine(providers=[StubPerceptionProvider()])
    experience = StubExperience()
    learning = StubLearning()
    brain = BlueprintBrain(
        perception_engine=perception,
        cognitive_router=router,
        llm_bridge=StubLLM(),
        experience_engine=experience,
        learning_coordinator=learning,
        semantic_understanding=SemanticUnderstanding(semantic_memory=None),
    )

    brain.start()
    try:
        response = brain.think_and_respond("I like Python")
        assert response == "runtime response"
        deadline = time.time() + 2.0
        while time.time() < deadline and learning.calls < 1:
            time.sleep(0.01)
        assert brain._learning_queue.is_alive()
        assert brain._learning_queue.processed == 1
        assert brain._learning_queue.failed == 0
        assert experience.calls == 1
        assert learning.calls == 1
    finally:
        brain.stop()


def main() -> None:
    test_p2_router_consumes_cognition_contract()
    test_p3_normal_turn_reaches_async_learning_queue()
    print("PASS: P2 Cognitive Router consumes canonical cognition.input")
    print("PASS: P3 normal think_and_respond turn reaches AsyncLearningQueue")
    print("PASS: P2/P3 runtime regression checks completed")


if __name__ == "__main__":
    main()
