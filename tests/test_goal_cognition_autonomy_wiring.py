import unittest

from core.autonomy.goal_manager import GoalManager
from core.autonomy.idle_loop import IdleLoop


class _Curiosity:
    def candidates(self, state=None, goals=None):
        return []


class _Planner:
    def plan(self, goal):
        return [
            {"action": "step_one", "requires_confirmation": False},
            {"action": "step_two", "requires_confirmation": False},
        ]


class GoalCognitionAutonomyWiringTests(unittest.TestCase):
    def test_active_goal_is_exposed_to_cognition(self):
        manager = GoalManager()
        goal = manager.add("finish wiring", priority=0.9)
        manager.update_status(goal["id"], "active")
        self.assertEqual(manager.current_goal["id"], goal["id"])
        self.assertEqual(manager.current_goal["text"], "finish wiring")

    def test_autonomous_goal_advances_across_planned_steps_and_completes(self):
        manager = GoalManager()
        goal = manager.add("finish wiring", priority=0.9)
        executed = []

        def executor(step, goal=None):
            executed.append((goal["id"], step["action"]))
            return {"success": True, "status": "completed", "action": step["action"]}

        idle = IdleLoop(
            goal_manager=manager,
            curiosity=_Curiosity(),
            planner=_Planner(),
            executor=executor,
            max_actions_per_step=1,
        )

        first = idle.step()
        second = idle.step()

        self.assertEqual(first["step_index"], 1)
        self.assertEqual(second["step_index"], 2)
        self.assertEqual(executed, [(goal["id"], "step_one"), (goal["id"], "step_two")])
        self.assertEqual(manager._find(goal["id"])["status"], "completed")

    def test_failed_autonomous_step_does_not_advance_goal(self):
        manager = GoalManager()
        goal = manager.add("recover safely", priority=0.8)

        def executor(step, goal=None):
            return {"success": False, "status": "failed", "action": step["action"]}

        idle = IdleLoop(
            goal_manager=manager,
            curiosity=_Curiosity(),
            planner=_Planner(),
            executor=executor,
            max_actions_per_step=1,
        )

        result = idle.step()
        stored = manager._find(goal["id"])

        self.assertEqual(result["step_index"], 0)
        self.assertEqual(stored["step_index"], 0)
        self.assertEqual(stored["status"], "active")


if __name__ == "__main__":
    unittest.main()
