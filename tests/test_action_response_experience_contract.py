import unittest

from core.learning.experience_engine import ExperienceEngine
from core.learning.self_evaluator import SelfEvaluator


class ActionResponseExperienceContractTests(unittest.TestCase):
    """Verify the completed Action/Response payload is consumable by the experience/evaluation layer."""

    def test_completed_native_action_response_becomes_evaluated_experience(self):
        action_response = {
            "mode": "native",
            "status": "completed",
            "response": "pong",
            "action": {"skill": "ping", "result": "pong"},
        }

        experience_engine = ExperienceEngine()
        result = experience_engine.process(
            event_type="BRAIN_ACTION_RESPONSE",
            context={"route": "native"},
            action=action_response,
            outcome={"status": "completed", "success": True, "score": 1.0},
            source="brain",
        )

        self.assertTrue(result["experience"]["success"])
        self.assertEqual(result["experience"]["action"], action_response)
        self.assertEqual(result["learning_signal"]["type"], "LEARNING_SIGNAL")
        self.assertEqual(result["learning_signal"]["success"], True)

        evaluation = SelfEvaluator().evaluate(result["experience"])
        self.assertEqual(evaluation["type"], "SELF_EVALUATION")
        self.assertTrue(evaluation["success"])
        self.assertEqual(evaluation["score"], 1.0)
        self.assertIn("ACTION_WAS_EXECUTED", evaluation["strengths"])

    def test_failed_action_response_becomes_failure_experience(self):
        action_response = {
            "mode": "native",
            "status": "failed",
            "response": "skill execution failed",
            "action": {"skill": "ping"},
            "error": "skill unavailable",
        }

        experience = ExperienceEngine().process(
            event_type="BRAIN_ACTION_RESPONSE",
            context={"route": "native"},
            action=action_response,
            outcome={"status": "failed", "success": False, "error": "skill unavailable"},
            source="brain",
        )["experience"]

        evaluation = SelfEvaluator().evaluate(experience)
        self.assertFalse(experience["success"])
        self.assertFalse(evaluation["success"])
        self.assertEqual(evaluation["score"], 0.0)
        self.assertIn("OUTCOME_FAILURE", evaluation["errors"])


if __name__ == "__main__":
    unittest.main()
