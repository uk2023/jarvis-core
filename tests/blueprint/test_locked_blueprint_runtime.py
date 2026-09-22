"""Runtime integration contracts for the locked JARVIS architecture.

These tests complement the static boundary suite. They execute the real
Brain autonomous boundary and the real IdleLoop with that Brain boundary.
They deliberately do not replace the locked architecture with a new design.
"""

import unittest
from unittest.mock import Mock

from core.autonomy.idle_loop import IdleLoop
from core.orchestration.brain import Brain


class _GoalManager:
    def __init__(self, goal):
        self.goal = dict(goal)
        self.goal["plan"] = list(self.goal.get("plan") or [])
        self.goal["step_index"] = int(self.goal.get("step_index", 0))
        self.status = "pending"
        self.progress = []

    def pending(self):
        return [self.goal] if self.status != "completed" else []

    def add(self, **kwargs):
        return None

    def next_goal(self):
        return self.goal if self.status != "completed" else None

    def update_status(self, goal_id, status):
        self.status = status

    def set_plan(self, goal_id, plan):
        self.goal["plan"] = list(plan)

    def _find(self, goal_id):
        return self.goal

    def advance_step(self, goal_id):
        self.goal["step_index"] += 1

    def add_progress(self, goal_id, message):
        self.progress.append(message)


class LockedBlueprintRuntimeTests(unittest.TestCase):
    def _brain(self):
        skill_executor = Mock()
        skill_executor.execute.return_value = "native-ok"
        brain = Brain(skill_executor=skill_executor)
        # Keep this test focused on the Brain boundary. The locked learning
        # suite separately verifies Experience -> Evaluation -> Learning.
        brain._enqueue_learning = Mock()
        return brain, skill_executor

    def test_brain_autonomous_success_crosses_action_to_experience_boundary(self):
        brain, executor = self._brain()

        result = brain.execute_autonomous_step(
            {"action": "safe_action", "skill": "safe_action", "input": "run"},
            goal={"id": "g1", "text": "test goal"},
        )

        self.assertTrue(result["success"])
        executor.execute.assert_called_once_with("safe_action", user_input="run")
        brain._enqueue_learning.assert_called_once()
        call = brain._enqueue_learning.call_args.kwargs
        self.assertEqual(call["event_type"], "AUTONOMOUS_STEP")
        self.assertEqual(call["source"], "idle")
        self.assertTrue(call["outcome"]["success"])

    def test_brain_autonomous_failure_also_crosses_experience_boundary(self):
        brain, executor = self._brain()
        executor.execute.side_effect = RuntimeError("boom")

        result = brain.execute_autonomous_step(
            {"action": "safe_action", "skill": "safe_action"},
            goal={"id": "g1"},
        )

        self.assertFalse(result["success"])
        brain._enqueue_learning.assert_called_once()
        call = brain._enqueue_learning.call_args.kwargs
        self.assertEqual(call["event_type"], "AUTONOMOUS_STEP")
        self.assertFalse(call["outcome"]["success"])

    def test_idle_loop_uses_brain_as_its_only_execution_boundary(self):
        brain, executor = self._brain()
        goal_manager = _GoalManager(
            {
                "id": "g1",
                "text": "safe idle goal",
                "plan": [{"action": "safe_action", "skill": "safe_action"}],
            }
        )
        curiosity = Mock()
        curiosity.candidates.return_value = []
        planner = Mock()

        idle = IdleLoop(
            goal_manager=goal_manager,
            curiosity=curiosity,
            planner=planner,
            executor=brain.execute_autonomous_step,
            max_actions_per_step=1,
        )

        result = idle.step()

        self.assertEqual(len(result["executed"]), 1)
        self.assertTrue(result["executed"][0]["success"])
        executor.execute.assert_called_once_with("safe_action", user_input="safe_action")
        brain._enqueue_learning.assert_called_once()
        self.assertEqual(
            brain._enqueue_learning.call_args.kwargs["event_type"],
            "AUTONOMOUS_STEP",
        )

    def test_idle_confirmation_does_not_cross_into_brain_execution(self):
        brain, executor = self._brain()
        goal_manager = _GoalManager(
            {
                "id": "g1",
                "text": "dangerous idle goal",
                "plan": [
                    {
                        "action": "dangerous_action",
                        "skill": "dangerous_action",
                        "requires_confirmation": True,
                    }
                ],
            }
        )
        curiosity = Mock()
        curiosity.candidates.return_value = []

        idle = IdleLoop(
            goal_manager=goal_manager,
            curiosity=curiosity,
            planner=Mock(),
            executor=brain.execute_autonomous_step,
        )

        result = idle.step()

        self.assertEqual(result["executed"], [])
        self.assertEqual(len(result["awaiting_confirmation"]), 1)
        executor.execute.assert_not_called()
        brain._enqueue_learning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
