import unittest

from core.orchestration.cognitive_router import CognitiveRouter


class CognitiveRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = CognitiveRouter()

    def test_empty_evidence_requires_llm(self):
        decision = self.router.decide(
            user_input="hello",
            context={},
            skills={},
            goals=[],
        )
        self.assertEqual(decision.mode, "llm")
        self.assertTrue(decision.llm_required)

    def test_structured_intent_with_skill_uses_native_route(self):
        decision = self.router.decide(
            user_input="run the registered capability",
            context={},
            skills={"example": object()},
            explicit_intent={"skill": "example"},
        )
        self.assertEqual(decision.mode, "tool")
        self.assertFalse(decision.llm_required)
        self.assertGreaterEqual(decision.confidence, 0.90)

    def test_structured_intent_with_memory_uses_known_route(self):
        decision = self.router.decide(
            user_input="what do you remember",
            context={"recent_experiences": [{"id": 1}]},
            skills={},
            explicit_intent={"intent": "recall"},
        )
        self.assertEqual(decision.mode, "known")
        self.assertFalse(decision.llm_required)

    def test_confirmation_is_not_sent_to_llm(self):
        decision = self.router.decide(
            user_input="perform the pending action",
            context={},
            skills={},
            explicit_intent={"requires_confirmation": True},
        )
        self.assertEqual(decision.mode, "clarify")
        self.assertFalse(decision.llm_required)


if __name__ == "__main__":
    unittest.main()
