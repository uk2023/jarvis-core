from __future__ import annotations

"""STEP-TURN GOALS -- plan, then work through it, inside one turn.

UK's ask (2026-09-13): "owner yani main, jab kahun chat mein bhi step
turn le sakta hun kisi goal ko pura karne ke liye -- coding + non-coding
task alike writing + designing + system related task."

Scope, deliberately narrow:

  * OWNER / CO-OWNER ONLY. An admin or user asking for a long task gets
    a normal single-turn answer. Multi-step means many model calls in
    one turn, so letting anyone trigger it hands them UK's token budget.

  * OPT-IN, NOT AUTOMATIC. Ordinary chat stays one turn even for the
    owner -- this runs when UK actually asks for it. A conversational
    reply gains nothing from iteration and pays latency for it.

  * SYSTEM TASKS ARE GATED AGAIN AT EXECUTION. Being owner lets you
    START a system task; each system step is still checked, so a plan
    that drifts into system work mid-run cannot slip through on the
    strength of the first step's approval.

The shape is plan -> execute -> verify, with each step seeing what the
previous ones produced. Coding steps go to the codebox and actually run;
writing/design steps produce text; system steps are described and held
for explicit confirmation rather than executed blind.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event
from ..skills.sandbox_policy import can_run_system_task

MAX_PLAN_STEPS = 10

CODING = "coding"
WRITING = "writing"
DESIGN = "design"
SYSTEM = "system"
REVIEW = "review"

_STEP_KINDS = {CODING, WRITING, DESIGN, SYSTEM, REVIEW}


@dataclass
class GoalStep:
    index: int
    kind: str
    description: str
    output: str = ""
    ok: bool = True
    executed: bool = False
    needs_confirmation: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index, "kind": self.kind, "description": self.description,
            "output": self.output[:3000], "ok": self.ok, "executed": self.executed,
            "needs_confirmation": self.needs_confirmation, "detail": self.detail,
        }


def _plan(generate: Callable, goal: str, max_steps: int) -> List[Dict[str, str]]:
    """One planning call. Returns typed steps so the executor knows
    which ones actually run code versus produce prose."""
    try:
        raw = str(generate(
            system_prompt=(
                "You are JARVIS planning how to complete a goal for UK. Return ONLY a JSON array, "
                f"at most {max_steps} items, no prose. Each item: "
                '{"kind": "coding"|"writing"|"design"|"system"|"review", "description": "..."}. '
                "Use 'coding' only for steps where code must actually run. Use 'system' only for "
                "steps that change the machine (installs, services, settings). Keep steps concrete "
                "and ordered so each builds on the last."
            ),
            user_input=f"Goal: {goal}",
            max_tokens=900,
            level="response_generation",
        )).strip()
    except Exception as exc:
        log_event("steps", f"planning failed: {exc}", level="warning")
        return [{"kind": REVIEW, "description": goal}]

    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.M).strip()
    try:
        parsed = json.loads(raw)
        steps = []
        for item in parsed[:max_steps]:
            kind = str(item.get("kind", WRITING)).lower().strip()
            steps.append({
                "kind": kind if kind in _STEP_KINDS else WRITING,
                "description": str(item.get("description", "")).strip(),
            })
        return [s for s in steps if s["description"]] or [{"kind": REVIEW, "description": goal}]
    except Exception:
        # Model ignored the format -- fall back to treating each line as
        # a writing step rather than abandoning the whole goal.
        lines = [l.strip(" -*0123456789.") for l in raw.splitlines() if l.strip()]
        return [{"kind": WRITING, "description": l} for l in lines[:max_steps]] or [{"kind": REVIEW, "description": goal}]


def run_goal_steps(
    generate: Callable,
    *,
    goal: str,
    role: str,
    is_verified: bool,
    max_steps: int = 6,
    brain: Any = None,
) -> Dict[str, Any]:
    """Execute a goal step by step. Owner/co-owner only."""
    role_l = (role or "").strip().lower()
    if role_l not in {"owner", "co_owner"} or not is_verified:
        return {
            "allowed": False,
            "reason": ("Step-by-step goal execution sirf verified owner ya co-owner ke liye hai. "
                       "Baaki sabke liye normal single-turn jawab milega."),
        }

    max_steps = max(1, min(int(max_steps), MAX_PLAN_STEPS))
    plan = _plan(generate, goal, max_steps)
    steps: List[GoalStep] = []
    context_so_far: List[str] = []

    for i, planned in enumerate(plan, start=1):
        kind = planned["kind"]
        desc = planned["description"]
        step = GoalStep(index=i, kind=kind, description=desc)

        if kind == SYSTEM:
            # Re-checked HERE, not only at entry: a plan can drift into
            # system work after starting, and the first step's approval
            # must not authorise that.
            allowed, why = can_run_system_task(role_l, is_verified)
            step.needs_confirmation = True
            step.executed = False
            step.output = (
                f"System-level step hai: {desc}\n"
                + ("Aap authorised ho, par main ise bina aapke explicit 'haan' ke nahi chalaunga."
                   if allowed else f"Refused: {why}")
            )
            step.ok = allowed
            steps.append(step)
            context_so_far.append(f"[step {i} held for confirmation] {desc}")
            continue

        if kind == CODING and brain is not None and hasattr(brain, "run_coding_task"):
            try:
                result = brain.run_coding_task(task=f"{goal}\n\nThis step: {desc}", max_steps=3)
                step.executed = True
                step.ok = bool(result.get("solved"))
                step.output = result.get("summary", "")
                step.detail = {"attempts": result.get("attempts"), "session": result.get("session_id")}
            except Exception as exc:
                step.ok = False
                step.output = f"Coding step failed: {exc}"
            steps.append(step)
            context_so_far.append(f"[step {i} coding] {desc} -> {'ok' if step.ok else 'failed'}")
            continue

        # writing / design / review -- produce content, aware of prior steps.
        try:
            piece = str(generate(
                system_prompt=(
                    f"You are JARVIS working through a goal for UK, step {i} of {len(plan)}. "
                    "Produce ONLY this step's output. Do not restate the plan, do not summarise "
                    "other steps, do not add a conclusion unless this is the final step."
                ),
                user_input=(
                    f"Overall goal: {goal}\n\n"
                    f"Steps so far:\n" + ("\n".join(context_so_far) if context_so_far else "(none yet)")
                    + f"\n\nThis step ({kind}): {desc}\n\nDo it now."
                ),
                max_tokens=1500,
                level="response_generation",
            )).strip()
            step.executed = True
            step.ok = bool(piece)
            step.output = piece or "(khali output aaya)"
        except Exception as exc:
            step.ok = False
            step.output = f"Step failed: {exc}"

        steps.append(step)
        context_so_far.append(f"[step {i} {kind}] {desc}")

        if not step.ok:
            break

    done = sum(1 for s in steps if s.ok and s.executed)
    held = [s for s in steps if s.needs_confirmation]

    return {
        "allowed": True,
        "goal": goal,
        "planned_steps": len(plan),
        "steps": [s.as_dict() for s in steps],
        "completed_steps": done,
        "awaiting_confirmation": [s.as_dict() for s in held],
        "complete": done == len(plan) and not held,
        "summary": (
            f"{done}/{len(plan)} step poore hue."
            + (f" {len(held)} system step aapki confirmation ka intezaar kar rahe hain."
               if held else "")
        ),
        "timestamp": time.time(),
    }
