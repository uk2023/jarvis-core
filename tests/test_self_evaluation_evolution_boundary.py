import unittest

from core.learning.evolution_engine import EvolutionEngine
from core.learning.self_evaluator import SelfEvaluator


class SelfEvaluationEvolutionBoundaryTests(unittest.TestCase):
    def test_self_evaluation_output_is_accepted_as_evolution_trigger(self):
        evaluator = SelfEvaluator()
        evolution = EvolutionEngine()

        experience = {
            "event_type": "NATIVE_ACTION_COMPLETED",
            "action": {"name": "test_action"},
            "outcome": {
                "success": False,
                "error": "TEST_FAILURE",
            },
            "success": False,
        }

        evaluation = evaluator.evaluate(experience)
        proposal = evolution.propose(
            evaluation=evaluation,
            target="response_routing",
        )

        self.assertEqual(evaluation["type"], "SELF_EVALUATION")
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertEqual(
            proposal["trigger"]["evaluation_score"],
            evaluation["score"],
        )
        self.assertEqual(
            proposal["trigger"]["errors"],
            evaluation["errors"],
        )

    def test_self_evaluation_does_not_implicitly_create_evolution_proposal(self):
        evaluator = SelfEvaluator()
        evolution = EvolutionEngine()

        evaluation = evaluator.evaluate({
            "event_type": "NATIVE_ACTION_COMPLETED",
            "action": {"name": "test_action"},
            "outcome": {"success": False, "error": "TEST_FAILURE"},
            "success": False,
        })

        self.assertEqual(evaluation["type"], "SELF_EVALUATION")
        self.assertEqual(evolution.list_proposals(), [])
        self.assertIsNone(evolution.last_proposal)

    def test_evolution_requires_explicit_controlled_state_transitions(self):
        evolution = EvolutionEngine()
        evaluation = {
            "type": "SELF_EVALUATION",
            "success": False,
            "score": 0.0,
            "errors": ["TEST_FAILURE"],
            "strengths": [],
        }

        proposal = evolution.propose(
            evaluation=evaluation,
            target="response_routing",
        )

        self.assertEqual(proposal["status"], "PROPOSED")

        validated = evolution.validate(proposal["id"])
        self.assertEqual(validated["status"], "VALIDATED")

        approved = evolution.approve(proposal["id"])
        self.assertEqual(approved["status"], "APPROVED")

        applied = evolution.apply(proposal["id"])
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(evolution.statistics()["applied"], 1)


if __name__ == "__main__":
    unittest.main()
