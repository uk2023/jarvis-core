from __future__ import annotations

"""CODING AGENT -- the loop itself (Phase 7), plus bounded concurrent
subtasks (Phase 7b, 2026-09-16).

    UNDERSTAND -> DISCOVER -> PLAN -> APPROVE -> EXECUTE -> OBSERVE
    -> VERIFY -> (FIX -> PLAN -> ... ) -> DONE / ARTIFACT

This is deliberately a SEPARATE class from
core/orchestration/task_loop.TaskLoop, not a rewrite of it --
TaskLoop already owns JARVIS's single-turn UNDERSTAND/PLAN/EXECUTE/
VERIFY/CONCLUDE loop for chat-scale work (KIND_CODE steps inside it
call brain.run_coding_task -> codebox.run_coding_session, a single
script). CodingAgent is what a KIND_CODE-equivalent step reaches for
when the work is REPO-scale.

JARVIS OWNS THE AGENT: the LLM (`generate`) is used ONLY to (a)
propose a plan as a list of tool calls and (b) propose a fix after a
failed verification. It never executes anything directly -- every
proposed call passes through approval.decide() before
ToolRegistry.invoke() runs it.

CONCURRENCY (2026-09-16): execution state that used to live on the
AGENT instance (`self._pending_plan`) now lives on the TASK
(`task.pending_plan`, see contracts.py) -- required so that
run_parallel_subtasks() can run several CodingTasks through the SAME
agent instance, on different threads, without one task's paused plan
corrupting another's. The two things that ARE still shared across
threads are deliberately shared: `self.registry` (its write lock is
what makes concurrent tool calls safe -- see tool_contract.py) and
`self._llm_limiter` (bounds concurrent/rate LLM calls -- see
concurrency.py). Subtasks may not themselves spawn further subtasks
(`_subtask_depth` guard below) -- unbounded recursive fan-out was an
explicit non-goal, not an oversight.
"""

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from ...runtime.log import log_event
except Exception:  # pragma: no cover -- degrade gracefully if core.runtime is ever unavailable
    def log_event(channel: str, message: str, level: str = "info") -> None:
        pass

from . import approval
from .concurrency import RateLimiter, WorkerPool, WorkerUnit
from .contracts import (
    CodingTask, ToolCall, ToolResult, VerificationResult,
    PLANNING, WAITING_APPROVAL, RUNNING, VERIFYING, FAILED, COMPLETED, BLOCKED,
    PHASE_UNDERSTAND, PHASE_DISCOVER, PHASE_PLAN, PHASE_APPROVE, PHASE_EXECUTE,
    PHASE_VERIFY, PHASE_DONE,
)
from .repo_tools import RepoWorkspace, build_registry
from .tool_contract import RISK_MEDIUM, ToolRegistry, ToolSpec

MAX_PLAN_CALLS_PER_ITERATION = 8
DISCOVERY_FILE_LIMIT = 80
MAX_SUBTASK_DEPTH = 1   # a subtask may not itself spawn subtasks


def _parse_json_list(raw: str) -> Optional[List[Dict[str, Any]]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I | re.M)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, list) else None
    except Exception:
        return None


