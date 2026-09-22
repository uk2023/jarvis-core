import unittest

from core.organism.bootstrap import start_jarvis, stop_jarvis
from core.orchestration.perception import PerceptionResult


class BootstrapSmokePerceptionProvider:
    name = "bootstrap-smoke"

    def perceive(self, user_input, context=None):
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "execute", "skill": "ping", "confidence": 0.99},
            language="en",
            confidence=0.99,
            uncertainty=0.01,
            source=self.name,
            reason="deterministic bootstrap runtime smoke test",
        )


class BootstrapRuntimeSmokeTests(unittest.TestCase):
    def test_real_bootstrap_wires_organs_and_executes_native_action(self):
        jarvis = start_jarvis(heartbeat_interval=0.5, idle_threshold=1.0)
        try:
            self.assertTrue(jarvis.running)
            self.assertIs(jarvis.get_organ("brain"), jarvis.get_organ("brain"))
            self.assertIs(jarvis.get_organ("perception"), jarvis.get_organ("brain").perception)
            self.assertIs(jarvis.get_organ("cognitive_router"), jarvis.get_organ("brain").cognitive_router)
            self.assertIs(jarvis.get_organ("skill_registry"), jarvis.get_organ("brain").skill_registry)
            self.assertTrue(jarvis.lifecycle.is_running())
            self.assertTrue(jarvis.events.running)
            self.assertTrue(jarvis.heartbeat.running)

            brain = jarvis.get_organ("brain")
            registry = jarvis.get_organ("skill_registry")
            perception = jarvis.get_organ("perception")

            registry.register("ping", lambda **kwargs: "pong")
            perception.providers = [BootstrapSmokePerceptionProvider()]

            response = brain.think_and_respond("ping jarvis", source="bootstrap-smoke")

            self.assertEqual(response, "pong")
            self.assertEqual(brain.last_perception["source"], "bootstrap-smoke")
            self.assertEqual(brain.last_cognitive_decision["mode"], "tool")
            self.assertFalse(brain.last_cognitive_decision["llm_required"])
            self.assertTrue(brain.last_turn_trace["pipeline_success"])
            self.assertEqual(brain.last_turn_trace["cognitive_route"]["mode"], "tool")
        finally:
            stop_jarvis(jarvis)

        self.assertFalse(jarvis.heartbeat.running)
        self.assertFalse(jarvis.events.running)


if __name__ == "__main__":
    unittest.main()
