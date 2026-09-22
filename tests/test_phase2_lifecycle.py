from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.autonomy.goal_manager import GoalManager
from core.autonomy.idle_loop import IdleLoop
from database.sqlite_store import SQLiteStore


class _NoOpCuriosity:
    def candidates(self, state=None, goals=None):
        return []


class _FixedPlanner:
    def __init__(self, plan):
        self.plan_data = list(plan)
        self.calls = 0

    def plan(self, goal):
        self.calls += 1
        return list(self.plan_data)


class _EventBusSpy:
    def __init__(self):
        self.events = []

    def safe_emit(self, name, payload=None, source=None):
        self.events.append((name, payload, source))


class Phase2LifecycleTests(unittest.TestCase):
    """Phase 2: verify the living lifecycle, persistence, and goal cursor."""

    def test_goal_executes_one_step_per_idle_cycle_until_complete(self):
        planner = _FixedPlanner([
            {"action": "STEP_1"},
            {"action": "STEP_2"},
        ])
        executed = []

        class MemoryStore:
            def __init__(self):
                self.value = None

            def get_meta(self, key):
                return self.value

            def set_meta(self, key, value):
                self.value = value

        store = MemoryStore()
        goals = GoalManager(store=store)
        goal = goals.add("complete two-step test goal")

        def executor(step, goal=None):
            executed.append((goal["id"], step["action"]))
            return {"success": True, "action": step["action"]}

        loop = IdleLoop(
            goal_manager=goals,
            curiosity=_NoOpCuriosity(),
            planner=planner,
            state=None,
            event_bus=_EventBusSpy(),
            store=store,
            executor=executor,
            max_actions_per_step=1,
        )

        first = loop.step()
        self.assertEqual(first["step_index"], 1)
        self.assertEqual(executed, [(goal["id"], "STEP_1")])
        self.assertEqual(goals._find(goal["id"])["status"], "active")

        second = loop.step()
        self.assertEqual(second["step_index"], 2)
        self.assertEqual(executed[-1], (goal["id"], "STEP_2"))
        self.assertEqual(goals._find(goal["id"])["status"], "completed")
        self.assertEqual(planner.calls, 1)

    def test_failed_step_does_not_advance_goal_cursor(self):
        planner = _FixedPlanner([{ "action": "FAIL" }, {"action": "NEVER_YET"}])
        goals = GoalManager()
        goal = goals.add("retry failed work")

        loop = IdleLoop(
            goal_manager=goals,
            curiosity=_NoOpCuriosity(),
            planner=planner,
            executor=lambda step, goal=None: {"success": False, "error": "test failure"},
            max_actions_per_step=1,
        )

        result = loop.step()
        current = goals._find(goal["id"])
        self.assertEqual(result["step_index"], 0)
        self.assertEqual(current["step_index"], 0)
        self.assertEqual(current["status"], "active")
        self.assertEqual(len(current["progress"]), 1)

    def test_confirmation_step_does_not_execute_or_advance(self):
        planner = _FixedPlanner([
            {"action": "DANGEROUS_STEP", "requires_confirmation": True},
        ])
        executed = []
        goals = GoalManager()
        goal = goals.add("confirmation boundary")

        loop = IdleLoop(
            goal_manager=goals,
            curiosity=_NoOpCuriosity(),
            planner=planner,
            executor=lambda step, goal=None: executed.append(step),
            max_actions_per_step=1,
        )

        result = loop.step()
        current = goals._find(goal["id"])
        self.assertEqual(executed, [])
        self.assertEqual(result["step_index"], 0)
        self.assertEqual(len(result["awaiting_confirmation"]), 1)
        self.assertEqual(current["step_index"], 0)
        self.assertEqual(current["status"], "active")
        self.assertEqual(len(loop.pending_confirmations), 1)

    def test_goal_progress_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "phase2.db")

            store1 = SQLiteStore(db_path)
            goals1 = GoalManager(store=store1)
            goal = goals1.add("persistent goal", priority=0.9, origin="user")
            goals1.set_plan(goal["id"], [{"action": "A"}, {"action": "B"}])
            goals1.update_status(goal["id"], "active")
            goals1.advance_step(goal["id"])
            goals1.add_progress(goal["id"], "Executed: A")
            store1.close()

            store2 = SQLiteStore(db_path)
            goals2 = GoalManager(store=store2)
            restored = goals2._find(goal["id"])

            self.assertIsNotNone(restored)
            self.assertEqual(restored["text"], "persistent goal")
            self.assertEqual(restored["status"], "active")
            self.assertEqual(restored["step_index"], 1)
            self.assertEqual(restored["plan"][0]["action"], "A")
            self.assertEqual(restored["progress"][0]["note"], "Executed: A")
            store2.close()

    def test_episodic_memory_survives_restart(self):
        """Verify the durable SQLite lifecycle independently of cognition."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "memory.db")
            episode = {
                "episode_id": "phase2-episode-1",
                "timestamp": 1.0,
                "event_type": "TASK_COMPLETED",
                "context": {"goal": "remember me"},
                "action": {"name": "test_action"},
                "outcome": {"success": True},
                "importance": 0.8,
                "confidence": 1.0,
                "source": "phase2-test",
                "tags": ["phase2"],
            }

            store1 = SQLiteStore(db_path)
            store1.save_episode(episode)
            self.assertEqual(store1.statistics()["episodes"], 1)
            store1.close()

            store2 = SQLiteStore(db_path)
            restored = store2.load_episodes()
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0]["episode_id"], episode["episode_id"])
            self.assertEqual(restored[0]["context"]["goal"], "remember me")
            self.assertTrue(restored[0]["outcome"]["success"])
            store2.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