class CodingAgent:
    """One instance per run. Holds the workspace + tool registry for
    exactly one top-level CodingTask (plus that task's fix iterations
    AND any subtasks spawned from it -- see run_subtask/run_parallel_subtasks)."""

    def __init__(self, generate: Callable, *, role: str = "user",
                 username: Optional[str] = None, is_verified: bool = False,
                 repo_path: Optional[str] = None, max_iterations: int = 6,
                 timeout: int = 30, extra_tools: Optional[List[Any]] = None,
                 llm_max_concurrent: int = 2, llm_min_interval_seconds: float = 0.8):
        self.generate = generate
        self.role = (role or "user").lower()
        self.username = username
        self.is_verified = bool(is_verified)
        self.max_iterations = max(1, min(int(max_iterations), 20))
        self._subtask_depth = 0

        # Shared across every thread that may call the LLM through this
        # agent (top-level run + any parallel subtasks) -- see
        # concurrency.py's docstring for why 0.8s matches task_loop.py's
        # own STEP_PACING_SECONDS rather than a new invented constant.
        self._llm_limiter = RateLimiter(max_concurrent=llm_max_concurrent,
                                         min_interval_seconds=llm_min_interval_seconds)

        if repo_path:
            self.workspace = RepoWorkspace(repo_path, timeout=timeout)
            self.scope_authorized = True   # existing, explicitly-named repo -- in scope
        else:
            self.workspace = RepoWorkspace(self._default_workdir(), timeout=timeout)
            self.scope_authorized = True   # a fresh sandbox the agent itself owns

        self.registry: ToolRegistry = build_registry(self.workspace)
        # LEARNED-TOOL REUSE: tools activated in a PREVIOUS run (see
        # companion_tools.activate_coding_tool) are carried in here by the
        # caller so this run doesn't rediscover the same capability.
        for spec in (extra_tools or []):
            try:
                self.registry.register(spec, overwrite=True)
            except Exception:
                pass

        # PLANNER-CALLABLE PARALLEL SUBTASKS (2026-09-16): exposed as a
        # tool so the PLAN phase can itself decide to fan out genuinely
        # independent work, not only a Python caller (codebase.py/
        # companion_tools.py). Bound by MAX_SUBTASK_DEPTH so a subtask's
        # own plan cannot request further subtasks.
        self.registry.register(ToolSpec(
            "spawn_parallel_subtasks",
            "Run several genuinely INDEPENDENT sub-objectives CONCURRENTLY (bounded, "
            "rate-limited, dependency-ordered). Argument: a list of objects "
            '{"id","objective","dependencies":[ids]}. Use ONLY when the sub-objectives '
            "truly do not depend on each other's output within a batch -- steps that must "
            "happen in order belong in the ordinary plan instead, not here.",
            self._spawn_parallel_subtasks_tool,
            risk=RISK_MEDIUM,
        ))

    def _default_workdir(self) -> str:
        try:
            from ..sandbox_policy import sandbox_dir_for
            import uuid
            return str(sandbox_dir_for(role=self.role, username=self.username,
                                        session_id="agent_" + uuid.uuid4().hex[:10]))
        except Exception:
            import tempfile
            return tempfile.mkdtemp(prefix="jarvis_coding_agent_")

    # -------------------------------------------------------------- LLM
    def _call_llm(self, instruction: str, context: str, max_tokens: int = 900) -> str:
        """Returns model text, or "" on any failure. Sets
        self._last_llm_error to the REASON so callers can report why
        nothing happened instead of a bare "no usable tool calls"."""
        self._last_llm_error = ""
        try:
            with self._llm_limiter:   # bounded concurrent + paced -- see concurrency.py
                raw = str(self.generate(
                    system_prompt=(
                        "You are the planning engine inside JARVIS's Coding Agent. "
                        + instruction
                    ),
                    # LEVEL: extended_thinking, NOT response_generation
                    # (fixed 2026-09-17, same bug as codebox.py's
                    # identical fix this turn -- see its comment). The
                    # per-level cap is 2 calls/turn; a coding-agent run
                    # needs one call for the initial plan PLUS one more
                    # per fix iteration, so it died on exactly its 2nd
                    # internal call every single time, independent of
                    # max_iterations, independent of which provider was
                    # configured -- this is what UK's "Repo-scale Coding
                    # Agent" tab was actually hitting.
                    user_input=context, max_tokens=max_tokens, level="extended_thinking",
                )).strip()
        except Exception as exc:
            self._last_llm_error = f"LLM call raised: {exc}"
            log_event("coding_agent", f"LLM call failed: {exc}", level="warning")
            return ""

        # generate_response() returns a DEGRADED-RESULT SENTINEL string
        # instead of raising when no provider answered (budget exhausted,
        # every key failed, local fallback off). Treating that sentence as
        # a plan is how UK's runs ended up reporting "Planner returned no
        # usable tool calls" for what was really "no model answered at
        # all" -- see llm_bridge.is_llm_unavailable's own comment.
        try:
            from ...orchestration.llm_bridge import is_llm_unavailable
        except Exception:
            is_llm_unavailable = lambda t: False  # noqa: E731
        if is_llm_unavailable(raw):
            self._last_llm_error = raw.strip("[]")
            log_event("coding_agent", f"planner got no model: {raw}", level="warning")
            return ""
        return raw

    # ------------------------------------------------------------ phases
    def _understand(self, task: CodingTask) -> None:
        task.set_phase(PHASE_UNDERSTAND)
        task.understanding = {"goal": task.objective, "done_when": [
            "the project's tests (or compile-check, if no tests exist) pass",
        ]}

    def _discover(self, task: CodingTask) -> str:
        task.set_phase(PHASE_DISCOVER)
        # Read-only filesystem walk -- safe to call from concurrent
        # subtask threads (see tool_contract.py: only MUTATING tool
        # calls are serialized; this bypasses the registry entirely
        # since it's inherently read-only).
        tree = self.workspace.list_tree(max_files=DISCOVERY_FILE_LIMIT)
        summary = "\n".join(tree.get("files", [])) if tree.get("ok") else f"(discovery failed: {tree.get('error')})"
        task.record(PHASE_DISCOVER, note=f"{tree.get('count', 0)} files discovered")
        return summary

    def _plan(self, task: CodingTask, discovery: str, failure_context: str = "") -> List[ToolCall]:
        task.set_phase(PHASE_PLAN)
        task.set_status(PLANNING if not failure_context else RUNNING)

        tool_list = "\n".join(f"- {t['name']}: {t['description']}" for t in self.registry.list_tools())
        instruction = (
            "Propose the NEXT tool calls needed to complete the objective -- not a description, "
            "actual calls. Return ONLY a JSON array, max "
            f"{MAX_PLAN_CALLS_PER_ITERATION} items: "
            '[{"tool_name": "...", "arguments": {...}, "reason": "..."}]. '
            f"Available tools:\n{tool_list}"
        )
        context = (
            f"Objective: {task.objective}\n\n"
            f"Project files (partial):\n{discovery}\n"
        )
        if failure_context:
            context += f"\nPrevious verification FAILED:\n{failure_context}\n\nPropose calls that fix this."

        raw = self._call_llm(instruction, context)
        parsed = _parse_json_list(raw) or []
        calls: List[ToolCall] = []
        for item in parsed[:MAX_PLAN_CALLS_PER_ITERATION]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool_name", "")).strip()
            if not name or not self.registry.has(name):
                continue
            args = item.get("arguments") or {}
            if not isinstance(args, dict):
                continue
            calls.append(ToolCall(tool_name=name, arguments=args,
                                   reason=str(item.get("reason", ""))[:200]))
        task.plan = calls
        if not calls:
            why = getattr(self, "_last_llm_error", "") or "planner returned nothing usable"
            task.add_error(f"No plan produced ({'fix' if failure_context else 'initial'}): {why}")
        return calls

    def _execute_plan(self, task: CodingTask) -> bool:
        """Executes task.pending_plan (falling back to task.plan) in
        order, gated by approval.decide() per call. Returns True if
        execution should continue to verification, False if the task
        is now WAITING_APPROVAL (caller must resume() it). All state
        lives on `task`, not `self` -- see module docstring."""
        task.set_phase(PHASE_EXECUTE)
        task.set_status(RUNNING)
        for call in list(task.pending_plan or task.plan):
            spec = self.registry.get(call.tool_name)
            target = call.arguments.get("path") or call.arguments.get("sub_path") or \
                call.arguments.get("command") or ""
            decision = approval.decide(
                tool_name=call.tool_name, risk=spec.risk if spec else "high",
                role=task.role, destructive=(spec.destructive if spec else True),
                target=str(target), scope_authorized=self.scope_authorized,
            )
            log_event("coding_agent", approval.audit_line(task.id, call, decision), level="info")

            if decision["decision"] == approval.DENY:
                result = ToolResult(call_id=call.id, ok=False, skipped=True,
                                     skip_reason=decision["reason"])
                task.record(PHASE_EXECUTE, tool_call=call, result=result)
                task.add_error(f"denied: {call.tool_name} -- {decision['reason']}")
                continue

            if decision["decision"] == approval.ASK_USER:
                idx = task.plan.index(call) if call in task.plan else 0
                task.pending_plan = task.plan[idx:]
                task.pending_approval = {"call": call.as_dict(), "reason": decision["reason"]}
                task.set_status(WAITING_APPROVAL)
                task.set_phase(PHASE_APPROVE)
                task.record(PHASE_APPROVE, tool_call=call, note=decision["reason"])
                return False

            out = self.registry.invoke(call.tool_name, **call.arguments)
            result = ToolResult(call_id=call.id, ok=bool(out.get("ok")),
                                 output=out.get("output") or out.get("diff") or out.get("error") or "",
                                 detail=out, duration_ms=out.get("duration_ms", 0.0))
            task.record(PHASE_EXECUTE, tool_call=call, result=result)
            if not result.ok:
                task.add_error(f"{call.tool_name} failed: {result.output}")

        task.pending_plan = []
        return True

    def resume(self, task: CodingTask, *, approve: bool) -> CodingTask:
        """Continues a WAITING_APPROVAL task after UK answers yes/no to
        the single call that triggered the gate."""
        if task.status != WAITING_APPROVAL or not task.pending_plan:
            task.add_error("resume() called but task was not waiting on approval")
            return task
        call = task.pending_plan[0]
        if approve:
            out = self.registry.invoke(call.tool_name, **call.arguments)
            result = ToolResult(call_id=call.id, ok=bool(out.get("ok")),
                                 output=out.get("output") or out.get("diff") or out.get("error") or "",
                                 detail=out, duration_ms=out.get("duration_ms", 0.0))
            task.record(PHASE_EXECUTE, tool_call=call, result=result, note="approved by UK")
        else:
            result = ToolResult(call_id=call.id, ok=False, skipped=True, skip_reason="denied by UK")
            task.record(PHASE_EXECUTE, tool_call=call, result=result, note="denied by UK")
        task.pending_plan = task.pending_plan[1:]
        task.pending_approval = None
        if task.pending_plan:
            task.plan = task.pending_plan
            if not self._execute_plan(task):
                return task   # hit ANOTHER approval gate
        return self._verify_and_continue(task)

    def _verify(self, task: CodingTask) -> VerificationResult:
        task.set_phase(PHASE_VERIFY)
        task.set_status(VERIFYING)
        out = self.workspace.run_tests()
        vr = VerificationResult(method=out.get("method", "unknown"), passed=bool(out.get("ok")),
                                 output=out.get("output") or out.get("error") or "")
        task.verifications.append(vr)
        task.record(PHASE_VERIFY, note=f"{vr.method}: {'passed' if vr.passed else 'failed'}")
        return vr

    def _verify_and_continue(self, task: CodingTask) -> CodingTask:
        vr = self._verify(task)

        # NOTHING-HAPPENED GUARD (2026-09-17, from UK's screenshot showing
        # "[COMPLETED] ... 0/0 tool calls ok" with "Planner returned no
        # usable tool calls" sitting in the SAME panel). run_tests()
        # honestly reports method "none_available" -> ok=True when there
        # is nothing to test, which is right on its own terms; but an
        # empty workspace passing a vacuous check is NOT a completed
        # objective, and saying COMPLETED there is the exact "kar diya"
        # dishonesty UK has flagged before. A run that executed no tool
        # and wrote no file is BLOCKED, whatever the verifier says.
        executed = sum(1 for o in task.observations
                        if o.result is not None and o.result.ok and not o.result.skipped)
        if executed == 0 and vr.method == "none_available":
            task.set_status(BLOCKED)
            task.set_phase(PHASE_DONE)
            why = "; ".join(task.errors[-2:]) or "planner produced no runnable steps"
            task.result_summary = (
                f"Kuch nahi hua -- koi tool chala hi nahi, isliye koi file nahi bani. "
                f"Wajah: {why}. (Verification skip hui: project mein test karne ko kuch tha hi nahi.)"
            )
            log_event("coding_agent", f"task {task.id} blocked: {why}", level="warning")
            return task

        if vr.passed:
            task.set_status(COMPLETED)
            task.set_phase(PHASE_DONE)
            task.result_summary = task.summary()
        elif task.iteration >= task.max_iterations:
            task.set_status(FAILED)
            task.result_summary = f"Max iterations ({task.max_iterations}) reached; last verification: {vr.method} failed."
        else:
            self._iterate(task)
        return task

    def _iterate(self, task: CodingTask) -> None:
        """One more PLAN(fix)->EXECUTE->VERIFY cycle."""
        task.iteration += 1
        failure = task.verifications[-1].output if task.verifications else ""
        discovery = self._discover(task)
        self._plan(task, discovery, failure_context=failure)
        task.pending_plan = list(task.plan)
        if not self._execute_plan(task):
            return   # now WAITING_APPROVAL; caller must resume()
        self._verify_and_continue(task)

    # ---------------------------------------------------------- subtasks
    def run_subtask(self, objective: str, *, parent: CodingTask) -> CodingTask:
        """Runs a CHILD CodingTask against the SAME workspace/registry as
        `parent`. Thread-safe: all execution state lives on `child`, not
        on `self` (see module docstring), so this may be called from
        several threads at once for DIFFERENT children of the same
        parent -- see run_parallel_subtasks below."""
        child = CodingTask(objective=objective, role=self.role,
                            repo_path=str(self.workspace.root), parent_id=parent.id,
                            max_iterations=max(1, self.max_iterations))
        parent.subtasks.append(child.id)
        child.set_status(RUNNING)
        try:
            self._understand(child)
            discovery = self._discover(child)
            child.iteration = 1
            self._plan(child, discovery)
            child.pending_plan = list(child.plan)
            if not self._execute_plan(child):
                return child   # child itself now WAITING_APPROVAL
            self._verify_and_continue(child)
        except Exception as exc:
            child.add_error(f"subtask crashed: {exc}")
            child.set_status(FAILED)
        return child

    def run_parallel_subtasks(self, objectives: List[Dict[str, Any]], *, parent: CodingTask,
                                max_workers: int = 3, timeout: float = 120.0,
                                max_retries: int = 1) -> Dict[str, CodingTask]:
        """Runs several genuinely independent subtasks CONCURRENTLY --
        bounded by max_workers, dependency-ordered, rate-limited on LLM
        calls (self._llm_limiter, shared with the top-level run), and
        SAFE against concurrent file writes because every mutating tool
        call is serialized behind ToolRegistry's own lock (research/
        read-only tools are NOT locked, so they genuinely overlap).

        JARVIS -- this method, plain Python -- decides scheduling. The
        LLM only ever proposed WHAT the sub-objectives are (via the
        spawn_parallel_subtasks tool, or a direct caller like
        codebase.py) and which ones depend on which; it never controls
        WHEN anything runs.

        `objectives`: [{"id": str, "objective": str, "dependencies": [id, ...]}]
        Returns {id: CodingTask} for every objective (failed/skipped
        ones still get a CodingTask, with the failure recorded in it).
        """
        if self._subtask_depth >= MAX_SUBTASK_DEPTH:
            raise RuntimeError(f"subtask nesting limit ({MAX_SUBTASK_DEPTH}) reached -- "
                                f"a subtask may not itself spawn subtasks")
        self._subtask_depth += 1
        try:
            units = []
            for obj in objectives:
                oid = str(obj["id"])

                def _make_fn(objective_text: str) -> Callable[[], CodingTask]:
                    def _run() -> CodingTask:
                        child = self.run_subtask(objective_text, parent=parent)
                        if child.status == FAILED:
                            raise RuntimeError(child.result_summary or "subtask failed")
                        return child
                    return _run

                units.append(WorkerUnit(id=oid, fn=_make_fn(obj["objective"]),
                                         dependencies=[str(d) for d in obj.get("dependencies", [])],
                                         timeout=timeout, max_retries=max_retries))

            pool = WorkerPool(max_workers=max_workers)
            worker_results = pool.run(units)

            tasks: Dict[str, CodingTask] = {}
            for oid, wr in worker_results.items():
                if wr.ok and isinstance(wr.value, CodingTask):
                    tasks[oid] = wr.value
                else:
                    failed = CodingTask(objective=next((o["objective"] for o in objectives if str(o["id"]) == oid), oid),
                                         role=self.role, repo_path=str(self.workspace.root),
                                         parent_id=parent.id)
                    failed.set_status(FAILED)
                    failed.add_error(wr.error or "subtask did not complete")
                    failed.result_summary = wr.error
                    tasks[oid] = failed
                    parent.subtasks.append(failed.id)
            return tasks
        finally:
            self._subtask_depth -= 1

    def _spawn_parallel_subtasks_tool(self, objectives: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The registry-tool wrapper for run_parallel_subtasks -- see its
        registration in __init__. `_current_task` is set by run()
        immediately before _execute_plan(), which is the only place a
        tool call (including this one) can originate from."""
        parent = getattr(self, "_current_task", None)
        if parent is None:
            return {"ok": False, "error": "no active task to attach subtasks to"}
        try:
            results = self.run_parallel_subtasks(objectives, parent=parent)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": all(t.status == COMPLETED for t in results.values()),
            "subtasks": {oid: t.summary() for oid, t in results.items()},
        }

    # -------------------------------------------------------------- run
    def run(self, objective: str) -> CodingTask:
        task = CodingTask(objective=objective, role=self.role,
                           repo_path=str(self.workspace.root),
                           max_iterations=self.max_iterations)
        self._current_task = task   # see _spawn_parallel_subtasks_tool
        task.set_status(RUNNING)
        try:
            self._understand(task)
            discovery = self._discover(task)
            task.iteration = 1
            self._plan(task, discovery)
            task.pending_plan = list(task.plan)
            if not self._execute_plan(task):
                return task   # WAITING_APPROVAL -- caller must resume()
            self._verify_and_continue(task)
        except Exception as exc:
            task.add_error(f"agent run crashed: {exc}")
            task.set_status(FAILED)
            log_event("coding_agent", f"task {task.id} crashed: {exc}", level="error")
        log_event("coding_agent", task.summary(), level="info")
        return task
