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
    def __init__(self):
        self.calls = []

    def generate(self, system_prompt, user_input, max_tokens=512, temperature=0.7):
        self.calls.append((system_prompt, user_input))
        return "Synthesized: pong from native capability."


class HybridRouterBrainSmokeTests(unittest.TestCase):
    def test_router_accepts_explicit_hybrid_contract(self):
        router = CognitiveRouter()
        decision = router.decide(
            user_input="check status",
            perception={
                "user_input": "check status",
                "confidence": 0.96,
                "intent": {"skill": "ping", "execution_mode": "hybrid"},
                "source": "test",
            },
            skills={"ping": lambda **kwargs: "pong"},
        )
        self.assertEqual(decision.mode, "hybrid")
        self.assertTrue(decision.llm_required)

    def test_hybrid_executes_native_then_llm_synthesizes(self):
        registry = SkillRegistry()
        registry.register("ping", lambda **kwargs: "pong")
        perception = FakePerception({
            "confidence": 0.96,
            "intent": {"skill": "ping", "execution_mode": "hybrid"},
            "source": "test",
        })
        llm = FakeLLM()
        brain = Brain(
            perception_engine=perception,
            skill_registry=registry,
            cognitive_router=CognitiveRouter(),
            llm_bridge=None,
        )
        brain.llm = llm
        brain._enqueue_learning = lambda **kwargs: None

        response = brain.think_and_respond("check status", source="test")

        self.assertEqual(response, "Synthesized: pong from native capability.")
        self.assertEqual(brain.last_cognitive_decision["mode"], "hybrid")
        self.assertEqual(brain.last_brain_decision["mode"], "hybrid")
        self.assertEqual(brain.last_brain_decision["native_skill"], "ping")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("Native result: pong", llm.calls[0][1])


if __name__ == "__main__":
    unittest.main()
