import unittest

from core.orchestration.brain import Brain
from core.orchestration.perception import PerceptionEngine, PerceptionResult
from core.orchestration.cognitive_router import CognitiveRouter
from core.skills.skill_registry import SkillRegistry


class FakePerceptionProvider:
    name = "fake"

    def __init__(self, intent=None, confidence=0.95):
        self.intent = intent or {"name": "conversation", "confidence": confidence}
        self.confidence = confidence
        self.calls = []

    def perceive(self, user_input, context=None):
        self.calls.append((user_input, context))
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent=self.intent,
            language="en",
            confidence=self.confidence,
            uncertainty=1.0 - self.confidence,
            source=self.name,
            reason="deterministic smoke-test perception",
        )


class FakeLLM:
    def __init__(self):
        self.combined_calls = []

    def generate_combined(self, system_prompt, user_input):
        self.combined_calls.append((system_prompt, user_input))
        return {
            "response": "mock response",
            "memory_signal": None,
        }


class SmokeBrain(Brain):
    """Keep the smoke test focused on cognition wiring, not persistence."""

    def build_context(self, query, recent_limit=3):
        return {
            "recent_experiences": [],
            "relevant_knowledge": [],
            "graph_relations": [],
        }

    def _enqueue_learning(self, **kwargs):
        self.learning_jobs = getattr(self, "learning_jobs", [])
        self.learning_jobs.append(kwargs)


class PerceptionRouterBrainSmokeTests(unittest.TestCase):
    def test_input_flows_perception_router_brain_to_mock_llm(self):
        provider = FakePerceptionProvider()
        perception = PerceptionEngine(providers=[provider])
        llm = FakeLLM()
        brain = SmokeBrain(
            llm_bridge=llm,
            perception_engine=perception,
            cognitive_router=CognitiveRouter(),
        )

        response = brain.think_and_respond("hello jarvis", source="smoke")

        self.assertEqual(response, "mock response")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][0], "hello jarvis")
        self.assertEqual(brain.last_perception["source"], "fake")
        self.assertEqual(brain.last_cognitive_decision["mode"], "llm")
        self.assertTrue(brain.last_cognitive_decision["llm_required"])
        self.assertEqual(len(llm.combined_calls), 1)
        self.assertIn("hello jarvis", llm.combined_calls[0][1])
        self.assertTrue(brain.last_turn_trace["pipeline_success"])

    def test_structured_perception_routes_to_registered_native_skill(self):
        provider = FakePerceptionProvider(
            intent={"name": "execute", "skill": "ping", "confidence": 0.98},
            confidence=0.98,
        )
        perception = PerceptionEngine(providers=[provider])
        registry = SkillRegistry()
        registry.register("ping", lambda **kwargs: "pong")

        brain = SmokeBrain(
            llm_bridge=None,
            perception_engine=perception,
            cognitive_router=CognitiveRouter(),
            skill_registry=registry,
        )

        response = brain.think_and_respond("ping jarvis", source="smoke")

        self.assertEqual(response, "pong")
        self.assertEqual(brain.last_cognitive_decision["mode"], "tool")
        self.assertFalse(brain.last_cognitive_decision["llm_required"])
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(brain.last_turn_trace["pipeline_success"])


if __name__ == "__main__":
    unittest.main()
