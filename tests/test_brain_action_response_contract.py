import unittest
from types import SimpleNamespace

from core.orchestration.cognitive_router import CognitiveRouter
from core.orchestration.brain import Brain
from core.skills.skill_registry import SkillRegistry


class FakePerception:
    def __init__(self, payload):
        self.payload = payload
        self.providers = []

    def perceive(self, user_input, context=None):
        return SimpleNamespace(as_dict=lambda: dict(self.payload, user_input=user_input))

    def add_provider(self, provider):
        self.providers.append(provider)


class FakeLLM:
    def generate(self, system_prompt, user_input, max_tokens=512, temperature=0.7):
        return "LLM response"


class BrainActionResponseContractTests(unittest.TestCase):
    def _brain(self, mode="tool"):
        registry = SkillRegistry()
        registry.register("ping", lambda **kwargs: "pong")
        perception = FakePerception({
            "confidence": 0.98,
            "intent": {"skill": "ping", "execution_mode": mode},
            "source": "test",
        })
        brain = Brain(
            perception_engine=perception,
            skill_registry=registry,
            cognitive_router=CognitiveRouter(),
            llm_bridge=FakeLLM(),
        )
        brain._enqueue_learning = lambda **kwargs: None
        return brain

    def test_native_brain_decision_is_committed_to_action_response(self):
        brain = self._brain("native")
        response = brain.think_and_respond("ping", source="test")

        self.assertEqual(response, "pong")
        self.assertEqual(brain.last_brain_decision["mode"], "native")
        self.assertEqual(brain.last_action_response["mode"], "native")
        self.assertEqual(brain.last_action_response["status"], "completed")
        self.assertEqual(brain.last_action_response["response"], "pong")
        self.assertEqual(brain.last_action_response["action"]["skill"], "ping")
        self.assertEqual(brain.last_turn_trace["action_response"]["response"], "pong")

    def test_hybrid_brain_decision_is_committed_to_action_response(self):
        brain = self._brain("hybrid")
        response = brain.think_and_respond("ping", source="test")

        self.assertEqual(response, "LLM response")
        self.assertEqual(brain.last_brain_decision["mode"], "hybrid")
        self.assertEqual(brain.last_action_response["mode"], "hybrid")
        self.assertEqual(brain.last_action_response["status"], "completed")
        self.assertEqual(brain.last_action_response["action"]["skill"], "ping")
        self.assertEqual(brain.last_turn_trace["action_response"]["mode"], "hybrid")


if __name__ == "__main__":
    unittest.main()
