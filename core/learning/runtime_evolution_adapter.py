from __future__ import annotations

import copy
import time
from typing import Any, Dict, Optional


class RuntimeEvolutionAdapter:
    """
    Controlled runtime evolution adapter.

    Phase 5 makes an approved proposal produce a real runtime profile
    revision. Phase 6 persists that profile and keeps immutable revision
    history so the active runtime can be rolled back without touching
    source code or importing executable proposal content.
    """

    TARGET = "organism_runtime"
    VERSION = "0.2.0"
    META_KEY = "evolution.runtime_state"
    MAX_HISTORY = 50

    def __init__(self, event_bus=None, memory_manager=None):
        self.event_bus = event_bus
        self.memory = memory_manager
        self._state = self._load_state()

    def __call__(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_proposal(proposal)

        proposal_id = str(proposal["id"])
        change = proposal.get("change") or {}
        parameters = change.get("parameters", {})
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise ValueError("Runtime evolution parameters must be a dictionary.")

        previous = self._state.get("active")
        revision_number = int(self._state.get("revision", 0)) + 1
        revision_id = f"r{revision_number}"
        profile = copy.deepcopy(parameters)
        revision = {
            "revision_id": revision_id,
            "revision": revision_number,
            "proposal_id": proposal_id,
            "target": self.TARGET,
            "profile": profile,
            "created_at": time.time(),
        }

        self._state["revision"] = revision_number
        self._state["active"] = revision
        self._state.setdefault("history", []).append(revision)
        self._state["history"] = self._state["history"][-self.MAX_HISTORY:]
        self._persist_state()

        handoff = {
            "adapter": self.__class__.__name__,
            "adapter_version": self.VERSION,
            "proposal_id": proposal_id,
            "target": self.TARGET,
            "revision_id": revision_id,
            "revision": revision_number,
            "profile": copy.deepcopy(profile),
            "previous_revision_id": (previous or {}).get("revision_id"),
            "next_cycle_ready": True,
        }
        self._emit("EVOLUTION_RUNTIME_APPLIED", handoff)
        return handoff

    def current(self) -> Optional[Dict[str, Any]]:
        active = self._state.get("active")
        return copy.deepcopy(active) if active else None

    def history(self) -> list[Dict[str, Any]]:
        return copy.deepcopy(self._state.get("history", []))

    def rollback(self, revision_id: str) -> Dict[str, Any]:
        """Activate a previously stored revision as a new rollback revision."""
        revision_id = str(revision_id or "")
        source = next(
            (item for item in self._state.get("history", []) if item.get("revision_id") == revision_id),
            None,
        )
        if source is None:
            raise KeyError(f"Unknown runtime evolution revision: {revision_id}")

        new_number = int(self._state.get("revision", 0)) + 1
        rollback_revision = {
            "revision_id": f"r{new_number}",
            "revision": new_number,
            "proposal_id": source.get("proposal_id"),
            "target": self.TARGET,
            "profile": copy.deepcopy(source.get("profile", {})),
            "created_at": time.time(),
            "operation": "ROLLBACK",
            "rolled_back_to": revision_id,
        }
        self._state["revision"] = new_number
        self._state["active"] = rollback_revision
        self._state.setdefault("history", []).append(rollback_revision)
        self._state["history"] = self._state["history"][-self.MAX_HISTORY:]
        self._persist_state()
        self._emit("EVOLUTION_RUNTIME_ROLLED_BACK", rollback_revision)
        return copy.deepcopy(rollback_revision)

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self._state)

    def _validate_proposal(self, proposal: Dict[str, Any]) -> None:
        if not isinstance(proposal, dict):
            raise TypeError("Evolution proposal must be a dictionary.")
        if str(proposal.get("target") or "") != self.TARGET:
            raise PermissionError(
                f"RuntimeEvolutionAdapter only accepts target: {self.TARGET}"
            )
        if not str(proposal.get("id") or ""):
            raise ValueError("Evolution proposal id is required.")

    def _load_state(self) -> Dict[str, Any]:
        default = {"version": self.VERSION, "revision": 0, "active": None, "history": []}
        store = getattr(self.memory, "store", None)
        getter = getattr(store, "get_meta", None)
        if not callable(getter):
            return default
        stored = getter(self.META_KEY, default)
        if not isinstance(stored, dict):
            return default
        state = copy.deepcopy(default)
        state.update(stored)
        if not isinstance(state.get("history"), list):
            state["history"] = []
        return state

    def _persist_state(self) -> None:
        store = getattr(self.memory, "store", None)
        setter = getattr(store, "set_meta", None)
        if callable(setter):
            setter(self.META_KEY, self._state)

    def _emit(self, event_name: str, payload: Any) -> None:
        if self.event_bus is None:
            return
        emit = getattr(self.event_bus, "emit", None)
        if callable(emit):
            emit(event_name, payload, source="runtime_evolution_adapter")
