import unittest

from core.organism.bootstrap import create_jarvis, stop_jarvis


class IdleBrainWiringTests(unittest.TestCase):
    def test_idle_executor_is_brain_owned(self):
        jarvis = create_jarvis()
        try:
            brain = jarvis.get_organ("brain")
            idle_loop = jarvis.get_organ("idle_loop")
            self.assertIs(idle_loop.executor.__self__, brain)
            self.assertEqual(idle_loop.executor.__func__, brain.execute_autonomous_step.__func__)
        finally:
            stop_jarvis(jarvis)

    def test_autonomous_step_commits_brain_decision_and_learning_handoff(self):
        jarvis = create_jarvis()
        try:
            brain = jarvis.get_organ("brain")
            registry = jarvis.get_organ("skill_registry")
            registry.register("ping", lambda **kwargs: "pong")

            handed_off = []
            brain._enqueue_learning = lambda **kwargs: handed_off.append(kwargs)

            result = brain.execute_autonomous_step(
                {"action": "ping", "skill": "ping"},
                goal={"id": "g1", "text": "verify ping"},
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["result"], "pong")
            self.assertEqual(brain.last_brain_decision["mode"], "native")
            self.assertEqual(brain.last_brain_decision["source"], "idle")
            self.assertEqual(brain.last_action_response["status"], "completed")
            self.assertEqual(len(handed_off), 1)
            self.assertEqual(handed_off[0]["event_type"], "AUTONOMOUS_STEP")
            self.assertEqual(handed_off[0]["source"], "idle")
        finally:
            stop_jarvis(jarvis)

    def test_heartbeat_idle_event_triggers_idle_loop(self):
        jarvis = create_jarvis()
        try:
            idle_loop = jarvis.get_organ("idle_loop")
            calls = []
            idle_loop.step = lambda: calls.append(True)

            jarvis.events.emit("HEARTBEAT", {"idle": True}, source="test")
            jarvis.events.emit("HEARTBEAT", {"idle": False}, source="test")

            self.assertEqual(calls, [True])
        finally:
            stop_jarvis(jarvis)


if __name__ == "__main__":
    unittest.main()
