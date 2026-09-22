from __future__ import annotations

"""CODING AGENT -- self-extension bridge (reuse, not duplicate).

UK's explicit instruction: "the existing JARVIS workflow-learning
mechanisms must be inspected and integrated rather than duplicated...
if an existing mechanism is incomplete, extend it." Two already exist:

  1. core/evolution/self_evolution.py -- propose_feature() / run_qa() /
     decide_proposal(). Already the engine behind the "propose_self_feature"
     chat tool. Sandboxes new code under data/evolution/, runs the same
     5-layer-shaped QA (syntax -> danger-scan -> deps -> isolated-exec ->
     resource) codebox.py uses, and NEVER auto-adopts into the live tree
     -- approval only moves a draft from drafts/ to approved/. That is a
     deliberate structural guarantee (see that file's own docstring) and
     is kept exactly as-is here.

  2. core/learning/learning_coordinator.py + core/skills/skill_learner.py
     + core/skills/skill_registry.py -- SkillLearner.observe(experience)
     accumulates repeated successful actions into governed proposals;
     LearningCoordinator.activate_skill_proposal() is the ONLY existing
     path that calls SkillRegistry.register_approved(), and it already
     refuses anything not status=="approved". Reused via
     record_run_as_experience() below, which just shapes a CodingTask
     into the `experience` dict learn() already expects -- no new
     learning logic.

THE ONE GAP -- what neither of the above provides -- is: once a
self_evolution proposal is "approved", something has to turn its saved
draft code into an ACTUAL callable tool inside a *running* ToolRegistry
(agent.py's tool belt) for THIS coding-agent run to use. That bridge
(activate_tool below) did not exist anywhere in the codebase; it is the
only genuinely new piece of logic in this file. It changes nothing
about self_evolution's approval semantics -- it still refuses anything
not "approved", and it is never called automatically by the loop.
"""

import ast
from pathlib import Path
from typing import Any, Dict, Optional


def propose_tool(feature_name: str, code: str, rationale: str,
                  confidence: float = 0.5) -> Dict[str, Any]:
    """Thin passthrough to self_evolution.propose_feature -- kept here so
    agent.py's tool belt (repo_tools._propose_new_tool) has one place to
    import from, not a re-implementation."""
    from ..evolution.self_evolution import propose_feature
    return propose_feature(feature_name, code, rationale, confidence)


def activate_tool(proposal: Dict[str, Any], *, entry_point: str,
                   target_registry: Any, risk: str = "medium",
                   destructive: bool = False) -> Dict[str, Any]:
    """Turns an APPROVED self_evolution proposal into a live tool in
    `target_registry` (a coding_agent.tool_contract.ToolRegistry).

    Refuses unless proposal["status"] == "approved" -- i.e. unless a
    human already ran decide_self_proposal(approve=True) (existing,
    brain.py, deliberately NOT an LLM-callable tool). This function is
    ALSO never invoked by the agent loop itself; only an explicit human-
    or CLI-triggered call reaches it (see companion_tools.activate_coding_tool).
    """
    if proposal.get("status") != "approved":
        return {"ok": False,
                "error": f"proposal status is '{proposal.get('status')}', not 'approved' -- "
                         f"decide_self_proposal(approve=True) must run first"}

    draft_path = proposal.get("draft_path") or proposal.get("path")
    if not draft_path:
        return {"ok": False, "error": "proposal has no stored code path"}
    try:
        code = Path(draft_path).read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"could not read approved code: {exc}"}

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False, "error": f"approved code no longer parses: {exc}"}
    if not any(isinstance(n, ast.FunctionDef) and n.name == entry_point for n in tree.body):
        return {"ok": False, "error": f"entry_point '{entry_point}' not found as a top-level function"}

    # Re-run the SAME danger scan self_evolution used at proposal time --
    # belt-and-suspenders against a draft file edited on disk between
    # approval and activation.
    from ..evolution.self_evolution import scan_for_danger
    danger = scan_for_danger(code)
    if danger:
        return {"ok": False, "error": f"refused: danger patterns present at activation time: {danger}"}

    namespace: Dict[str, Any] = {}
    try:
        exec(compile(tree, filename=f"<evolved:{proposal.get('feature_name')}>", mode="exec"), namespace)
    except Exception as exc:
        return {"ok": False, "error": f"approved code failed to load: {exc}"}
    handler = namespace.get(entry_point)
    if not callable(handler):
        return {"ok": False, "error": f"'{entry_point}' is not callable"}

    from .coding_agent.tool_contract import ToolSpec
    spec = ToolSpec(name=proposal.get("feature_name") or entry_point,
                     description=(proposal.get("rationale") or "self-authored tool")[:200],
                     handler=handler, risk=risk, destructive=destructive)
    target_registry.register(spec, overwrite=True)
    return {"ok": True, "tool_name": spec.name, "entry_point": entry_point}


def record_run_as_experience(task: Any) -> Dict[str, Any]:
    """Shapes ONE finished CodingTask into the `experience` dict shape
    LearningCoordinator.learn() / SkillLearner.observe() already expect
    (see learning_coordinator.py: action/detail/context/outcome). Does
    NOT call learn() itself -- companion_tools.run_coding_agent does
    that, since only it holds `self.learning`. Kept as a pure function
    here so the shaping logic has one home and is unit-testable without
    a live LearningCoordinator."""
    ok = task.status == "COMPLETED"
    return {
        "action": {"skill": "coding_agent_run", "detail": task.objective[:200]},
        "context": {"goal": task.objective},
        "outcome": {"success": ok, "status": task.status,
                     "detail": (task.result_summary or "")[:300]},
    }
