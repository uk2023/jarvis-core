from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping, Optional


class IdleExecutor:
    """Bounded execution boundary for autonomous plan steps.

    Planner output is data, never executable code. Only explicitly registered
    capabilities are callable. Confirmation-required steps never execute.
    """

    VERSION = "0.1.1"

    def __init__(self, capabilities: Optional[Mapping[str, Callable[..., Any]]] = None, event_bus=None):
        # Keep a supplied mutable registry mapping live so newly learned skills
        # become visible without rebuilding the organism.
        self.capabilities = capabilities if capabilities is not None else {}
        self.events = event_bus

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        if not name or not callable(handler):
            raise ValueError("Idle capability requires a name and callable handler.")
        self.capabilities[str(name)] = handler

    def execute(self, step: Mapping[str, Any]) -> Dict[str, Any]:
        started = time.time()
        step_data = dict(step or {})
        action = step_data.get("action")
        result: Dict[str, Any] = {
            "success": False,
            "action": action,
            "result": None,
            "side_effects": [],
            "learnable": True,
            "risk": step_data.get("risk", "unknown"),
            "duration": 0.0,
        }
        if step_data.get("requires_confirmation") is True:
            result["result"] = "confirmation_required"
            result["duration"] = time.time() - started
            return result

        capability = step_data.get("capability") or step_data.get("skill") or action
        if not capability or capability not in self.capabilities:
            result["result"] = f"capability_not_registered: {capability}"
            result["duration"] = time.time() - started
            return result

        try:
            result["result"] = self.capabilities[capability](step_data)
            result["success"] = True
            result["side_effects"] = list(step_data.get("declared_side_effects", []))
        except Exception as exc:
            result["result"] = str(exc)

        result["duration"] = time.time() - started
        self._emit("IDLE_EXECUTION_COMPLETE", result)
        return result

    def __call__(self, step: Mapping[str, Any]) -> Dict[str, Any]:
        return self.execute(step)

    def _emit(self, name: str, payload: Any) -> None:
        if self.events is None:
            return
        emit = getattr(self.events, "safe_emit", None) or getattr(self.events, "emit", None)
        if callable(emit):
            try:
                emit(name, payload, source="idle_executor")
            except TypeError:
                try:
                    emit(name, payload)
                except Exception:
                    pass
            except Exception:
                pass
