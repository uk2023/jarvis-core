"""Milestone 3 tests for self-evolving Semantic Understanding."""

from __future__ import annotations

from core.cognition.semantic_understanding.learning_boundary import LearnedSemanticRegistry, SemanticLearningBoundary


def test_native_path_does_not_call_llm() -> None:
    calls = []

    def llm(request):
        calls.append(request)
        return {"intent": {"name": "should_not_run"}, "confidence": 0.99}

    boundary = SemanticLearningBoundary(llm_fallback=llm)
    result = boundary.resolve("hello", {"intent": {"name": "greeting"}, "confidence": 0.95, "unknowns": []})
    assert result["source"] == "native"
    assert result["fallback_used"] is False
    assert calls == []


def test_unknown_uses_llm_as_candidate_source() -> None:
    def llm(request):
        assert request["text"] == "what is my new concept"
        return {"semantic": {
            "normalized": "what is my new concept",
            "intent": {"name": "concept_explanation"},
            "entities": [{"text": "new concept", "type": "topic"}],
            "relations": [], "events": [], "references": [], "confidence": 0.88,
            "provenance": {"source": "llm_fallback"}, "inferences": [], "unknowns": [],
        }}

    boundary = SemanticLearningBoundary(llm_fallback=llm)
    result = boundary.resolve("what is my new concept", {"intent": {"name": "statement"}, "confidence": 0.30, "unknowns": ["intent"]})
    assert result["source"] == "llm_fallback"
    assert result["fallback_used"] is True
    assert result["candidate"]["status"] == "CANDIDATE"


def test_candidate_requires_explicit_acceptance_before_promotion() -> None:
    def llm(_request):
        return {"semantic": {"intent": {"name": "concept_explanation"}, "confidence": 0.91}}

    boundary = SemanticLearningBoundary(llm_fallback=llm)
    result = boundary.resolve("explain quantum widgets please", {"confidence": 0.20, "unknowns": ["intent"]})
    candidate_id = result["candidate"]["id"]
    try:
        boundary.promote(candidate_id)
    except ValueError:
        pass
    else:
        raise AssertionError("unaccepted semantic candidate was promoted")

    accepted = boundary.accept_candidate(candidate_id)
    assert accepted["status"] == "ACCEPTED"
    promoted = boundary.promote(candidate_id)
    assert promoted["source"] == "llm_fallback"


def test_accepted_candidate_becomes_data_driven_native_capability() -> None:
    def llm(_request):
        return {"semantic": {
            "normalized": "explain quantum widgets please",
            "intent": {"name": "concept_explanation"}, "entities": [], "relations": [],
            "events": [], "references": [], "confidence": 0.91,
            "provenance": {"source": "llm_fallback"}, "inferences": [], "unknowns": [],
        }}

    boundary = SemanticLearningBoundary(llm_fallback=llm, native_confidence_threshold=0.72)
    result = boundary.resolve("explain quantum widgets please", {"confidence": 0.20, "unknowns": ["intent"]})
    candidate_id = result["candidate"]["id"]
    boundary.accept_candidate(candidate_id)
    boundary.promote(candidate_id)

    learned = boundary.resolve("please explain quantum widgets", {"confidence": 0.10, "unknowns": ["intent"]})
    assert learned["source"] == "learned_native"
    assert learned["fallback_used"] is False
    assert learned["semantic"]["intent"]["name"] == "concept_explanation"


def test_learning_coordinator_receives_candidate_as_experience() -> None:
    class FakeLearning:
        def __init__(self):
            self.calls = []

        def learn(self, experience, auto_accept=False):
            self.calls.append((experience, auto_accept))
            return {"success": True, "accepted": False}

    def llm(_request):
        return {"semantic": {"intent": {"name": "new_intent"}, "confidence": 0.84}}

    learning = FakeLearning()
    boundary = SemanticLearningBoundary(llm_fallback=llm, learning_coordinator=learning)
    result = boundary.resolve("a new semantic pattern", {"confidence": 0.1, "unknowns": ["intent"]})
    learned = boundary.learn(result["candidate"]["id"])
    assert learned["learning"]["success"] is True
    experience, auto_accept = learning.calls[0]
    assert experience["event_type"] == "SEMANTIC_FALLBACK_INTERPRETATION"
    assert experience["semantic_candidate"]["source"] == "llm_fallback"
    assert auto_accept is False


def test_registry_similarity_is_data_driven() -> None:
    registry = LearnedSemanticRegistry(minimum_similarity=0.50)
    candidate = {
        "id": "semantic:test", "input_text": "explain quantum widgets please",
        "semantic": {"intent": {"name": "concept_explanation"}, "confidence": 0.9},
        "source": "llm_fallback", "confidence": 0.9, "status": "ACCEPTED",
    }
    registry.promote(candidate)
    match = registry.match("please explain quantum widgets")
    assert match is not None and match["similarity"] >= 0.50


def main() -> None:
    tests = [
        test_native_path_does_not_call_llm,
        test_unknown_uses_llm_as_candidate_source,
        test_candidate_requires_explicit_acceptance_before_promotion,
        test_accepted_candidate_becomes_data_driven_native_capability,
        test_learning_coordinator_receives_candidate_as_experience,
        test_registry_similarity_is_data_driven,
    ]
    for test in tests:
        test()
    print("PASS: native semantic path avoids unnecessary LLM fallback")
    print("PASS: unknown semantic pattern reaches LLM fallback as a candidate")
    print("PASS: fallback result remains untrusted until explicit acceptance")
    print("PASS: accepted semantic knowledge becomes data-driven native capability")
    print("PASS: existing LearningCoordinator boundary receives semantic experience")
    print("PASS: learned matching uses token similarity; no per-case regex is generated")


if __name__ == "__main__":
    main()
