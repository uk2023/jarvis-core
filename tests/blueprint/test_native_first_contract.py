import unittest

from core.orchestration.cognitive_router import CognitiveRouter
from core.orchestration.llm_bridge import CognitiveBudgeter, HybridLLMBridge
from core.orchestration.blueprint_brain import BlueprintBrain
from core.learning.controlled_evolution import ControlledEvolutionEngine


class NativeFirstContractTests(unittest.TestCase):
    def test_router_canonicalizes_legacy_known_to_native_when_capability_exists(self):
        router = CognitiveRouter(minimum_confidence=0.5)
        decision = router.decide(
            user_input="run safe",
            cognition_input={
                "semantic": {"normalized_text": "run safe", "confidence": 0.99, "intent": {"route": "known", "skill": "safe"}},
                "memory": {}, "knowledge": {}, "goals": [], "state": {},
                "capabilities": {"skills": {"safe": object()}}, "experience": [],
            },
        )
        self.assertEqual(decision.mode, "native")
        self.assertFalse(decision.llm_required)

    def test_blueprint_brain_exposes_only_executable_canonical_routes(self):
        self.assertEqual(BlueprintBrain._SUPPORTED_ROUTES, frozenset({"goal", "native", "hybrid", "llm", "clarify"}))

    def test_bridge_generate_is_budgeted(self):
        bridge = HybridLLMBridge(force_mode="offline")
        bridge.begin_turn_budget()
        self.assertEqual(bridge.generate.__name__, "generate")
        system, user = bridge._context_budgeter.optimize_payload("system " * 1000, "user " * 10000, max_tokens=512)
        self.assertLessEqual(CognitiveBudgeter.estimate_tokens(system) + CognitiveBudgeter.estimate_tokens(user), 4096 - 512 - bridge._context_budgeter.safety_tokens)

    def test_controlled_evolution_supplies_contract_revision(self):
        evolution = ControlledEvolutionEngine()
        evolution.register_adapter("routing", lambda proposal: {"changed": True})
        proposal = evolution.propose({"score": 0.2, "errors": ["bad route"], "strengths": []}, "routing")
        evolution.validate(proposal["id"]); evolution.approve(proposal["id"])
        applied = evolution.apply(proposal["id"])
        self.assertIsInstance(applied["revision"], (int, float))
        self.assertTrue(applied["revision_id"])
        self.assertTrue(applied["next_cycle_ready"])


if __name__ == "__main__":
    unittest.main()
