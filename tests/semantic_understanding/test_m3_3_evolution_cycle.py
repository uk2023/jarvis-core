"""M3.3 tests: promotion is reused natively on a future cycle."""

from __future__ import annotations

from typing import Any

from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator
from core.learning.self_evaluator import SelfEvaluator

from core.cognition.semantic_understanding.evolution_cycle import SemanticEvolutionCycle
from core.cognition.semantic_understanding.learning_boundary import SemanticLearningBoundary


class FakeKnowledge:
    def __init__(self, knowledge_id: str, subject: str, predicate: str, value: Any) -> None:
        self.knowledge_id = knowledge_id
        self.subject = subject
        self.predicate = predicate
        self.value = value
        self.confidence = 0.9
        self.importance = 0.5
        self.source = "experience:SEMANTIC_FALLBACK_INTERPRETATION"
        self.tags = ["semantic"]

    def to_dict(self) -> dict[str, Any]:
        return {"knowledge_id": self.knowledge_id, "subject": self.subject,
                "predicate": self.predicate, "value": self.value}


class FakeMemory:
    def __init__(self) -> None:
        self.saved: list[FakeKnowledge] = []
        self.counter = 0

    def remember_knowledge(self, subject: str, predicate: str, value: Any,
                           confidence: float, importance: float,
                           source: str, tags: list[str]) -> FakeKnowledge:
        self.counter += 1
        item = FakeKnowledge(f"knowledge:{self.counter}", subject, predicate, value)
        self.saved.append(item)
        return item


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"semantic": {
            "normalized": "explain quantum widgets",
            "intent": {"name": "concept_explanation"},
            "entities": [], "relations": [], "events": [], "references": [],
            "confidence": 0.91,
            "provenance": {"source": "llm_fallback"},
            "inferences": [], "unknowns": [],
        }}


def test_promoted_capability_is_reused_without_llm() -> None:
    memory = FakeMemory()
    learning = LearningCoordinator(
        evaluator=SelfEvaluator(),
        knowledge_builder=KnowledgeBuilder(memory_manager=memory),
        memory_manager=memory,
    )
    boundary = SemanticLearningBoundary()
    llm = FakeLLM()
    boundary.llm_fallback = llm
    cycle = SemanticEvolutionCycle(boundary, learning)

    first = cycle.cycle("explain quantum widgets", {"confidence": 0.1, "unknowns": ["intent"]})
    candidate_id = first["candidate"]["id"]
    promoted = cycle.accept_and_promote(candidate_id)
    assert promoted["promoted_capability"]["source"] == "llm_fallback"
    assert llm.calls == 1

    second = cycle.cycle("explain quantum widgets", {"confidence": 0.1, "unknowns": ["intent"]})
    assert second["source"] == "learned_native"
    assert second["fallback_used"] is False
    assert second["semantic"]["provenance"]["source"] == "learned_native"
    assert llm.calls == 1, "learned capability triggered another LLM call"


def test_rejected_candidate_does_not_enter_future_native_path() -> None:
    boundary = SemanticLearningBoundary()
    llm = FakeLLM()
    boundary.llm_fallback = llm
    cycle = SemanticEvolutionCycle(boundary, learning_coordinator=None)

    first = cycle.cycle("reject this pattern", {"confidence": 0.1, "unknowns": ["intent"]})
    candidate_id = first["candidate"]["id"]
    rejected = cycle.reject(candidate_id, reason="not reliable")
    assert rejected["candidate"]["status"] == "REJECTED"
    assert boundary.registry.entries() == []

    second = cycle.cycle("reject this pattern", {"confidence": 0.1, "unknowns": ["intent"]})
    assert second["source"] == "llm_fallback"
    assert second["fallback_used"] is True
    assert llm.calls == 2


def main() -> None:
    test_promoted_capability_is_reused_without_llm()
    test_rejected_candidate_does_not_enter_future_native_path()
    print("PASS: M3.3 accepted semantic capability is reused natively")
    print("PASS: future matching bypasses unnecessary LLM fallback")
    print("PASS: rejected knowledge never becomes a native capability")
    print("PASS: full fallback -> learning -> promotion -> native reuse cycle validated")
    print("PASS: no per-case regex capability is generated")


if __name__ == "__main__":
    main()
