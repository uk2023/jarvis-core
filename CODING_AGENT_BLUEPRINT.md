# JARVIS Coding Agent -- Blueprint & Phase Status
_2026-09-16, in response to UK's coding-agent merge request. Read this before continuing -- say "continue" and the next turn picks up from "PENDING" below._

## PHASE 1 -- INSPECTION FINDINGS (read this first, action needed from UK)

### ✅ Finding #1 -- RESOLVED (2026-09-16, `runtime_v1_tar.gz` supplied)
`core/runtime/` was genuinely absent from the original export, confirmed
by a full-archive search (no `.git` history to recover from either).
UK supplied the missing package separately; it's now integrated at
`core/runtime/` (`log.py`, `trace_log.py`, `state_bus.py`,
`memory_limits.py`, `runtime_monitor.py`, `diagnostics.py`,
`chat_log.py`, plus `identity_trace.py`, `voice.py`,
`session_registry.py`, `terminal_resilience.py`, `resource_monitor.py`
-- more than the 7 originally missing). **Everything below this line
is now tested against the REAL runtime, not a stub**: `core.skills.coding_agent`,
`core.skills.self_extension`, and `core.evolution.self_evolution` all
import cleanly, and `log_event()` calls are confirmed actually
writing to `logs/jarvis_runtime.log` (real file, real rotating
handler, verified by inspecting its contents after a live run).

All NEW code in this pass (`core/skills/coding_agent/`) degrades
gracefully if `runtime.log` is missing (`try/except` -> a no-op
logger), so it is independently testable and doesn't add a new crash
point -- but it does not fix the underlying gap.

### Existing architecture map (what's already there, and NOT duplicated)
- **`core/orchestration/task_loop.py`** -- the ONE existing multi-step
  loop: UNDERSTAND -> PLAN -> EXECUTE -> VERIFY -> CONCLUDE, chat-turn
  scale. `KIND_CODE` steps call `brain.run_coding_task()`.
- **`core/skills/codebox.py`** -- sandboxed execution for ONE script:
  write -> run -> read the traceback -> fix -> re-run
  (`run_coding_session`). Per-role sandbox dirs via `sandbox_policy.py`.
  5-layer QA (syntax/danger-scan/deps/isolated-exec/resource) via
  `core/evolution/self_evolution.run_qa`. **This already IS a coding
  agent for single-script tasks and is left exactly as-is.**
- **`core/orchestration/tool_registry.py`** -- the LLM-facing
  function-calling registry (Groq tool-use) for ordinary chat tools.
  `run_coding_task` was already a WRITE_TOOL here.
- **`core/orchestration/companion_tools.py`** -- mixin holding the
  Brain methods those tools dispatch to (`Brain(CompanionToolsMixin)`
  in brain.py).
- **`core/skills/sandbox_policy.py`** -- per-role (owner/admin/user)
  sandbox directories + the package-install allowlist.

### The actual gap (what UK's spec asked for that didn't exist)
Everything above operates on **one script at a time**. Nothing could:
inspect an existing multi-file repo, edit several files in one task,
run the project's real test suite, decide APPROVE/ASK_USER/DENY per
operation, or package a finished project as zip/tar.gz. That's what
`core/skills/coding_agent/` (new, this pass) adds.

---

## ARCHITECTURE -- WHERE THE NEW SUBSYSTEM SITS

```
Jarvis Brain (unchanged)
  |
  v
tool_registry.py: "run_coding_agent" (NEW WRITE_TOOL, alongside run_coding_task)
  |
  v
companion_tools.py: Brain.run_coding_agent() / .resume_coding_agent()  (NEW methods)
  |
  v
core/skills/coding_agent/   <-- NEW PACKAGE, this pass
  contracts.py      CodingTask, ToolCall, ToolResult, Observation, VerificationResult
  tool_contract.py  ToolSpec, ToolRegistry (dynamic, extensible)
  approval.py       decide() -> APPROVE / ASK_USER / DENY
  repo_tools.py     RepoWorkspace + concrete tools (list_tree, read/write/patch,
                     search_code, run_command, git_status/commit, run_tests)
  packaging.py      package_project() -> zip/tar.gz, secret-file exclusion
  agent.py          CodingAgent -- the PLAN->APPROVE->EXECUTE->OBSERVE->VERIFY->FIX loop
```

