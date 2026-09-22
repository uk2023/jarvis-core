import unittest

from core.organism.bootstrap import create_jarvis
from core.orchestration.perception import PerceptionResult


class _NativePerceptionProvider:
    name = "test-native"

    def perceive(self, user_input, context=None):
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "ping", "skill": "ping", "confidence": 0.99},
            confidence=0.99,
            uncertainty=0.01,
            source=self.name,
            reason="deterministic test perception",
        )


class BrainLivingCycleEventTraceTests(unittest.TestCase):
    def test_real_brain_cycle_emits_ordered_organism_events(self):
        jarvis = create_jarvis(heartbeat_interval=60.0, idle_threshold=120.0)
        brain = jarvis.organs["brain"]
        registry = jarvis.organs["skill_registry"]
        registry.register("ping", lambda **_: "pong")
        brain.perception.providers = [_NativePerceptionProvider()]

        response = brain.think_and_respond("ping", source="test")

        self.assertEqual(response, "pong")
        names = [event.name for event in jarvis.event_bus.get_history(limit=50)]
        expected = [
            "BRAIN_CYCLE_STARTED",
            "PERCEPTION_COMPLETED",
            "COGNITION_ROUTED",
            "ACTION_RESPONSE_COMPLETED",
            "BRAIN_CYCLE_COMPLETED",
        ]
        positions = [names.index(name) for name in expected]
        self.assertEqual(positions, sorted(positions))

        trace = brain.last_turn_trace
        self.assertIsNotNone(trace)
        self.assertEqual(trace["action_response"]["status"], "completed")
        self.assertEqual(trace["cognitive_route"]["mode"], "tool")

    def test_event_stream_is_the_source_of_cycle_trace_not_a_separate_path(self):
        jarvis = create_jarvis(heartbeat_interval=60.0, idle_threshold=120.0)
        brain = jarvis.organs["brain"]
        registry = jarvis.organs["skill_registry"]
        registry.register("ping", lambda **_: "pong")
        brain.perception.providers = [_NativePerceptionProvider()]

        brain.think_and_respond("ping", source="test")

        completed = [
            event for event in jarvis.event_bus.get_history(limit=50)
            if event.name == "BRAIN_CYCLE_COMPLETED"
        ]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].payload["trace"], brain.last_turn_trace)


if __name__ == "__main__":
    unittest.main()
