from __future__ import annotations

"""CODING AGENT -- unified tool contract + dynamic registry (Phase 3/5).

Distinct from core/orchestration/tool_registry.py, which is JARVIS's
LLM-facing function-calling registry (Groq tool-use JSON schemas for
ordinary chat turns -- "pending rules dikhao" style tools). THIS
registry is the Coding Agent's OWN internal tool belt: filesystem,
git, test-runner and packaging operations the agent invokes itself,
step by step, inside one coding task. The two meet at exactly one
door: tool_registry.py's "run_coding_agent" WRITE_TOOL is what the
chat-facing model calls to START a CodingAgent run; everything below
that door is internal to the run and never itself exposed as an LLM
chat tool.

Every tool is a ToolSpec: name, description, input schema, a risk/
destructive/read-only classification (used by approval.py -- the
policy gate never executes a tool without first reading these three
fields), and a handler. Registration is dynamic (`register()`), so
future capabilities -- STT, TTS, vision, Arduino, browser, memory --
become tools here without the agent LOOP (agent.py) changing at all;
the loop only ever knows "call a tool by name with these arguments",
never the concrete operations.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from ...runtime.log import log_event
except Exception:  # pragma: no cover -- see BLUEPRINT.md, Phase 1 finding #1
    def log_event(channel: str, message: str, level: str = "info") -> None:
        pass

# ------------------------------------------------------------------- risk
RISK_READ_ONLY = "read_only"   # cannot change anything -- list, read, search, status
RISK_LOW = "low"               # reversible, contained to the sandbox/repo workdir
RISK_MEDIUM = "medium"         # reversible but broader effect -- install dep, package
RISK_HIGH = "high"             # irreversible, or leaves the authorized scope
_RISKS = {RISK_READ_ONLY, RISK_LOW, RISK_MEDIUM, RISK_HIGH}


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Dict[str, Any]]
    input_schema: Dict[str, Any] = field(default_factory=dict)
    risk: str = RISK_LOW
    destructive: bool = False
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.risk not in _RISKS:
            raise ValueError(f"tool '{self.name}': unknown risk tier '{self.risk}'")
        if self.read_only and self.risk not in (RISK_READ_ONLY, RISK_LOW):
            raise ValueError(f"tool '{self.name}': read_only tools must be read_only/low risk")

    def invoke(self, **kwargs: Any) -> Dict[str, Any]:
        started = time.time()
        try:
            out = self.handler(**kwargs)
            if not isinstance(out, dict):
                out = {"output": str(out)}
            out.setdefault("ok", True)
        except Exception as exc:
            out = {"ok": False, "error": str(exc)}
            log_event("coding_agent", f"tool '{self.name}' raised: {exc}", level="warning")
        out["duration_ms"] = round((time.time() - started) * 1000, 1)
        out["tool"] = self.name
        return out

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema, "risk": self.risk,
                "destructive": self.destructive, "read_only": self.read_only}


class ToolRegistry:
    """Dynamic, inspectable, per-run tool belt.

    A fresh registry is built per CodingAgent run (see agent.py) rather
    than shared as a module-level singleton, because tools like
    repo_tools' file operations close over ONE repo's workdir -- a
    shared global registry would leak one task's filesystem access
    into another's.

    HOOKS (adapted from Claude Code's PreToolUse/PostToolUse hook
    concept -- see BLUEPRINT.md's source-completeness section): plain
    callables registered via on_before/on_after, run around every
    invoke(). A before-hook returning a dict with "block": True short-
    circuits the call (its "reason" becomes the error) -- this is how
    a future custom policy (rate limiting, a project-specific lint
    rule, an audit sink) plugs in without agent.py or approval.py
    changing at all.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._before_hooks: List[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = []
        self._after_hooks: List[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = []
        # CONCURRENCY SAFETY (2026-09-16): the ONE lock that makes
        # parallel workers (concurrency.py) safe against torn writes.
        # Read-only tools (read_only=True) skip it entirely -- research
        # genuinely overlaps; every mutating tool call across every
        # worker thread is serialized through this single lock, so two
        # workers can never write the same file (or any file) at the
        # same instant. This is what lets run_parallel_subtasks() be
        # real concurrency without becoming a race condition.
        self._write_lock = threading.Lock()

    def on_before_invoke(self, hook: Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]) -> None:
        self._before_hooks.append(hook)

    def on_after_invoke(self, hook: Callable[[str, Dict[str, Any], Dict[str, Any]], None]) -> None:
        self._after_hooks.append(hook)

    def register(self, spec: ToolSpec, *, overwrite: bool = False) -> None:
        if spec.name in self._tools and not overwrite:
            raise ValueError(f"tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        return sorted(self._tools.keys())

    def list_tools(self) -> List[Dict[str, Any]]:
        return [spec.describe() for spec in self._tools.values()]

    def invoke(self, name: str, **kwargs: Any) -> Dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error": f"unknown tool '{name}'", "tool": name,
                     "duration_ms": 0.0}
        for hook in self._before_hooks:
            try:
                verdict = hook(name, kwargs)
            except Exception as exc:
                log_event("coding_agent", f"before-hook raised: {exc}", level="warning")
                continue
            if isinstance(verdict, dict) and verdict.get("block"):
                return {"ok": False, "error": verdict.get("reason", "blocked by hook"),
                        "tool": name, "duration_ms": 0.0}
        if spec.read_only:
            result = spec.invoke(**kwargs)
        else:
            with self._write_lock:
                result = spec.invoke(**kwargs)
        for hook in self._after_hooks:
            try:
                hook(name, kwargs, result)
            except Exception as exc:
                log_event("coding_agent", f"after-hook raised: {exc}", level="warning")
        return result