`task_loop.py` is **not modified**. It remains JARVIS's chat-turn loop.
The two are siblings: task_loop's `KIND_CODE` step is chat-scale
(one script); `run_coding_agent` is repo-scale. A future, cleaner
integration (Phase 10, still pending) is for `task_loop._run_code_step`
to detect "this needs the repo agent" and delegate to
`brain.run_coding_agent()` instead of `run_coding_task()` -- not
implemented yet, flagged below.

`core/orchestration/tool_registry.py` (LLM chat-tool registry) and
`core/skills/coding_agent/tool_contract.py` (the agent's OWN internal
tool belt) are two different, correctly-separate things that share a
name coincidentally. Only `run_coding_agent`/`resume_coding_agent`
cross between them.

---

## HOW THE APPROVAL GATE WORKS (plain language)

Every tool call the agent wants to make gets a risk tag when it's
registered (`read_only` / `low` / `medium` / `high`) plus a
destructive flag. Before it runs, `approval.decide()` checks, in
order:
1. **Looks like a secret** (`.env`, `*credential*`, `*.pem`, ...)? -> **DENY**, always, no exceptions.
2. **Named always-ask op** (delete, git commit, force-push, DB drop, security config) or **high risk**? -> **ASK_USER**, task pauses (`status=WAITING_APPROVAL`), UK sees exactly which call and why, answers yes/no, agent continues from there via `resume_coding_agent()`.
3. **Outside the authorized project folder**? -> **ASK_USER**.
4. **Read-only / low risk** (list, read, search, write inside sandbox, run tests)? -> **APPROVE**, silently, no interruption.
5. **Medium risk** (arbitrary shell command, dependency install)? -> APPROVE for owner/co-owner/admin, ASK_USER for a plain user.

Nothing is ever a blanket yes or a blanket no -- it's per call, per
tool, per role.

---

## MULTI-WORKER PARALLEL FLOW (UK's ask: research/edit/verify/fix/git/registry workers)

