from __future__ import annotations

import unittest

from core.learning.controlled_evolution import ControlledEvolutionEngine
from core.organism.bootstrap import create_jarvis, stop_jarvis


class Phase3EvolutionLifecycleTests(unittest.TestCase):
    """Phase 3: verify controlled evolution remains gated and observable."""

    def _proposal(self, evolution, target="response_routing"):
        return evolution.propose(
            evaluation={
                "type": "SELF_EVALUATION",
                "score": 0.2,
                "errors": ["ROUTE_ERROR"],
                "strengths": [],
            },
            target=target,
        )

    def test_bootstrap_exposes_controlled_evolution_boundary(self):
        jarvis = create_jarvis()
        try:
            evolution = jarvis.get_organ("evolution")
            self.assertIsInstance(evolution, ControlledEvolutionEngine)
            self.assertIn("organism_runtime", evolution.adapter_targets())
        finally:
            stop_jarvis(jarvis)

    def test_proposal_requires_validation_then_approval_before_apply(self):
        evolution = ControlledEvolutionEngine()
        proposal = self._proposal(evolution)

        with self.assertRaises(RuntimeError):
            evolution.apply(proposal["id"])
        self.assertEqual(proposal["status"], "PROPOSED")

        evolution.validate(proposal["id"])
        self.assertEqual(proposal["status"], "VALIDATED")

        with self.assertRaises(RuntimeError):
            evolution.apply(proposal["id"])
        self.assertEqual(proposal["status"], "VALIDATED")

        evolution.approve(proposal["id"])
        self.assertEqual(proposal["status"], "APPROVED")

    def test_approved_proposal_without_adapter_is_blocked(self):
        evolution = ControlledEvolutionEngine()
        proposal = self._proposal(evolution, target="unwired_target")
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])

        with self.assertRaises(PermissionError):
            evolution.apply(proposal["id"])

        self.assertEqual(proposal["status"], "APPROVED")
        self.assertEqual(evolution.statistics()["applied"], 0)

    def test_adapter_failure_does_not_mark_evolution_applied(self):
        evolution = ControlledEvolutionEngine()
        proposal = self._proposal(evolution)
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])

        def failing_adapter(_proposal):
            raise RuntimeError("adapter failure")

        evolution.register_adapter("response_routing", failing_adapter)

        with self.assertRaisesRegex(RuntimeError, "adapter failure"):
            evolution.apply(proposal["id"])

        self.assertEqual(proposal["status"], "APPROVED")
        self.assertEqual(evolution.statistics()["applied"], 0)
        self.assertEqual(evolution.last_execution["status"], "FAILED")

    def test_approved_proposal_reaches_only_registered_adapter(self):
        calls = []
        evolution = ControlledEvolutionEngine()
        proposal = self._proposal(evolution)
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])

        evolution.register_adapter(
            "response_routing",
            lambda item: calls.append(item["id"]) or {"changed": True},
        )

        applied = evolution.apply(proposal["id"])

        self.assertEqual(calls, [proposal["id"]])
        self.assertEqual(applied["status"], "APPLIED")
        self.assertEqual(applied["execution"], {"changed": True})
        self.assertEqual(evolution.statistics()["applied"], 1)
        self.assertEqual(evolution.last_execution["status"], "APPLIED")

    def test_evolution_proposal_state_survives_snapshot_restore(self):
        evolution1 = ControlledEvolutionEngine()
        proposal = self._proposal(evolution1)
        evolution1.validate(proposal["id"])
        evolution1.approve(proposal["id"])

        snapshot = evolution1.snapshot()

        evolution2 = ControlledEvolutionEngine()
        evolution2.restore(snapshot)
        restored = evolution2.get_proposal(proposal["id"])

        self.assertIsNotNone(restored)
        self.assertEqual(restored["target"], "response_routing")
        self.assertEqual(restored["status"], "APPROVED")
        self.assertEqual(restored["id"], proposal["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
