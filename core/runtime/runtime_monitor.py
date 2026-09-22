from __future__ import annotations

import json
import os
import resource
import threading
import time
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PATH = os.path.join(BASE_DIR, "runtime", "jarvis_health.json")


class RuntimeMonitor:
    """Read-only, low-overhead runtime telemetry shared with JARVIS and CLI tools."""

    VERSION = "1.0"

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("JARVIS_HEALTH_FILE") or DEFAULT_PATH
        self._jarvis = None
        self._lock = threading.RLock()

    def bind_jarvis(self, jarvis) -> None:
        self._jarvis = jarvis

    @staticmethod
    def _stats(obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        fn = getattr(obj, "statistics", None)
        if not callable(fn):
            return {}
        try:
            value = fn()
            return value if isinstance(value, dict) else {"value": value}
        except Exception as exc:
            return {"error": str(exc)}

    def snapshot(self, organs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        organs = organs or (getattr(self._jarvis, "organs", {}) if self._jarvis is not None else {})
        heartbeat = organs.get("heartbeat")
        llm = organs.get("llm_bridge")
        state = organs.get("state")
        usage = resource.getrusage(resource.RUSAGE_SELF)
        threads = threading.enumerate()
        return {
            "timestamp": time.time(),
            "version": self.VERSION,
            "pid": os.getpid(),
            "process": {
                "max_rss_mb": round(float(usage.ru_maxrss) / 1024.0, 1),
                "user_cpu_seconds": round(usage.ru_utime, 3),
                "system_cpu_seconds": round(usage.ru_stime, 3),
                "threads": len(threads),
            },
            "heartbeat": {
                "running": bool(getattr(heartbeat, "running", False)),
                "beat_count": int(getattr(heartbeat, "beat_count", 0)),
                "is_idle": bool(getattr(heartbeat, "is_idle", False)),
                "interval": getattr(heartbeat, "interval", None),
            },
            "llm": {
                "backend": getattr(llm, "last_backend", "unknown"),
                "ready": bool(getattr(llm, "is_ready", False)),
                "local_loaded": getattr(llm, "_local_engine", None) is not None,
                "groq_loaded": getattr(llm, "_groq_engine", None) is not None,
                "last_error": getattr(llm, "last_error", None),
                "budget": llm.budget_status() if llm is not None and hasattr(llm, "budget_status") else {},
            },
            "learning": self._stats(organs.get("learning")),
            "self_evaluation": self._stats(organs.get("evaluator")),
            "knowledge": self._stats(organs.get("knowledge_builder")),
            "evolution": self._stats(organs.get("evolution")),
            # UK explicitly asked to be able to SEE idle memory
            # consolidation happen -- previously absent from every
            # visibility surface (CLI, web, monitor.py) even though
            # bootstrap.py was calling it every idle tick.
            "consolidation": self._stats(organs.get("consolidator")),
            "idle_loop": {
                "pending_confirmations": len(getattr(organs.get("idle_loop"), "pending_confirmations", []) or [])
            },
            "state": self._stats(state),
        }

    def write_snapshot(self, jarvis=None, organs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if jarvis is not None:
            self.bind_jarvis(jarvis)
        snapshot = self.snapshot(organs=organs)
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with self._lock:
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.write("\n")
                os.replace(tmp, self.path)
        except OSError:
            pass
        return snapshot

    def read_snapshot(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}