Implemented as **phases of ONE agent loop**, not six separate LLM
instances -- per your own spec ("do not unnecessarily create six
separate agents if one can safely perform the task"). The
correspondence, so this can become real separate workers later
without a redesign:

| Your worker | Current phase in `agent.py` |
|---|---|
| Worker A (research) | `_discover()` -- `list_tree`/`search_code` |
| Worker B (editing) | `_execute_plan()` -- `write_file`/`apply_patch` |
| Worker C (verifying) | `_verify()` -- `run_tests()` |
| Worker D (fixing) | `_iterate()` -- re-plans with failure context |
| Worker E (git control) | `repo_tools.RepoWorkspace.git*` -- gated `high` risk |
| Worker F (tool registry, after sandbox test) | `ToolRegistry.register()` -- already dynamic; a tool proven in sandbox can be registered at runtime with no other code change |

Each phase is already its own method with its own inputs/outputs, so
splitting any one into a real parallel worker later is additive, not
a rewrite.

---

## WHAT'S DONE -- ACROSS ALL PASSES (verified against the REAL runtime as of this turn)

**Pass 1** (Phases 2/3/5/6/7/9 -- full task lifecycle, plan/execute/verify/fix
loop, approval gate, packaging, tool_registry.py + companion_tools.py wiring)
-- all re-confirmed this turn against the real `core/runtime/`, not the stub
harness used when it was first built. No regressions.

**Pass 2, this turn:**
- ✅ **`core/runtime/` integrated** (see Finding #1 above) -- `core.skills.coding_agent`,
  `core.skills.self_extension`, `core.evolution.self_evolution` all import
  cleanly against it; `log_event()` confirmed writing real log lines to
  `logs/jarvis_runtime.log`.
- ✅ **Two import-path bugs fixed** in `repo_tools.py` -- it was silently
  NOT reusing `codebox.py`'s refused-command list or 5-layer QA (wrong
  relative-import depth, `.codebox` instead of `..codebox`), falling back
  to its own private copy instead. Fixed; reconfirmed live that the refusal
  message and QA layers now genuinely come from `codebox.py`.
- ✅ **CodeBox reuse, live-tested**: new `run_python_qa` tool constructs a
  real `codebox.CodeBox`, points its `workdir` at the coding agent's OWN
  workspace (instead of a throwaway sandbox), and runs the SAME 5-layer QA
  pipeline. Confirmed all 5 layers green on a real snippet.
- ✅ **Self-extension bridge, fully reused, fully tested end-to-end**:
  new `propose_new_tool` agent-tool -> `self_evolution.propose_feature`
  (existing, unmodified) -> QA passes -> draft saved -> `decide_proposal`
  (existing, unmodified) -> new `self_extension.activate_tool` (the ONE
  genuinely new piece -- nothing else in JARVIS turned an approved draft
  into a live callable) -> registered into the run's `ToolRegistry` ->
  invoked successfully. Full chain run live: `double_it(21) == 42`.
- ✅ **Skill-learning reuse, tested against the REAL `LearningCoordinator`/
  `SkillLearner`/`SkillRegistry`** (not stubs): 3 simulated successful
  `coding_agent_run` experiences through `learning.learn()` -> a real skill
  proposal appeared exactly on the 3rd, matching `SkillLearner`'s own
  repetition threshold. No new learning logic -- `self_extension.record_run_as_experience()`
  only shapes a `CodingTask` into the dict `learn()` already expects.
- ✅ **Tool-reuse across runs**: tools activated via `activate_coding_tool`
  are now kept on the Brain instance and re-injected into the NEXT
  `run_coding_agent()` call's fresh `ToolRegistry` -- a tool created once
  doesn't need rediscovering.
- ✅ **CLI wiring, syntax-checked**: `/coding_agent <objective>` and
  `/approve_coding_step yes|no` added to `cli.py`, following its existing
  command pattern exactly.
- ✅ **`codebase.py`** -- standalone terminal REPL, live-tested (`/help`,
  `/tools`, running an objective, `/status`, `/trace` all confirmed
  working end to end against the real `core.orchestration.llm_bridge.HybridLLMBridge`).
  With no reachable LLM provider in this sandbox (no network), it degrades
  exactly as it should: an honest "no usable tool calls" rather than a
  fabricated result -- confirming the honesty behaviour holds even from
  this new entry point, not just from `cli.py`.
- ✅ **Hooks** (`ToolRegistry.on_before_invoke`/`on_after_invoke`) -- adapted
  from Claude Code's PreToolUse/PostToolUse concept (see comparison table
  below). Wired into `invoke()`; a before-hook can block a call with its
  own reason, independent of `approval.py`.
- ✅ **Subtasks** (`CodingAgent.run_subtask`) -- a tracked child `CodingTask`
  (parent_id, appears in `parent.subtasks`) sharing the SAME workspace/
  registry. Deliberately sequential -- see the design note below.

---

## SOURCE COMPLETENESS -- vs. the supplied Claude Code source

Requested comparison: integrated / adapted differently / missing /
intentionally unused and why. The supplied archive is almost entirely
the **React/Ink terminal UI** (`components/`, `coordinator/`) plus some
TypeScript service glue -- not a portable backend agent core in the
sense JARVIS needs, so most of what's below is CONCEPT-level adaptation
into JARVIS's own Python, never code copied across.

