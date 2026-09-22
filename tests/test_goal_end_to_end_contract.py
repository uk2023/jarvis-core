import unittest

from core.autonomy.goal_manager import GoalManager
from core.autonomy.idle_loop import IdleLoop
from core.autonomy.planner import Planner
from core.orchestration.cognitive_router import CognitiveRouter
from core.orchestration.brain import Brain
from core.orchestration.perception import PerceptionEngine, PerceptionResult


class _GoalProvider:
    name = "test-goal"

    def perceive(self, user_input, context=None):
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "create_goal", "confidence": 0.98},
            goal={"text": "learn JARVIS architecture", "priority": 0.9},
            confidence=0.98,
            uncertainty=0.02,
            source=self.name,
            reason="explicit goal in test input",
        )


class _Executor:
    def __init__(self):
        self.calls = []

    def execute(self, skill_name, user_input=None):
        self.calls.append((skill_name, user_input))
        return "native-ok"


class GoalEndToEndContractTests(unittest.TestCase):
    def _brain(self):
        manager = GoalManager()
        planner = Planner(llm_bridge=None)
        perception = PerceptionEngine(providers=[_GoalProvider()])
        executor = _Executor()
        brain = Brain(
            goal_manager=manager,
            planner=planner,
            cognitive_router=CognitiveRouter(),
            perception_engine=perception,
            skill_executor=executor,
            llm_bridge=None,
        )
        return brain, manager, executor

    def test_user_goal_flows_perception_to_cognition_to_planner_to_brain_decision(self):
        brain, manager, _ = self._brain()

        response = brain.think_and_respond("I want to learn JARVIS architecture")

        goal = manager.current_goal
        self.assertIsNotNone(goal)
        self.assertEqual(goal["origin"], "user")
        self.assertEqual(goal["text"], "learn JARVIS architecture")
        self.assertTrue(goal["plan"])
        self.assertEqual(brain.last_cognitive_decision["mode"], "goal")
        self.assertEqual(brain.last_brain_decision["mode"], "goal")
        self.assertEqual(brain.last_brain_decision["status"], "planned")
        self.assertIn("Goal accepted", response)
        self.assertEqual(brain.last_turn_trace["perception"]["goal"]["text"], "learn JARVIS architecture")

    def test_autonomous_plan_step_crosses_brain_boundary_and_returns_action_response(self):
        brain, manager, executor = self._brain()
        goal = manager.add("verify_knowledge architecture", priority=0.8, origin="curiosity")
        manager.update_status(goal["id"], "active")
        plan = Planner(llm_bridge=None).plan(goal)
        manager.set_plan(goal["id"], plan)

        result = brain.execute_autonomous_step(
            plan[0],
            goal=manager.current_goal,
        )

        self.assertTrue(result["success"])
        self.assertEqual(brain.last_brain_decision["source"], "idle")
        self.assertEqual(brain.last_brain_decision["mode"], "native")
        self.assertEqual(brain.last_action_response["status"], "completed")
        self.assertEqual(executor.calls[0][0], plan[0]["action"])

    def test_idle_loop_uses_brain_executor_for_autonomous_goal(self):
        brain, manager, executor = self._brain()
        goal = manager.add("verify_knowledge architecture", priority=0.8, origin="curiosity")
        idle = IdleLoop(
            goal_manager=manager,
            curiosity=type("Curiosity", (), {"candidates": lambda self, state=None, goals=None: []})(),
            planner=Planner(llm_bridge=None),
            executor=brain.execute_autonomous_step,
            state=None,
        )

        result = idle.step()

        self.assertEqual(result["goal_id"], goal["id"])
        self.assertTrue(result["executed"])
        self.assertEqual(result["executed"][0]["success"], True)
        self.assertTrue(executor.calls)


if __name__ == "__main__":
    unittest.main()
