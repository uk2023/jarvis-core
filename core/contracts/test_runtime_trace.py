"""Regression checks for the deep runtime trace surface."""

from __future__ import annotations

from types import SimpleNamespace

from deep_inspector import _runtime_contract_trace


def _fake_brain():
    contracts = {
        "perception.output": {"normalized_input": "hello Jarvis", "language": "en", "confidence": 0.9},
        "semantic_understanding.input": {"perception": {}, "user_input": "hello Jarvis"},
        "semantic_understanding.output": {"normalized_text": "hello Jarvis", "intent": {}, "entities": [], "relations": [], "events": [], "references": [], "confidence": 0.9, "provenance": {"source": "native"}},
        "cognition.input": {"semantic": {}, "memory": {}, "knowledge": {}, "goals": [], "state": {}, "capabilities": {}, "experience": []},
        "cognition.output": {"cognitive_context": {}, "confidence": 0.9},
        "cognitive_router.input": {"cognitive_context": {}},
        "cognitive_router.output": {"route": "known", "confidence": 0.9, "fallback_allowed": False, "evidence": []},
        "brain.input": {"cognitive_context": {}, "routing_decision": {}},
        "brain.output": {"decision": {}, "action": None, "response": "Namaste"},
        "experience.input": {"event_type": "USER_CHAT", "context": {}, "action": {}, "outcome": {}},
        "experience.output": {"evaluation": {}, "experience": {}},
        "learning.input": {"experience": {}},
        "learning.output": {"learning_result": {}, "knowledge_updates": []},
        "self_evaluation.input": {"experience": {}},
        "self_evaluation.output": {"evaluation": {}},
        "evolution.input": {"evolution_proposal": {}},
        "evolution.output": {"proposal_id": "p1", "target": "x", "revision_id": "r1", "revision": 1, "profile": {}, "next_cycle_ready": True, "change_record": {}},
        "memory.evolution.input": {"evolution_output": {}},
        "memory.evolution.output": {"memory_context": {}},
    }
    return SimpleNamespace(
        last_contracts=contracts,
        last_router_output=contracts["cognitive_router.output"],
        last_perception={"semantic_understanding": contracts["semantic_understanding.output"]},
        last_brain_decision={"mode": "known", "status": "completed"},
        last_experience_input=contracts["experience.input"],
        last_experience_output=contracts["experience.output"],
        last_learning_input=contracts["learning.input"],
        last_learning_output=contracts["learning.output"],
        last_self_evaluation_input=contracts["self_evaluation.input"],
        last_self_evaluation_output=contracts["self_evaluation.output"],
        last_memory_input=contracts["memory.evolution.input"],
        last_memory_output=contracts["memory.evolution.output"],
    )


def test_trace_uses_live_contract_records():
    brain = _fake_brain()
    trace = _runtime_contract_trace(brain, {"source": "cli"}, "Namaste")
    assert len(trace["contracts"]) == 20
    assert trace["semantic_provenance"]["source"] == "native"
    assert trace["route_consistency"]["status"] == "PASS"


def test_trace_flags_forbidden_route_execution_mismatch():
    brain = _fake_brain()
    brain.last_brain_decision = {"mode": "llm", "status": "completed"}
    trace = _runtime_contract_trace(brain, {"source": "cli"}, "fallback")
    assert trace["route_consistency"]["status"] == "FAIL"


def main():
    test_trace_uses_live_contract_records()
    test_trace_flags_forbidden_route_execution_mismatch()
    print("PASS: deep runtime trace consumes live contract records")
    print("PASS: semantic provenance is exposed without a second interpretation path")
    print("PASS: forbidden Router -> Brain execution mismatch is detected")
    print("PASS: runtime trace regression checks completed")


if __name__ == "__main__":
    main()