| Claude Code concept (source path) | Status in JARVIS |
|---|---|
| Per-operation-type permission dialogs (`components/permissions/{Bash,FileEdit,FileWrite,Filesystem,WebFetch,Skill,Sandbox}PermissionRequest`) | **Integrated, adapted**: `approval.py`'s `decide()` gates by tool name + risk tier, matching the same per-operation-type granularity (write vs patch vs command vs git vs delete each carry their own risk/destructive flags in `repo_tools.build_registry`). |
| `PermissionRuleExplanation` (why a permission is needed) | **Integrated**: every `decide()` result carries a `reason` string; surfaced verbatim in `_format_coding_agent_result`/`codebase.py`'s `_format_task`. |
| `EnterPlanMode`/`ExitPlanMode` | **Integrated, differently**: JARVIS's loop always plans before executing (`PHASE_PLAN` before `PHASE_EXECUTE`) rather than a toggle-able mode -- there is no "skip planning" path, so a separate mode switch wasn't needed. |
| Hooks (`components/hooks/*`, pre/post tool use) | **Integrated this turn**: `ToolRegistry.on_before_invoke`/`on_after_invoke` (see above). Config UI (`HooksConfigMenu.tsx` equivalent) not built -- no JARVIS UI surface asked for it yet. |
| `coordinator/coordinatorMode.ts`, `TeamCreateTool`/`TeamDeleteTool`/`SendMessageTool` (spawning concurrent worker sub-agents) | **Adapted, NOT as concurrent workers**: `CodingAgent.run_subtask()` gives a tracked child task, but runs it sequentially. **Intentionally unused**: true concurrent LLM callers need verified rate-limit headroom on JARVIS's configured provider, which nothing in this codebase currently confirms (see `tool_registry.py`'s own `STEP_PACING_SECONDS` rationale in `task_loop.py` -- concurrent calls are the exact failure mode that pacing exists to prevent). Flagged as a future upgrade, not silently dropped. |
| `SandboxPermissionRequest`, sandbox config tabs (`components/sandbox/*`) | **Already existed in JARVIS, reused as-is**: `sandbox_policy.py`'s per-role sandbox dirs + package-install allowlist predate this work and were not duplicated. |
| Skills system (`components/skills/*`, `SkillPermissionRequest`) | **Integrated via JARVIS's OWN pre-existing mechanism**: `SkillRegistry`/`SkillLearner`/`LearningCoordinator`, not a new one -- see the self-extension section above. |
| Structured diff rendering (`components/StructuredDiff`, `HighlightedCode`) | **Missing** -- `repo_tools.apply_patch` returns a unified diff string but nothing renders it with syntax highlighting; `codebase.py`'s `/trace` prints it as plain text. Low-cost future addition if UK wants it. |
| `AgentTool`, sub-agent spawning as an LLM-callable tool | **Missing on purpose, for now**: `run_subtask` exists as a Python method but is not exposed as a tool the PLANNER can call mid-plan (recursion/budget risk not yet reasoned through) -- reachable only from `codebase.py`'s `/subtask` or direct Python calls. |
| `ComputerUseApproval`, `NotebookEditPermissionRequest`, `PowerShellPermissionRequest` | **Not applicable** -- no computer-use, notebook, or Windows/PowerShell surface exists in JARVIS (Android/Termux). |
| Analytics/telemetry (`services/analytics/*`, Statsig feature gates) | **Intentionally unused** -- proprietary Anthropic service dependencies; JARVIS's own `log_event`/`trace_log` cover the equivalent observability need without a third-party service. |
| `WorkerBadge`/`WorkerPendingPermission` UI | **Missing (UI only)** -- no JARVIS web_frontend panel yet shows a coding-agent approval pending state. The DATA (`task.pending_approval`) is already there for a future panel to render. |

---

## PENDING -- say "continue" for these

- **Context system** (was Phase 4): planner context is still a flat file
  list (`list_tree`, capped at 80 files) + last failure output. No
  symbol/import/call-graph awareness, no git-diff-aware context.
- **`task_loop.py` delegation**: chat-scale (`KIND_CODE` -> `run_coding_task`)
  and repo-scale (`run_coding_agent`) are both reachable as LLM tools today
  (the model itself picks), but `task_loop.py` has no explicit
  "this needs the repo agent" detection of its own -- not necessarily
  needed if tool-choice already covers it; worth confirming against real
  usage rather than guessing.
- **Live LLM verification**: everything above is proven with a
  deterministic fake `generate` (Pass 1) and, this pass, the real
  `HybridLLMBridge` wiring -- but not a real provider round-trip, since
  this container has no network. Needs a run on your device to confirm
  actual plan quality.
- **pytest specifically**: `run_tests()`'s pytest path is written and
  auto-detected but only its `py_compile` fallback has been exercised
  live here (no network to install pytest in this sandbox). Should just
  work on your device.
- **Structured diff rendering**, **planner-callable subtask tool**,
  **web_frontend approval panel** -- see comparison table above, all
  flagged as genuine gaps rather than silently dropped.

---

## CONCURRENT WORKERS -- bounded, dependency-aware, rate-limit-safe (2026-09-16)

