#!/usr/bin/env python3
from __future__ import annotations

"""codebase.py -- standalone terminal interface for JARVIS's Coding Agent.

STYLING NOTE (2026-09-17): the color palette below (CLAUDE_COLORS) is
adapted from the supplied Claude Code source's utils/theme.ts dark
theme -- the actual rgb() values Claude Code's own terminal uses for
its claude-orange accent, permission (blue-purple), success/error/
warning, and diff colors. Colors are design data, not executable
logic, so they transfer directly; the RENDERING CODE itself is
original JARVIS/rich code, not copied -- Claude Code's own component
code is Ink (a terminal React renderer) compiled with Bun and wired to
~50 Anthropic-internal modules per file (AppState, keybindings,
bridge, schemas...) that do not exist outside that repo, so it cannot
be dropped in here; see CODING_AGENT_HOWTO.txt for the fuller
explanation. What IS reproduced faithfully: the plan-as-checklist
presentation, the permission-request layout (what/why/risk), and the
diff color scheme -- the same three patterns web_frontend's
CodingAgentWorkspace.tsx (PlanChecklist, the approval card, DiffView)
already carries, so all three surfaces (chat panel, codebase.py,
cli.py) present a run the same way.

Every command below still calls straight into core/skills/coding_agent/
-- the exact same CodingAgent, ToolRegistry, approval gate and
packaging module cli.py's `/coding_agent` uses. No agent logic lives
in this file.

USAGE
    python3 codebase.py [--repo PATH] [--role owner|admin|user] [--max-iterations N]

REPL COMMANDS
    <objective text>        start (or continue past a fix cycle) a coding task
    /status                 current task's status/phase/last verification
    /trace                  full observation log for the current task
    /tools                  list the agent's tool belt (name, risk, description)
    /approve  /deny         answer a WAITING_APPROVAL pause and continue
    /package [zip|tar.gz]   package the current workspace as an artifact
    /subtask <objective>    run a tracked child task against the SAME workspace
    /help                   this list
    /exit                   quit
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich import box as rich_box
    _RICH = True
except Exception:  # pragma: no cover -- codebase.py must still run without rich
    _RICH = False


# Adapted from Claude Code's utils/theme.ts darkTheme -- see module
# docstring. rgb(...) strings are valid rich color specs directly.
CLAUDE_COLORS = {
    "claude": "rgb(215,119,87)",        # accent -- headers, the agent's own voice
    "permission": "rgb(177,185,249)",   # approval-gate panels
    "plan_mode": "rgb(72,150,140)",     # plan/checklist accents
    "success": "rgb(78,186,101)",
    "error": "rgb(255,107,128)",
    "warning": "rgb(255,193,7)",
    "diff_added": "rgb(56,166,96)",
    "diff_removed": "rgb(179,89,107)",
    "subtle": "rgb(140,140,140)",
    "inactive": "rgb(153,153,153)",
}

if _RICH:
    _console = Console(highlight=False)

    def _out(renderable) -> None:
        _console.print(renderable)
else:
    def _out(renderable) -> None:  # noqa: ANN001
        print(renderable if isinstance(renderable, str) else str(renderable))


HELP = """\
  <objective text>        start a coding task (or the next fix cycle)
  /status                 current task's status/phase/last verification
  /trace                  full observation log for the current task
  /tools                  list the agent's tool belt
  /approve | /deny        answer a pending approval and continue
  /package [zip|tar.gz]   package the current workspace
  /subtask <objective>    run a tracked child task in the same workspace
  /help                   this list
  /exit                   quit"""


def _build_generate():
    """JARVIS's OWN provider abstraction -- whatever HybridLLMBridge
    currently routes to (Groq/local/etc) is what answers here too."""
    from core.orchestration.llm_bridge import HybridLLMBridge
    bridge = HybridLLMBridge()
    return bridge.generate_response


# ------------------------------------------------------------- rendering
# Every renderer below degrades to plain text if rich isn't installed
# (_RICH False) -- codebase.py must still be usable without it.

def _status_style(status: str) -> str:
    return {
        "COMPLETED": CLAUDE_COLORS["success"],
        "FAILED": CLAUDE_COLORS["error"],
        "BLOCKED": CLAUDE_COLORS["error"],
        "WAITING_APPROVAL": CLAUDE_COLORS["warning"],
        "RUNNING": CLAUDE_COLORS["claude"],
        "PLANNING": CLAUDE_COLORS["claude"],
        "VERIFYING": CLAUDE_COLORS["plan_mode"],
    }.get(status, CLAUDE_COLORS["inactive"])


def _render_status(task: dict) -> None:
    if not _RICH:
        _out(f"[{task.get('status')}] {task.get('objective')}")
        return
    color = _status_style(task.get("status", ""))
    body = Text()
    body.append(f"{task.get('objective', '')}\n", style="bold")
    body.append(f"phase: {task.get('phase')}   ", style=CLAUDE_COLORS["subtle"])
    body.append(f"iteration {task.get('iteration')}/{task.get('max_iterations')}",
                 style=CLAUDE_COLORS["subtle"])
    if task.get("result_summary"):
        body.append(f"\n{task['result_summary']}", style="white")
    _out(Panel(body, title=f"[bold]{task.get('status', '?')}[/bold]",
               border_style=color, box=rich_box.ROUNDED))


def _render_plan(task: dict) -> None:
    """Plan-as-checklist -- same pattern as web_frontend's PlanChecklist:
    pending (dim circle) -> done (green check) -> failed (red x), matched
    to observations by tool_call id, not position."""
    plan = task.get("plan") or []
    if not plan:
        return
    result_by_id = {}
    for obs in task.get("observations") or []:
        call = obs.get("tool_call")
        if call:
            result_by_id[call["id"]] = obs.get("result")

    if not _RICH:
        for call in plan:
            r = result_by_id.get(call["id"])
            mark = "x" if r and not r.get("ok") else ("v" if r else " ")
            _out(f"  [{mark}] {call['tool_name']}({call.get('arguments')})")
        return

    table = Table.grid(padding=(0, 1))
    for call in plan:
        r = result_by_id.get(call["id"])
        done = r is not None
        ok = bool(r and r.get("ok") and not r.get("skipped"))
        if done and ok:
            mark, style = "\u2713", CLAUDE_COLORS["success"]
        elif done and not ok:
            mark, style = "\u2717", CLAUDE_COLORS["error"]
        else:
            mark, style = "\u25cb", CLAUDE_COLORS["inactive"]
        arg_path = (call.get("arguments") or {}).get("path", "")
        line = Text()
        line.append(f" {mark} ", style=f"bold {style}")
        line.append(call["tool_name"], style="white" if done else CLAUDE_COLORS["subtle"])
        if arg_path:
            line.append(f"  {arg_path}", style=CLAUDE_COLORS["subtle"])
        table.add_row(line)
    _out(Panel(table, title="Plan", border_style=CLAUDE_COLORS["plan_mode"],
               box=rich_box.ROUNDED))


def _render_diff(diff_text: str) -> None:
    """Colored per-line diff -- diff_added/diff_removed lifted straight
    from Claude Code's theme (see module docstring); same scheme
    web_frontend's DiffView uses, so a diff looks the same everywhere."""
    if not diff_text:
        return
    if not _RICH:
        _out(diff_text)
        return
    body = Text()
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            body.append(line + "\n", style=CLAUDE_COLORS["subtle"])
        elif line.startswith("@@"):
            body.append(line + "\n", style=CLAUDE_COLORS["plan_mode"])
        elif line.startswith("+"):
            body.append(line + "\n", style=CLAUDE_COLORS["diff_added"])
        elif line.startswith("-"):
            body.append(line + "\n", style=CLAUDE_COLORS["diff_removed"])
        else:
            body.append(line + "\n", style=CLAUDE_COLORS["inactive"])
    _out(Panel(body, border_style=CLAUDE_COLORS["subtle"], box=rich_box.MINIMAL))


