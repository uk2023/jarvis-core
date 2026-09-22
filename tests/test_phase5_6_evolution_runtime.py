from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.learning.controlled_evolution import ControlledEvolutionEngine
from core.learning.runtime_evolution_adapter import RuntimeEvolutionAdapter
from core.organism.event_bus import EventBus
from core.organism.internal_state import InternalState
from database.sqlite_store import SQLiteStore


class Phase5And6EvolutionRuntimeTests(unittest.TestCase):
    """Phase 5: real runtime mutation; Phase 6: persistence/versioning/rollback."""

    def _proposal(self, evolution, parameters):
        proposal = evolution.propose(
            evaluation={
                "type": "SELF_EVALUATION",
                "score": 0.2,
                "errors": ["ROUTE_ERROR"],
                "strengths": [],
            },
            target="organism_runtime",
        )
        proposal["change"]["parameters"] = parameters
        evolution.validate(proposal["id"])
        evolution.approve(proposal["id"])
        return proposal

    def _runtime(self, path: Path):
        store = SQLiteStore(str(path))
        state = InternalState()
        events = EventBus(internal_state=state)
        memory = type("Memory", (), {"store": store})()
        adapter = RuntimeEvolutionAdapter(event_bus=events, memory_manager=memory)
        return store, events, adapter

    def test_phase5_approved_evolution_materializes_real_runtime_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _events, adapter = self._runtime(Path(tmp) / "jarvis.db")
            try:
                evolution = ControlledEvolutionEngine(adapters={"organism_runtime": adapter})
                proposal = self._proposal(evolution, {"routing_policy": "native_first", "confidence_floor": 0.8})
                applied = evolution.apply(proposal["id"])

                self.assertEqual(applied["status"], "APPLIED")
                self.assertEqual(applied["execution"]["revision_id"], "r1")
                self.assertEqual(
                    adapter.current()["profile"],
                    {"routing_policy": "native_first", "confidence_floor": 0.8},
                )
                self.assertEqual(evolution.runtime_state()["active"]["revision_id"], "r1")
            finally:
                store.close()

    def test_phase5_unapproved_proposal_cannot_mutate_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _events, adapter = self._runtime(Path(tmp) / "jarvis.db")
            try:
                evolution = ControlledEvolutionEngine(adapters={"organism_runtime": adapter})
                proposal = evolution.propose(
                    evaluation={"score": 0.1, "errors": ["TEST"], "strengths": []},
                    target="organism_runtime",
                )
                proposal["change"]["parameters"] = {"routing_policy": "unsafe"}
                with self.assertRaises(RuntimeError):
                    evolution.apply(proposal["id"])
                self.assertIsNone(adapter.current())
            finally:
                store.close()

    def test_phase6_runtime_revision_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jarvis.db"
            store, _events, adapter = self._runtime(db)
            evolution = ControlledEvolutionEngine(adapters={"organism_runtime": adapter})
            proposal = self._proposal(evolution, {"routing_policy": "hybrid", "confidence_floor": 0.7})
            evolution.apply(proposal["id"])
            store.close()

            store2, _events2, adapter2 = self._runtime(db)
            try:
                current = adapter2.current()
                self.assertEqual(current["revision_id"], "r1")
                self.assertEqual(current["profile"]["routing_policy"], "hybrid")
                self.assertEqual(len(adapter2.history()), 1)
            finally:
                store2.close()

    def test_phase6_rollback_creates_new_revision_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jarvis.db"
            store, _events, adapter = self._runtime(db)
            evolution = ControlledEvolutionEngine(adapters={"organism_runtime": adapter})
            first = self._proposal(evolution, {"routing_policy": "native_first"})
            evolution.apply(first["id"])
            second = self._proposal(evolution, {"routing_policy": "llm_first"})
            evolution.apply(second["id"])

            rolled = evolution.rollback_runtime("r1")
            self.assertEqual(rolled["revision_id"], "r3")
            self.assertEqual(rolled["operation"], "ROLLBACK")
            self.assertEqual(rolled["rolled_back_to"], "r1")
            self.assertEqual(adapter.current()["profile"]["routing_policy"], "native_first")
            self.assertEqual(len(adapter.history()), 3)
            store.close()

            store2, _events2, adapter2 = self._runtime(db)
            try:
                self.assertEqual(adapter2.current()["revision_id"], "r3")
                self.assertEqual(adapter2.current()["profile"]["routing_policy"], "native_first")
                self.assertEqual(len(adapter2.history()), 3)
            finally:
                store2.close()

    def test_phase6_unknown_rollback_revision_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _events, adapter = self._runtime(Path(tmp) / "jarvis.db")
            try:
                evolution = ControlledEvolutionEngine(adapters={"organism_runtime": adapter})
                with self.assertRaises(KeyError):
                    evolution.rollback_runtime("r999")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