New: `core/skills/coding_agent/concurrency.py` (`RateLimiter`, `WorkerPool`,
`WorkerUnit`), plus a write-lock added to `ToolRegistry` (`tool_contract.py`)
and a refactor of execution state from the AGENT instance onto the TASK
(`CodingTask.pending_plan`) so concurrent subtasks can't corrupt each
other's paused-approval state.

**How it's actually safe, not just described as safe:**
- **Dependency ordering**: `WorkerPool.run()` executes in topological
  batches -- a unit only becomes eligible once every dependency has
  SUCCEEDED; a unit whose dependency failed is recorded as skipped, never
  run; an unresolvable cycle fails explicitly instead of hanging. Verified
  live: objectives A and B (no deps) ran concurrently, C (depends on A,B)
  only started after both finished.
- **Rate-limit safety**: `RateLimiter` bounds both concurrent LLM calls
  AND minimum spacing between them (default 0.8s -- the SAME number
  `task_loop.py` already uses for `STEP_PACING_SECONDS`, reused not
  reinvented), shared across every worker thread on one `CodingAgent`.
  Verified live: 3 calls under `max_concurrent=2, min_interval=0.3s` paced
  at exactly 0.3s apart.
- **Write safety**: `ToolRegistry` now holds one lock; every MUTATING tool
  call acquires it, read-only tools (list/search/read) don't. Stress-tested
  live: 8 threads x 20 writes each (160 concurrent attempts) to the SAME
  file -- zero corruption, zero errors, clean final content.
- **Bounded, not unbounded**: `max_workers` caps in-flight units;
  `MAX_SUBTASK_DEPTH = 1` refuses a subtask that tries to spawn further
  subtasks (verified live -- raises `RuntimeError` on the attempt).
- **JARVIS stays the orchestrator**: `WorkerPool` is plain Python -- the
  LLM proposes WHAT the sub-objectives and dependencies are (via the new
  `spawn_parallel_subtasks` tool, callable from the planner itself, or
  directly from `codebase.py`/`companion_tools.py`); scheduling, retries,
  and timeouts are all decided by this module, never the model.
- **Timeout/retry, stated honestly**: each unit gets `max_retries` with
  bounded exponential backoff, and the pool stops WAITING after `timeout`
  -- but Python cannot forcibly kill a thread, so a genuinely hung call's
  thread can outlive the pool's wait. Documented in `concurrency.py`'s own
  docstring rather than overclaimed.

Multi-worker table (from Pass 2) is now accurate for real, not aspirational:
Worker A (research) and Worker B-shaped edits on independent objectives CAN
now run concurrently through `spawn_parallel_subtasks`; verification/fixing
stays sequential per-task (each subtask still runs its own full plan->
execute->verify loop).

## OTHER ITEMS COMPLETED THIS PASS

- **Diff surfacing fixed**: `apply_patch`'s unified diff was silently
  dropped from `ToolResult.output` (only `output`/`error` keys were
  checked, not `diff`) -- ordinary project edits never showed their diff
  in `/trace` or `codebase.py`. Fixed; the diff now appears in both.