def _render_trace(task: dict) -> None:
    obs = task.get("observations") or []
    if not obs:
        _out("(no observations yet)")
        return
    if not _RICH:
        for o in obs:
            call = o.get("tool_call")
            if call:
                r = o.get("result") or {}
                status = "ok" if r.get("ok") else ("skipped" if r.get("skipped") else "FAILED")
                _out(f"  [{o['step_index']:>3}] {o['phase']:<9} {call['tool_name']}({call['arguments']}) -> {status}")
            elif o.get("note"):
                _out(f"  [{o['step_index']:>3}] {o['phase']:<9} {o['note']}")
        return

    for o in obs:
        call = o.get("tool_call")
        if not call:
            if o.get("note"):
                _out(Text(f"  {o['phase']:<9} {o['note']}", style=CLAUDE_COLORS["subtle"]))
            continue
        r = o.get("result") or {}
        ok = r.get("ok")
        skipped = r.get("skipped")
        color = CLAUDE_COLORS["success"] if ok else (
            CLAUDE_COLORS["warning"] if skipped else CLAUDE_COLORS["error"])
        header = Text()
        header.append(f"[{o['step_index']}] ", style=CLAUDE_COLORS["subtle"])
        header.append(f"{o['phase']} ", style=CLAUDE_COLORS["plan_mode"])
        header.append(call["tool_name"], style=f"bold {color}")
        arg_path = (call.get("arguments") or {}).get("path")
        if arg_path:
            header.append(f"  {arg_path}", style=CLAUDE_COLORS["subtle"])
        _out(header)
        diff = (r.get("detail") or {}).get("diff") if isinstance(r.get("detail"), dict) else None
        if diff:
            _render_diff(diff)
        elif r.get("output") and not ok:
            _out(Text(f"    {r['output'][:300]}", style=color))


