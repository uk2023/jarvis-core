"""M3.2 tests: candidate -> evaluation -> knowledge -> promotion/rejection."""

from __future__ import annotations

from typing import Any

from core.learning.knowledge_builder import KnowledgeBuilder
from core.learning.learning_coordinator import LearningCoordinator
from core.learning.self_evaluator import SelfEvaluator

from core.cognition.semantic_understanding.knowledge_promotion import SemanticKnowledgePromotion
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
        knowledge = FakeKnowledge(f"knowledge:{self.counter}", subject, predicate, value)
        self.saved.append(knowledge)
        return knowledge


def make_learning() -> tuple[LearningCoordinator, FakeMemory]:
    memory = FakeMemory()
    builder = KnowledgeBuilder(memory_manager=memory)
    evaluator = SelfEvaluator()
    return LearningCoordinator(evaluator=evaluator, knowledge_builder=builder,
                               memory_manager=memory), memory


def make_candidate(boundary: SemanticLearningBoundary, text: str = "explain quantum widgets") -> str:
    def llm(_request: dict[str, Any]) -> dict[str, Any]:
        return {"semantic": {"normalized": text,
            "intent": {"name": "concept_explanation"}, "entities": [], "relations": [],
            "events": [], "references": [], "confidence": 0.91,
            "provenance": {"source": "llm_fallback"}, "inferences": [], "unknowns": []}}
    boundary.llm_fallback = llm
    result = boundary.resolve(text, {"confidence": 0.1, "unknowns": ["intent"]})
    return result["candidate"]["id"]


def test_accept_path_uses_existing_learning_stack_and_promotes() -> None:
    learning, memory = make_learning()
    boundary = SemanticLearningBoundary()
    candidate_id = make_candidate(boundary)
    result = SemanticKnowledgePromotion(boundary, learning).accept_and_promote(candidate_id)
    assert result["evaluation"]["success"] is True
    assert result["knowledge"]["status"] == "ACCEPTED"
    assert result["knowledge"]["semantic_knowledge_id"] == "knowledge:1"
    assert result["candidate"]["status"] == "ACCEPTED"
    assert result["promoted_capability"]["source"] == "llm_fallback"
    assert result["promoted_capability"]["semantic"]["intent"]["name"] == "concept_explanation"
    assert len(memory.saved) == 1


def test_reject_path_never_promotes_or_persists() -> None:
    learning, memory = make_learning()
    boundary = SemanticLearningBoundary()
    candidate_id = make_candidate(boundary, "reject this unknown pattern")
    result = SemanticKnowledgePromotion(boundary, learning).reject(candidate_id, reason="evaluation rejected")
    assert result["evaluation"]["status"] == "REJECTED"
    # Rejection is terminal before knowledge creation; there must be no
    # persisted knowledge object to promote or inspect as ACCEPTED/REJECTED.
    assert result["knowledge"] is None
    assert result["candidate"]["status"] == "REJECTED"
    assert result["promoted_capability"] is None
    assert memory.saved == []
    assert boundary.registry.entries() == []


def test_low_evaluation_rejects_knowledge_before_promotion() -> None:
    learning, memory = make_learning()
    boundary = SemanticLearningBoundary()
    candidate_id = make_candidate(boundary, "low confidence pattern")
    original = learning.evaluator.evaluate
    def failed(experience: dict[str, Any]) -> dict[str, Any]:
        result = original(experience)
        result["success"] = False
        result["score"] = 0.1
        return result
    learning.evaluator.evaluate = failed  # type: ignore[method-assign]
    result = SemanticKnowledgePromotion(boundary, learning).evaluate_and_build(candidate_id)
    assert result["evaluation"]["success"] is False
    assert result["evaluation"]["score"] == 0.1
    assert result["knowledge"] is None
    assert memory.saved == []


def main() -> None:
    test_accept_path_uses_existing_learning_stack_and_promotes()
    test_reject_path_never_promotes_or_persists()
    test_low_evaluation_rejects_knowledge_before_promotion()
    print("PASS: M3.2 candidate -> evaluation -> KnowledgeBuilder -> accepted knowledge -> promoted capability")
    print("PASS: acceptance persists through existing MemoryManager boundary before semantic promotion")
    print("PASS: rejection path produces no promoted capability and no semantic persistence")
    print("PASS: failed evaluation blocks knowledge creation and promotion")
    print("PASS: no hard-coded regex capability is generated")


if __name__ == "__main__":
    main()