- **`spawn_parallel_subtasks`** is now planner-callable (was flagged
  missing last pass over "recursion/budget risk not yet reasoned
  through") -- reasoned through and implemented: the depth guard is the
  answer to the recursion risk, and `RateLimiter`+`max_workers`+`timeout`
  are the answer to the budget risk.

## STILL GENUINELY UNUSED FROM THE CLAUDE CODE SOURCE, AND WHY

(Supersedes/extends last pass's table -- these remain unaddressed, not
newly discovered.)

- **Structured diff rendering with syntax highlighting** (`StructuredDiff`,
  `HighlightedCode`) -- `codebase.py`/`cli.py` print the unified diff as
  plain text now (previously it was dropped entirely). A colorized/
  highlighted renderer is a real UI improvement but has no functional
  effect on the agent and was deprioritized behind the concurrency work
  this turn was actually asked for.
- **`AgentTool`-style RECURSIVE sub-agent spawning** -- still intentionally
  bounded to depth 1 (see `MAX_SUBTASK_DEPTH`). Unbounded fan-out was
  never asked for and is a genuine safety question (cost, runaway
  recursion) rather than a missing feature.
- **Web frontend approval panel** (`WorkerBadge`/`WorkerPendingPermission`
  UI equivalents) -- still not built. This needs inspecting
  `web_frontend/`'s actual build/API-contract conventions first, which I
  have not done; adding an untested, unintegrated endpoint would risk
  exactly the "claims to work but doesn't" failure UK has flagged before.
  The DATA is ready (`task.pending_approval`, `task.observations`) for a
  future panel to render -- genuinely pending, not silently dropped.
- **Analytics/telemetry service, Statsig feature gates** -- proprietary
  Anthropic service dependencies; JARVIS's own `log_event`/`trace_log`
  cover the equivalent observability need without a third-party service.
- **Computer-use, Notebook, PowerShell surfaces** -- not applicable
  (Android/Termux, no equivalent surface in JARVIS).

## PENDING -- say "continue" for these

- Live LLM round-trip on a real provider (this container has no network) --
  everything above is proven with deterministic fake generators plus the
  real `HybridLLMBridge` wiring, not a live model response.
- `pytest` path specifically (same network constraint -- `py_compile`
  fallback is what's actually been exercised live here).
- Structured diff rendering, web_frontend approval panel -- both
  explicitly scoped out above with reasoning, not silently skipped.
- `task_loop.py` explicit chat-scale/repo-scale delegation -- LLM
  tool-choice already covers this in practice (`run_coding_task` vs
  `run_coding_agent` are both offered as tools); worth confirming against
  real usage before adding a second, redundant detection layer.

---

## RUNTIME BUG FIXES from UK's 2026-09-16 live log + web panel

Four real defects, all found from the actual runtime output UK sent, not
from re-reading code. Root causes, not symptom patches:

### 1. `run_coding_agent` could NEVER execute (the big one)
`dispatch_tool_call()`'s validation block ran `if name in WRITE_TOOLS:` and
demanded `subject`/`predicate`/`value` -- but those are `save_verified_fact`'s
OWN fields. Every other write tool (`run_coding_agent`, `run_coding_task`,
`add_relationship`, `leave_message_for`, `propose_self_feature`) was rejected
with *"subject, predicate and value are all required"* BEFORE its method was
called. UK's log shows the exact signature: three `run_coding_agent` calls in
one turn (the model retrying a call that kept erroring) then a hedge reply.
**Fix**: scoped the block to `save_verified_fact` only. Verified: dispatch now
reaches the agent and returns a real result.

### 2. Duplicate expensive tool calls
`MAX_TOOL_ITERATIONS` correctly lets the model call again after seeing a
result -- right for cheap reads, wrong for a repo-scale agent run (real LLM
spend, real file writes) fired 3x for one request. **Fix**: new
`ONCE_PER_TURN_TOOLS` gate in `dispatch_tool_call`; a repeat returns the FIRST
result (with a `note`) instead of re-running. Reset per turn in
`run_tool_loop`. Verified both branches live.

### 3. Fabricated/hedged reply after a coding run
The tool returned a raw `task.as_dict()` -- a large nested blob with no plain
statement of outcome, so the model had nothing quotable and invented
*"mujhe status pata nahi"*. **Fix**: new `_coding_agent_result()` returns a
human-readable `summary` FIRST (what happened, which files, verification
pass/fail, why it stopped), plus `instruction_to_model` forbidding claims the
`status` doesn't support. `cli.py`'s formatter now renders that SAME dict, so
CLI and chat can't diverge.

### 4. CodeBox web panel: "Poora nahi hua -- 0 attempt"
`run_coding_session` counted `s.kind == "run"`, but `run_python()` appends
steps with kind `"run_python"` -- so the count was structurally always 0 for
the path the loop actually uses, making a real failure look like a loop that
never ran. **Fix**: count both kinds, and when nothing ran, surface the
recorded `blocked_reason` instead of a bare zero. Verified both the
success (`attempts: 1`) and empty-code (`"model ne khali code diya"`) cases.

### 5. CodeBox is no longer an island
New backend routes `/api/coding_agent/run`, `/api/coding_agent/approve`,
`/api/coding_agent/state` -- all calling the SAME `brain.run_coding_agent` /
`resume_coding_agent` that `cli.py` and `codebase.py` use. `/state` returns
the full task (plan, observations, tool calls, diffs, verifications, pending
approval) for a frontend panel to render, with an honest empty state when no
run has happened. No second agent implementation.

### 6. `CODING_AGENT_HOWTO.txt` (repo root)
UK's fair complaint -- "tumne btaya bhi nahi ki coding agent se kaise baat
kare". Plain-Hinglish guide: the three entry points, what auto-approves vs
pauses vs is always denied, and what to do when a run stops.

---

## FRONTEND (2026-09-16) -- Coding Agent workspace + CodeBox fixes

### New: `web_frontend/src/components/CodingAgentWorkspace.tsx`
The repo-scale surface, registered as its own tab next to CodeBox
(same capability family, two depths: one script vs a whole project).
Renders, all from the server's REAL task record -- never invented:

- **Status + phase rail** -- live status chip (Running/Verifying/Needs
  approval/Completed/Failed) with the full phase sequence, current phase
  highlighted, iteration counter.
- **APPROVAL GATE** -- the one thing that must never be missable: an
  amber bordered card showing WHAT tool wants to run, its exact
  arguments, WHY it's asking, and Approve/Deny buttons wired to
  `/api/coding_agent/approve`.
- **Execution trace** -- every tool call, expandable: arguments, output,
  pass/fail/skipped icon, duration. Auto-scrolls as steps arrive.
- **Diff rendering** -- `apply_patch` diffs render with per-line
  green/red/hunk colouring (adapted from the Claude Code source's
  StructuredDiff concept, kept dependency-free). This closes the
  "structured diff rendering" gap listed as missing in the previous
  source-completeness table.
- **Summary strip** -- files touched, last verification (method +
  PASSED/FAILED + failure output), artifacts.
- **Tool belt inspector** -- every registered tool with its risk tier
  colour-coded, so the approval policy is visible, not implicit.
- **Honest empty state** -- when no run has happened it says so and
  points at the other two entry points (`/coding_agent`, `codebase.py`),
  rather than showing a fake plan.

Polling runs ONLY while a task is genuinely in flight; an idle or
finished task does not poll in the background.

### Wiring
- `api/client.ts`: `codingAgentRun` / `codingAgentApprove` / `codingAgentState`.
- `types.ts`: `ConsoleView` gains `'coding_agent'`.
- `config/features.ts`: registered `ready: true`, admin/owner/co_owner
  only -- same operator tier as codebox, since this one edits whole
  projects.
- `App.tsx`: import, nav button (Bot icon, next to CodeBox), view route.

All three surfaces -- this panel, `cli.py`'s `/coding_agent`, and
`codebase.py` -- call the SAME `brain.run_coding_agent` /
`resume_coding_agent`. No second agent implementation anywhere.

### CodeBox bug #7 (found while inspecting the panel)
`CodeBoxScreen.tsx` declared and rendered `result.stdout` /
`result.stderr`, but the backend returns ONE combined `output` field
(`codebox.Step.as_dict()` -- stderr is appended server-side under an
`[stderr]` marker). **The Output panel therefore rendered nothing even
on a successful run.** This is a separate defect from the "0 attempt"
counter bug fixed earlier this session -- together they made the panel
look completely dead. Fixed: correct field, colour-coded by `ok`, and
`blocked_reason` now surfaces so a stalled build explains itself.

## REMAINING (unchanged, still honest)

- **Neural-chat thinking-trace persistence** -- NOT done. The backend
  work needed is a store for per-turn workflow traces plus an endpoint
  to read them back by session; `ThinkingSteps.tsx` currently renders
  live in-memory state only, so a refresh drops it. I have not yet
  traced how chat turns persist in this codebase, and inventing an
  endpoint without that would repeat exactly the "claims to work but
  doesn't" failure from earlier this session.
- **`npm install` / real browser render** -- this container has no
  network, so the new component is syntax-checked (tsc, clean apart
  from unavoidable missing-React-types noise) but not built or rendered.
  Needs `npm install && npm run build` on your device.
- **Live LLM round-trip** -- same network constraint.