def _render_approval(task: dict) -> None:
    """WHAT / WHY / RISK -- the exact shape Claude Code's own
    PermissionRuleExplanation surfaces (tool, reason, and what would
    change), reproduced in rich rather than in Ink."""
    pa = task.get("pending_approval") or {}
    call = pa.get("call", {})
    if not _RICH:
        _out(f"WAITING FOR APPROVAL: {call.get('tool_name')}({call.get('arguments')})")
        _out(f"why: {pa.get('reason')}")
        _out("-> /approve or /deny")
        return
    body = Text()
    body.append("WHAT  ", style=f"bold {CLAUDE_COLORS['permission']}")
    body.append(f"{call.get('tool_name')}({call.get('arguments')})\n", style="white")
    body.append("WHY   ", style=f"bold {CLAUDE_COLORS['permission']}")
    body.append(f"{pa.get('reason')}\n", style="white")
    body.append("\n-> /approve  or  /deny", style=CLAUDE_COLORS["subtle"])
    _out(Panel(body, title="[bold]Approval needed[/bold]",
               border_style=CLAUDE_COLORS["permission"], box=rich_box.HEAVY))


def _render_task(task: dict) -> None:
    if task.get("status") == "WAITING_APPROVAL" and task.get("pending_approval"):
        _render_status(task)
        _render_plan(task)
        _render_approval(task)
        return
    _render_status(task)
    _render_plan(task)
    verifs = task.get("verifications") or []
    if verifs:
        v = verifs[-1]
        color = CLAUDE_COLORS["success"] if v.get("passed") else CLAUDE_COLORS["error"]
        if _RICH:
            _out(Text(f"verification ({v.get('method')}): "
                       f"{'PASSED' if v.get('passed') else 'FAILED'}", style=f"bold {color}"))
        else:
            _out(f"verification ({v.get('method')}): {'PASSED' if v.get('passed') else 'FAILED'}")
    if task.get("errors"):
        for e in task["errors"][-3:]:
            _out(Text(f"error: {e}", style=CLAUDE_COLORS["error"]) if _RICH else f"error: {e}")


