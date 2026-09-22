from __future__ import annotations

import unittest

from core.organism.bootstrap import create_jarvis, stop_jarvis
from core.orchestration.perception import PerceptionResult


class _NativePerceptionProvider:
    name = "phase4-test-native"

    def perceive(self, user_input, context=None):
        return PerceptionResult(
            user_input=user_input,
            normalized_text=user_input,
            intent={"name": "ping", "skill": "ping", "confidence": 0.99},
            confidence=0.99,
            uncertainty=0.01,
            source=self.name,
            reason="deterministic phase 4 test perception",
        )


class Phase4EvolutionCycleWiringTests(unittest.TestCase):
    """Phase 4: prove an applied evolution crosses into the next brain cycle."""

    def test_bootstrap_registers_only_the_allowlisted_runtime_adapter(self):
        jarvis = create_jarvis(heartbeat_interval=60.0, idle_threshold=120.0)
        try:
            evolution = jarvis.organs["evolution"]
            self.assertEqual(evolution.adapter_targets(), ["organism_runtime"])
            self.assertIn("runtime_evolution_adapter", jarvis.organs)
        finally:
            stop_jarvis(jarvis)

    def test_full_gate_applies_runtime_adapter_then_next_cycle_runs(self):
        jarvis = create_jarvis(heartbeat_interval=60.0, idle_threshold=120.0)
        try:
            evolution = jarvis.organs["evolution"]
            brain = jarvis.organs["brain"]
            registry = jarvis.organs["skill_registry"]
            registry.register("ping", lambda **_: "pong")
            brain.perception.providers = [_NativePerceptionProvider()]

            proposal = evolution.propose(
                evaluation={
                    "type": "SELF_EVALUATION",
                    "score": 0.2,
                    "errors": ["ROUTE_ERROR"],
                    "strengths": [],
                },
                target="organism_runtime",
            )
            evolution.validate(proposal["id"])
            evolution.approve(proposal["id"])
            applied = evolution.apply(proposal["id"])

            self.assertEqual(applied["status"], "APPLIED")
            self.assertEqual(applied["execution"]["target"], "organism_runtime")
            self.assertTrue(applied["execution"]["next_cycle_ready"])
            self.assertEqual(evolution.statistics()["applied"], 1)

            response = brain.think_and_respond("ping", source="phase4-test")
            self.assertEqual(response, "pong")

            history = jarvis.event_bus.get_history(limit=100)
            names = [event.name for event in history]
            applied_index = names.index("EVOLUTION_APPLIED")
            next_cycle_index = names.index("BRAIN_CYCLE_STARTED", applied_index + 1)
            self.assertLess(applied_index, next_cycle_index)

            runtime_applied = [
                event for event in history
                if event.name == "EVOLUTION_RUNTIME_APPLIED"
            ]
            self.assertEqual(len(runtime_applied), 1)
            self.assertEqual(
                runtime_applied[0].payload["proposal_id"],
                proposal["id"],
            )
            self.assertEqual(
                evolution.statistics()["last_execution"]["status"],
                "APPLIED",
            )
        finally:
            stop_jarvis(jarvis)

    def test_next_cycle_does_not_bypass_evolution_gate(self):
        jarvis = create_jarvis(heartbeat_interval=60.0, idle_threshold=120.0)
        try:
            evolution = jarvis.organs["evolution"]
            brain = jarvis.organs["brain"]

            proposal = evolution.propose(
                evaluation={"score": 0.2, "errors": ["TEST"], "strengths": []},
                target="organism_runtime",
            )

            with self.assertRaises(RuntimeError):
                evolution.apply(proposal["id"])

            self.assertEqual(proposal["status"], "PROPOSED")
            self.assertEqual(evolution.statistics()["applied"], 0)

            # A normal brain cycle remains executable, but it cannot
            # silently promote the unvalidated/unapproved proposal.
            result = brain.execute_autonomous_step(
                {"action": "unknown", "capability": "unknown"},
                goal={"id": "phase4-gate-test"},
            )
            self.assertFalse(result["success"])
            self.assertEqual(proposal["status"], "PROPOSED")
            self.assertEqual(evolution.statistics()["applied"], 0)
        finally:
            stop_jarvis(jarvis)


if __name__ == "__main__":
    unittest.main(verbosity=2)
