from __future__ import annotations

"""CODING AGENT -- task & tool-call contracts (Phase 3).

This is the data model for the autonomous coding agent required by
UK's merge request (2026-09-16): a real, stateful, iterative
coding-agent subsystem, not a single LLM prompt.

Deliberately separate from core/contracts/schemas.py, which defines
the PERCEIVE->...->EVOLVE pipeline's dict-shaped layer boundaries.
CodingTask below is JARVIS-internal state for ONE coding-agent run --
it never crosses those pipeline boundaries directly; a run is
launched as a normal WRITE_TOOL call (see tool_registry.py's
"run_coding_agent") and its result re-enters the pipeline the same
way run_coding_task's result already does.

Nothing here talks to the LLM, the filesystem, or a subprocess --
that is tool_contract.py (the tool belt), approval.py (the policy
gate) and agent.py (the loop that ties them together). This module
only defines what a task and a step ARE.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------- status
PENDING = "PENDING"
PLANNING = "PLANNING"
WAITING_APPROVAL = "WAITING_APPROVAL"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
COMPLETED = "COMPLETED"
CANCELLED = "CANCELLED"

STATUSES = {PENDING, PLANNING, WAITING_APPROVAL, RUNNING, VERIFYING,
            BLOCKED, FAILED, COMPLETED, CANCELLED}

# Terminal states -- once here, a task is over; only a fresh task continues it.
TERMINAL_STATUSES = {FAILED, COMPLETED, CANCELLED}

# Lifecycle phase (distinct from status -- status is "how is it going",
# phase is "where in the PLAN->EXECUTE->OBSERVE->VERIFY->FIX loop are we").
PHASE_UNDERSTAND = "understand"
PHASE_DISCOVER = "discover"
PHASE_DECOMPOSE = "decompose"
PHASE_PLAN = "plan"
PHASE_APPROVE = "approve"
PHASE_EXECUTE = "execute"
PHASE_OBSERVE = "observe"
PHASE_VERIFY = "verify"
PHASE_FIX = "fix"
PHASE_PACKAGE = "package"
PHASE_DONE = "done"


class InvalidStatus(ValueError):
    pass


@dataclass
class ToolCall:
    """One proposed invocation of a registered tool."""
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    reason: str = ""              # why the planner/fixer wants this call

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "tool_name": self.tool_name,
                "arguments": self.arguments, "reason": self.reason}


@dataclass
class ToolResult:
    """What actually happened when a ToolCall was (or was not) run."""
    call_id: str
    ok: bool
    output: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    skipped: bool = False          # denied/held by the approval gate
    skip_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"call_id": self.call_id, "ok": self.ok,
                "output": (self.output or "")[:4000], "detail": self.detail,
                "duration_ms": round(self.duration_ms, 1),
                "skipped": self.skipped, "skip_reason": self.skip_reason}


@dataclass
class Observation:
    """One entry in the task's audit trail -- a tool call plus its result."""
    step_index: int
    phase: str
    tool_call: Optional[ToolCall] = None
    result: Optional[ToolResult] = None
    note: str = ""
    at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index, "phase": self.phase,
            "tool_call": self.tool_call.as_dict() if self.tool_call else None,
            "result": self.result.as_dict() if self.result else None,
            "note": self.note, "at": self.at,
        }


@dataclass
class VerificationResult:
    method: str                    # e.g. "pytest", "py_compile", "none_available"
    passed: bool
    output: str = ""
    at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {"method": self.method, "passed": self.passed,
                "output": (self.output or "")[:4000], "at": self.at}


@dataclass
class CodingTask:
    """A single coding-agent run. One task may spawn subtasks (their ids
    live in `subtasks`); a subtask's own CodingTask carries `parent_id`.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: Optional[str] = None
    objective: str = ""
    role: str = "user"
    repo_path: str = ""
    status: str = PENDING
    phase: str = PHASE_UNDERSTAND
    understanding: Dict[str, Any] = field(default_factory=dict)
    plan: List[ToolCall] = field(default_factory=list)
    subtasks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    observations: List[Observation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    verifications: List[VerificationResult] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 6
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result_summary: Optional[str] = None
    pending_approval: Optional[Dict[str, Any]] = None  # set when WAITING_APPROVAL
    pending_plan: List[ToolCall] = field(default_factory=list)  # remaining calls after a gate/iteration -- lives on the TASK (not the agent) so concurrent subtasks (see concurrency.py) never share this mutable state

    # ------------------------------------------------------------ mutators
    def set_status(self, status: str) -> None:
        if status not in STATUSES:
            raise InvalidStatus(f"'{status}' is not a valid CodingTask status")
        if self.status in TERMINAL_STATUSES and status not in TERMINAL_STATUSES:
            raise InvalidStatus(f"task {self.id} is already terminal ({self.status}); "
                                 f"start a new task instead of reviving it")
        self.status = status
        self.updated_at = time.time()

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.updated_at = time.time()

    def record(self, phase: str, *, tool_call: Optional[ToolCall] = None,
               result: Optional[ToolResult] = None, note: str = "") -> Observation:
        obs = Observation(step_index=len(self.observations) + 1, phase=phase,
                           tool_call=tool_call, result=result, note=note)
        self.observations.append(obs)
        self.updated_at = time.time()
        return obs

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.updated_at = time.time()

    # -------------------------------------------------------------- views
    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "parent_id": self.parent_id, "objective": self.objective,
            "role": self.role, "repo_path": self.repo_path,
            "status": self.status, "phase": self.phase,
            "understanding": self.understanding,
            "plan": [c.as_dict() for c in self.plan],
            "subtasks": self.subtasks, "dependencies": self.dependencies,
            "observations": [o.as_dict() for o in self.observations],
            "errors": self.errors,
            "verifications": [v.as_dict() for v in self.verifications],
            "artifacts": self.artifacts,
            "iteration": self.iteration, "max_iterations": self.max_iterations,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "result_summary": self.result_summary,
            "pending_approval": self.pending_approval,
        }

    def summary(self) -> str:
        ok_steps = sum(1 for o in self.observations if o.result and o.result.ok)
        total_steps = sum(1 for o in self.observations if o.result is not None)
        return (f"[{self.status}] {self.objective[:80]!r} -- "
                f"{ok_steps}/{total_steps} tool calls ok, "
                f"{len(self.verifications)} verification(s), "
                f"iteration {self.iteration}/{self.max_iterations}")