def _begin_fresh_budget(agent) -> None:
    """See the fresh-turn-budget explanation in backend/routes_codebox.py
    (_fresh_llm_turn) and cli.py's /coding_agent handler -- codebase.py's
    REPL has the identical gap, once per DISTINCT unit of work (a new
    objective, a resume, or a subtask), not just once at startup."""
    bridge = getattr(agent.generate, "__self__", None)
    begin = getattr(bridge, "begin_turn_budget", None)
    if callable(begin):
        begin()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS Coding Agent -- standalone terminal interface")
    parser.add_argument("--repo", default=None, help="existing project to work on; omit to start a fresh sandbox project")
    parser.add_argument("--role", default="owner", choices=["owner", "co_owner", "admin", "user"])
    parser.add_argument("--max-iterations", type=int, default=6)
    args = parser.parse_args()

    from core.skills.coding_agent import CodingAgent, packaging as coding_agent_packaging

    try:
        generate = _build_generate()
    except Exception as exc:
        _out(f"Could not start JARVIS's LLM provider: {exc}\n"
             f"(codebase.py still runs -- tool calls that don't need generation, like /tools, still work.)")
        generate = lambda **kw: ""  # noqa: E731 -- degrade, don't crash the REPL

    agent = CodingAgent(generate, role=args.role, repo_path=args.repo, max_iterations=args.max_iterations)
    task = None

    if _RICH:
        _out(Panel(Text("JARVIS Coding Agent -- standalone terminal interface", style=f"bold {CLAUDE_COLORS['claude']}"),
                   border_style=CLAUDE_COLORS["claude"], box=rich_box.DOUBLE))
    else:
        _out("JARVIS Coding Agent -- standalone terminal interface")
    _out(f"workspace: {agent.workspace.root}")
    _out("Type an objective, or /help.")

    while True:
        try:
            line = input("codebase> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue

        if line in ("/exit", "/quit"):
            break
        elif line == "/help":
            _out(HELP)
        elif line == "/tools":
            for t in agent.registry.list_tools():
                flag = " destructive" if t["destructive"] else ""
                _out(f"  {t['name']:<18} [{t['risk']}{flag}] -- {t['description']}")
        elif line == "/status":
            _render_status(task) if task else _out("No task yet.")
        elif line == "/trace":
            _render_trace(task) if task else _out("No task yet.")
        elif line in ("/approve", "/deny"):
            if task is None or task["status"] != "WAITING_APPROVAL":
                _out("Nothing is waiting on approval.")
                continue
            _begin_fresh_budget(agent)
            task = agent.resume(_task_obj(agent, task), approve=(line == "/approve")).as_dict()
            _render_task(task)
        elif line.startswith("/package"):
            parts = line.split()
            fmt = parts[1] if len(parts) > 1 else "zip"
            label = task.get("id") if task else "workspace"
            result = coding_agent_packaging.package_project(
                str(agent.workspace.root), out_dir="dist",
                archive_name=f"project_{label}", fmt=fmt)
            _out(str(result))
        elif line.startswith("/subtask"):
            objective = line[len("/subtask"):].strip()
            if not task:
                _out("Run a top-level objective first -- a subtask needs a parent task.")
            elif not objective:
                _out("Usage: /subtask <objective>")
            else:
                _begin_fresh_budget(agent)
                child = agent.run_subtask(objective, parent=_task_obj(agent, task))
                _render_task(child.as_dict())
        else:
            _begin_fresh_budget(agent)
            result_task = agent.run(line)
            task = result_task.as_dict()
            _agent_task_cache[task["id"]] = result_task
            _render_task(task)


# resume()/run_subtask() need the live CodingTask object (not the dict
# snapshot rendered to the terminal) -- kept in a tiny id-keyed cache so
# the REPL only ever deals in dicts for display but the real object for
# continuation.
_agent_task_cache: dict = {}


def _task_obj(agent, task_dict: dict):
    cached = _agent_task_cache.get(task_dict.get("id"))
    return cached if cached is not None else task_dict


if __name__ == "__main__":
    main()
