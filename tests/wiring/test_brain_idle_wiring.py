from __future__ import annotations

import pathlib
import sys
import time
import unittest

# Allow both `python3 -m unittest ...` and direct execution from repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.organism.bootstrap import create_jarvis


class BrainIdleWiringTests(unittest.TestCase):
    """Verify the runtime path Heartbeat -> EventBus -> IdleLoop -> Brain."""

    @staticmethod
    def assert_bound_method_targets(testcase, bound_method, owner, method_name):
        testcase.assertIs(bound_method.__self__, owner)
        testcase.assertEqual(bound_method.__func__.__name__, method_name)

    def test_heartbeat_idle_event_reaches_idle_loop(self):
        jarvis = create_jarvis(heartbeat_interval=0.5, idle_threshold=0.5)
        idle_loop = jarvis.get_organ("idle_loop")
        brain = jarvis.get_organ("brain")

        self.assertIsNotNone(idle_loop)
        self.assertIs(jarvis.idle_loop, idle_loop)
        self.assert_bound_method_targets(self, idle_loop.executor, brain, "execute_autonomous_step")

        calls = []
        original_step = idle_loop.step

        def spy_step():
            calls.append(True)
            return {"action": "TEST_IDLE_CYCLE"}

        idle_loop.step = spy_step
        try:
            # Force the organism into the idle condition without waiting
            # for a background heartbeat thread.
            jarvis.state.last_activity_at = time.time() - 10.0
            jarvis.heartbeat.running = True
            payload = jarvis.heartbeat.beat()

            self.assertTrue(payload["idle"])
            self.assertEqual(calls, [True])

            heartbeat_events = jarvis.event_bus.get_history("HEARTBEAT")
            self.assertTrue(heartbeat_events)
            self.assertTrue(heartbeat_events[-1].payload["idle"])
            self.assertEqual(
                jarvis.event_bus.get_subscribers("HEARTBEAT")["HEARTBEAT"],
                1,
            )
        finally:
            idle_loop.step = original_step
            jarvis.heartbeat.running = False

    def test_idle_loop_is_brain_owned(self):
        jarvis = create_jarvis()
        idle_loop = jarvis.get_organ("idle_loop")
        brain = jarvis.get_organ("brain")
        perception = jarvis.get_organ("perception")
        router = jarvis.get_organ("cognitive_router")

        self.assertIsNotNone(idle_loop)
        self.assertIsNotNone(brain)
        self.assert_bound_method_targets(self, idle_loop.executor, brain, "execute_autonomous_step")
        # Brain exposes the perception organ as `perception` (not
        # `perception_engine`). Keep the assertion aligned with the
        # actual Brain API rather than testing a nonexistent attribute.
        self.assertIs(brain.perception, perception)
        self.assertIs(brain.cognitive_router, router)


if __name__ == "__main__":
    unittest.main(verbosity=2)
