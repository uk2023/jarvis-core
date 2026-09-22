import unittest

from core.learning.controlled_evolution import ControlledEvolutionEngine
from core.organism.bootstrap import create_jarvis, stop_jarvis


class EvolutionExecutionWiringTests(unittest.TestCase):
    def test_bootstrap_wires_controlled_evolution_engine(self):
        jarvis = create_jarvis()
        try:
            evolution = jarvis.get_organ("evolution")
            self.assertIsInstance(evolution, ControlledEvolutionEngine)
            self.assertEqual(evolution.adapter_targets(), ["organism_runtime"])
            self.assertIn("runtime_evolution_adapter", jarvis.organs)
        finally:
            stop_jarvis(jarvis)

    def test_only_approved_proposal_reaches_registered_adapter(self):
        calls = []
        evolution = ControlledEvolutionEngine()
        evolution.register_adapter(
            "response_routing",
            lambda proposal: calls.append(proposal["id"]) or {"changed": True},
        )

        proposal = evolution.propose(
            evaluation={"score": 0.2, "errors": ["ROUTE_ERROR"], "strengths": []},
            target="response_routing",
        )
        evolution.validate(proposal["id"])

        with self.assertRaises(RuntimeError):
            evolution.apply(proposal["id"])
        self.assertEqual(calls, [])
        self.assertEqual(evolution.get_proposal(proposal["id"])["status"], "VALIDATED")

        evolution.approve(proposal["id"])
        applied = evolution.apply(proposal["id"])

        self.assertEqual(calls, [proposal["id"]])
        self.assertEqual(applied["status"], "APPLIED")
        execution = applied["execution"]
        self.assertTrue(execution["changed"])
        self.assertIsInstance(execution["revision_id"], str)
        self.assertGreaterEqual(execution["revision"], 1)
        self.assertTrue(execution["next_cycle_ready"])
        self.assertEqual(
            execution["change_record"],
            {"target": "response_routing", "proposal_id": proposal["id"]},
        )
        self.assertEqual(evolution.statistics()["applied"], 1)

    def test_approved_proposal_without_adapter_is_blocked(self):
        evolution = ControlledEvolutionEngine()
        proposal = evolution.propose(
            evaluation={"score": 0.1, "errors": ["TEST_FAILURE"], "strengths": []},
            target="unwired_target",
        )
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])

        with self.assertRaises(PermissionError):
            evolution.apply(proposal["id"])

        self.assertEqual(
            evolution.get_proposal(proposal["id"])["status"],
            "APPROVED",
        )
        self.assertEqual(evolution.statistics()["applied"], 0)
        self.assertIsNone(evolution.last_execution)


if __name__ == "__main__":
    unittest.main()
