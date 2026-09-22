"""Local smoke and integration tests for the JARVIS contract pipeline.

Run from repository root:
    python3 -m core.contracts.test_contracts
"""

from __future__ import annotations

from . import CONTRACTS, ContractError, validate_input, validate_output


def test_registry_is_complete() -> None:
    expected_layers = {
        "perception", "semantic_understanding", "cognition", "cognitive_router",
        "brain", "experience", "learning", "memory", "self_evaluation", "evolution",
        "response",
    }
    actual_layers = {name.rsplit(".", 1)[0] for name in CONTRACTS}
    assert actual_layers == expected_layers, (actual_layers, expected_layers)
    for layer in expected_layers:
        assert f"{layer}.input" in CONTRACTS
        assert f"{layer}.output" in CONTRACTS


def test_representative_pipeline() -> None:
    perception = validate_output("perception", {
        "normalized_input": "How do I stay motivated in my journey?",
        "language": "en", "confidence": 0.99, "basic_intent": "guidance",
        "entities": [], "metadata": {},
    })
    semantic = validate_output("semantic_understanding", {
        "normalized_text": perception["normalized_input"],
        "intent": {"name": "motivation_guidance"}, "entities": [], "relations": [],
        "events": [], "references": [], "confidence": 0.91,
        "provenance": {"source": "native_semantic"}, "inferences": [], "unknowns": [],
    })
    cognition = validate_input("cognition", {
        "semantic": semantic, "memory": {}, "knowledge": {}, "goals": [],
        "state": {}, "capabilities": {}, "experience": [],
    })
    assert cognition["semantic"]["intent"]["name"] == "motivation_guidance"


def test_invalid_payload_is_rejected() -> None:
    try:
        validate_output("perception", {"normalized_input": "missing fields"})
    except ContractError:
        return
    raise AssertionError("invalid perception output was accepted")


def test_runtime_integration() -> None:
    from .test_pipeline_integration import (
        test_runtime_pipeline_contracts,
        test_semantic_layer_is_authoritative_and_not_legacy_double_parsed,
    )
    test_runtime_pipeline_contracts()
    test_semantic_layer_is_authoritative_and_not_legacy_double_parsed()


def test_p2_p3_runtime() -> None:
    from .test_p2_p3_runtime import (
        test_p2_router_consumes_cognition_contract,
        test_p3_normal_turn_reaches_async_learning_queue,
    )
    test_p2_router_consumes_cognition_contract()
    test_p3_normal_turn_reaches_async_learning_queue()


def test_full_runtime_contracts() -> None:
    from .test_full_runtime_contracts import test_full_runtime_contract_chain
    test_full_runtime_contract_chain()


def test_runtime_authority_and_budget() -> None:
    from .test_runtime_authority_budget import (
        test_router_emits_canonical_native_for_usable_capability,
        test_validator_records_real_runtime_events,
        test_llm_budget_is_hard_per_turn,
    )
    test_router_emits_canonical_native_for_usable_capability()
    test_validator_records_real_runtime_events()
    test_llm_budget_is_hard_per_turn()


def main() -> None:
    test_registry_is_complete()
    test_representative_pipeline()
    test_invalid_payload_is_rejected()
    test_runtime_integration()
    test_p2_p3_runtime()
    test_full_runtime_contracts()
    test_runtime_authority_and_budget()
    print(f"PASS: {len(CONTRACTS)} JARVIS input/output contracts validated")
    print("PASS: runtime perception -> semantic_understanding -> cognition integration validated")
    print("PASS: invalid payload rejection validated")
    print("PASS: Semantic Understanding is authoritative; legacy double-parsing is absent")
    print("PASS: P2 Cognition Router consumes canonical cognition.input")
    print("PASS: P3 normal think_and_respond reaches AsyncLearningQueue")
    print("PASS: full runtime Perception -> Memory contract chain validated")
    print("PASS: Router authority + LLM budget + live validation trace validated")


if __name__ == "__main__":
    main()
