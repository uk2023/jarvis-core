from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, Optional

from .evolution_engine import EvolutionEngine


class ControlledEvolutionEngine(EvolutionEngine):
    """Runtime evolution boundary with explicit, controlled adapters."""
    VERSION = "0.3.0-controlled"

    def __init__(self, *args, adapters: Optional[Dict[str, Callable[..., Any]]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._adapters: Dict[str, Callable[..., Any]] = dict(adapters or {})
        self.last_execution: Optional[Dict[str, Any]] = None

    def register_adapter(self, target: str, handler: Callable[..., Any]) -> None:
        if not target: raise ValueError("Evolution adapter target cannot be empty.")
        if not callable(handler): raise TypeError("Evolution adapter must be callable.")
        self._adapters[target] = handler

    def unregister_adapter(self, target: str) -> None: self._adapters.pop(target, None)
    def adapter_targets(self): return sorted(self._adapters)

    def apply(self, proposal_id: str) -> Dict[str, Any]:
        proposal = self._get_proposal(proposal_id)
        if proposal.get("status") != "APPROVED": raise RuntimeError("Only APPROVED proposals can be applied.")
        target = str(proposal.get("target") or "")
        handler = self._adapters.get(target)
        if handler is None:
            self._emit("EVOLUTION_APPLY_BLOCKED", {"proposal_id": proposal_id, "target": target, "reason": "NO_ADAPTER"})
            raise PermissionError(f"No approved runtime adapter is registered for evolution target: {target}")
        try:
            result = handler(proposal)
        except Exception as exc:
            self.last_execution = {"proposal_id": proposal_id, "target": target, "status": "FAILED", "error": str(exc)}
            self._emit("EVOLUTION_APPLY_FAILED", self.last_execution)
            raise
        if not isinstance(result, dict): result = {"result": result}
        result.setdefault("revision_id", f"{target}:{uuid.uuid4()}")
        result.setdefault("revision", 1)
        result.setdefault("profile", {})
        result.setdefault("next_cycle_ready", True)
        result.setdefault("change_record", {"target": target, "proposal_id": proposal_id})
        proposal["execution"] = result
        proposal["revision_id"] = result["revision_id"]
        proposal["revision"] = result["revision"]
        applied = super().apply(proposal_id)
        if not isinstance(applied, dict):
            applied = {"status": "APPLIED", "result": applied}
        applied.update({
            "revision_id": result["revision_id"],
            "revision": result["revision"],
            "next_cycle_ready": result["next_cycle_ready"],
            "change_record": result["change_record"],
            "execution": result,
        })
        self.last_execution = {"proposal_id": proposal_id, "target": target, "status": "APPLIED", "result": result}
        self._emit("EVOLUTION_EXECUTED", self.last_execution)
        return applied

    def rollback_runtime(self, revision_id: str, target: str = "organism_runtime") -> Dict[str, Any]:
        if target != "organism_runtime": raise PermissionError("Runtime rollback is allowlisted to organism_runtime.")
        handler = self._adapters.get(target); rollback = getattr(handler, "rollback", None)
        if not callable(rollback): raise RuntimeError("Registered runtime adapter does not support rollback.")
        result = rollback(revision_id)
        self._emit("EVOLUTION_ROLLBACK", {"target": target, "revision_id": result.get("revision_id"), "rolled_back_to": revision_id})
        return result

    def runtime_state(self, target: str = "organism_runtime") -> Dict[str, Any]:
        handler = self._adapters.get(target); snapshot = getattr(handler, "snapshot", None)
        return snapshot() if callable(snapshot) else {}

    def statistics(self) -> Dict[str, Any]:
        result = super().statistics(); result["adapter_targets"] = self.adapter_targets(); result["last_execution"] = self.last_execution; result["runtime_state"] = self.runtime_state(); return result
