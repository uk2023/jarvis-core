"""Runtime regression checks for native-first Router authority and LLM budget."""

from __future__ import annotations

from typing import Any

from ..contracts.validator import begin_validation_trace, get_validation_trace, validate_input
from ..orchestration.cognitive_router import CognitiveRouter
from ..orchestration.llm_bridge import CognitiveBudgetExceeded, CognitiveBudgeter, HybridLLMBridge


class _FakeLocal:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system_prompt: str, user_input: str, max_tokens: int = 512, temperature: float = 0.7) -> str:
        self.calls += 1
        return f"reply-{self.calls}"


def _cognition(mode: str = "", skill: str | None = None) -> dict[str, Any]:
    intent = {"name": "statement", "confidence": 0.9}
    if mode:
        intent["execution_mode"] = mode
    if skill:
        intent["skill"] = skill
    return {
        "semantic": {
            "normalized_text": "hello Jarvis",
            "intent": intent,
            "entities": [], "relations": [], "events": [], "references": [],
            "confidence": 0.9, "provenance": {"source": "native"},
            "inferences": [], "unknowns": [],
        },
        "memory": {"recent_experiences": [{} for _ in range(3)]},
        "knowledge": {"relevant_knowledge": []},
        "goals": [], "state": {}, "capabilities": {"skills": {skill: {}} if skill else {}}, "experience": [],
    }


def test_router_emits_canonical_native_for_usable_capability() -> None:
    router = CognitiveRouter(minimum_confidence=0.6)
    decision = router.decide(user_input="hello Jarvis", cognition_input=_cognition(mode="native", skill="clock"))
    assert decision.mode == "native"
    assert decision.llm_required is False


def test_legacy_known_with_capability_does_not_force_llm() -> None:
    router = CognitiveRouter(minimum_confidence=0.6)
    decision = router.decide(user_input="hello Jarvis", cognition_input=_cognition(mode="known", skill="clock"))
    assert decision.mode == "native"
    assert decision.llm_required is False


def test_native_without_capability_is_genuine_llm_fallback() -> None:
    router = CognitiveRouter(minimum_confidence=0.6)
    decision = router.decide(user_input="hello Jarvis", cognition_input=_cognition(mode="native"))
    assert decision.mode == "llm"
    assert decision.llm_required is True


def test_validator_records_real_runtime_events() -> None:
    begin_validation_trace()
    validate_input("cognition", _cognition())
    events = get_validation_trace()
    assert events
    assert events[-1]["schema"] == "cognition.input"
    assert events[-1]["status"] == "PASS"


def test_llm_budget_is_hard_per_turn() -> None:
    bridge = HybridLLMBridge(force_mode="offline")
    fake = _FakeLocal()
    bridge._get_local = lambda: fake
    # Pin the budget explicitly rather than relying on whatever
    # config/cognition.json currently says: this test asserts a
    # *mechanism* (two requests that together exceed the turn's token
    # budget -> the second one raises), not any particular numeric
    # config value. Freeze the policy loader so begin_turn_budget()
    # doesn't reload config/cognition.json over this test's fixture.
    bridge._load_budget_policy = lambda: None
    bridge._budget_max_calls = 5
    bridge._budget_max_output_tokens = 768
    bridge.begin_turn_budget()
    assert bridge.generate_response("system", "one", max_tokens=512) == "reply-1"
    try:
        bridge.generate_response("system", "two", max_tokens=512)
    except CognitiveBudgetExceeded:
        pass
    else:
        raise AssertionError("second 512-token request must exceed the 768-token turn budget")
    assert fake.calls == 1


def test_context_budget_bounds_large_payload() -> None:
    budgeter = CognitiveBudgeter(max_context_tokens=4096)
    system = "system evidence " * 2000
    user = "retrieved memory knowledge " * 20000
    bounded_system, bounded_user = budgeter.optimize_payload(system, user, max_tokens=768)
    assert budgeter.estimate_tokens(bounded_system) + budgeter.estimate_tokens(bounded_user) <= 4096 - 768 - 128
    assert len(bounded_user) < len(user)


def main() -> None:
    test_router_emits_canonical_native_for_usable_capability()
    test_legacy_known_with_capability_does_not_force_llm()
    test_native_without_capability_is_genuine_llm_fallback()
    test_validator_records_real_runtime_events()
    test_llm_budget_is_hard_per_turn()
    test_context_budget_bounds_large_payload()
    print("PASS: canonical NATIVE route is executable")
    print("PASS: legacy known/native labels do not force LLM when native capability exists")
    print("PASS: LLM remains genuine fallback when native capability is unavailable")
    print("PASS: central validator records real runtime events")
    print("PASS: LLM call/output budget is enforced per turn")
    print("PASS: LLM system+user context is bounded within 4096-token budget")


if __name__ == "__main__":
    main()
