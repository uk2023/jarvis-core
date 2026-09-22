from __future__ import annotations

"""ONE LOOP: THINK, ACT, VERIFY, CONCLUDE.

UK (2026-09-14): "extended thinking step turn multi turn sab ek hi
ho... Claude ki tarah think karke, beech mein jitne turns lena, aur
task end tak complete karna."

He is right that these were three things pretending to be one feature:

    thinking.py     reasoned in stages and then answered
    step_goals.py   planned steps and executed them
    codebox.py      iterated on code until it ran

Each was reachable separately, none knew about the others, and none of
them finished a task -- thinking stopped at an answer, step_goals
stopped at a plan-with-outputs. So "calculator bana do" produced either
prose about a calculator or a list of steps describing one, never a
calculator that ran.

THE LOOP
========
    UNDERSTAND  what is being asked, what is assumed, what "done" means
    PLAN        concrete steps, typed (code / write / verify / system)
    EXECUTE     each step; code steps ACTUALLY RUN in the sandbox
    VERIFY      check the result against the done-criteria from step 1
    CONCLUDE    what was built, what works, what did not

Every stage is emitted as an event, so the same run drives the CLI
panel and the frontend ThinkingSteps panel. One implementation, two
surfaces -- the previous split is how they drifted apart.

WHAT STOPS IT RUNNING AWAY
==========================
A loop that calls an LLM per step can burn a turn's budget in seconds
and, on a phone, take the process down with it. So:

  * the budget is checked BEFORE each step, not after;
  * MAX_STEPS is a hard cap, not a suggestion;
  * a failed verify retries ONCE, then reports honestly rather than
    looping on a problem it is not solving.

Stopping early with partial work and saying so is better than an
elegant loop that never terminates. UK has seen "Thought for 26.7s"
followed by a crash; that must not be reachable from here.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from ..runtime.log import log_event

MAX_STEPS = 100     # absolute ceiling -- effort_levels.py's per-level caps sit under this
MIN_BUDGET_TO_CONTINUE = 2
MAX_VERIFY_RETRIES = 0  # retry mechanism removed 2026-09-17, UK's spec -- see effort_levels.py

# Below this many output tokens, a step call isn't worth attempting at
# all -- not enough room for a useful answer even at minimum. See
# TaskLoop._call()'s adaptive clamp and the step loop's early-stop below.
_MIN_STEP_TOKENS = 120


class TaskBudgetExhausted(Exception):
    """Raised by TaskLoop._call() when the turn's output-token budget
    has nothing left worth attempting (fixed 2026-09-17, UK's trace: a
    9-step run where steps 3-9 ALL failed with the same token-exceeded
    message, each one a real network round-trip that could never have
    succeeded, because nothing checked whether budget existed before
    trying. The step loop below catches this specifically to stop the
    whole run immediately with one honest message, instead of letting
    every remaining step repeat the identical failure."""
    pass

# Minimum gap between consecutive LLM calls inside one task. Not a
# throttle for its own sake: without it a 10-step task issues ten
# requests as fast as the socket allows, which trips provider rate
# limits and makes the streamed step view arrive as one instant dump
# instead of something a person can follow.
STEP_PACING_SECONDS = 0.8

KIND_CODE = "code"
KIND_WRITE = "write"
KIND_VERIFY = "verify"
KIND_SYSTEM = "system"
_KINDS = {KIND_CODE, KIND_WRITE, KIND_VERIFY, KIND_SYSTEM}


@dataclass
class TaskStep:
    index: int
    kind: str
    description: str
    output: str = ""
    ok: bool = True
    executed: bool = False
    held: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index, "kind": self.kind, "description": self.description,
            "output": self.output[:2500], "ok": self.ok, "executed": self.executed,
            "held": self.held, "detail": self.detail,
            "duration_ms": round(self.duration_ms, 1),
        }


def _parse_json_list(raw: str) -> Optional[List[Dict[str, Any]]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip(), flags=re.I | re.M)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, list) else None
    except Exception:
        return None


class TaskLoop:
    """Runs one task from request to finished result."""

    def __init__(self, generate: Callable, *, brain: Any = None,
                 role: str = "user", is_verified: bool = False,
                 effort: str = "medium", context: str = ""):
        self.generate = generate
        self.brain = brain
        self.role = (role or "user").lower()
        self.is_verified = bool(is_verified)
        self.steps: List[TaskStep] = []
        self._last_call_at: float = 0.0
        self._calls_made: int = 0
        # CONVERSATION CONTEXT (2026-09-19, real bug UK caught: "Continue"
        # sent to a running TaskLoop produced "What's being asked: user
        # wants me to continue something... ambiguous, what exactly
        # should be continued" -- because _understand()/_plan() sent
        # ONLY the bare task string to the LLM, nothing about what was
        # discussed before. routes_codebox.py already built a real
        # combined_ctx (continuity state + grounding + persona) for
        # think_stream()'s staged reasoner, but never passed it to
        # TaskLoop at all -- the two reasoning paths had completely
        # different amounts of context, which is exactly the
        # discussion-vs-thinking divergence UK reported ("normal
        # thinking mein continuity hai... extended thinking bilkul
        # context se door chala jaata hai"). Stored once here, used in
        # both _understand() and _plan() below.
        self.context = context or ""

        # EFFORT (2026-09-14, UK's 5-level spec). One dial drives both
        # this loop's step cap/retries AND thinking.py's stage count --
        # see core/orchestration/effort_levels.py for why they must move
        # together rather than being two settings a person has to
        # remember to align.
        from .effort_levels import profile_for
        self.effort = profile_for(effort)

    # ------------------------------------------------------------ budget
    def _remaining_calls(self) -> int:
        # The effort level's OWN budget is what governs an extended run
        # (2026-09-16). deep is unbounded by design -- UK: "deep
        # thinking mein jab tak kaam pura na ho tab tak chalna chahiye".
        budget = self.effort.llm_call_budget
        if budget >= 0 and self._calls_made >= budget:
            return 0
        try:
            return int(self.brain.llm.budget_status().get("remaining_calls", 0))
        except Exception:
            return MIN_BUDGET_TO_CONTINUE + 1      # unknown: allow, cap still applies

    def _call(self, system: str, user: str, max_tokens: int = 900) -> str:
        # LEVEL: extended_thinking, NOT response_generation (fixed
        # 2026-09-16). Every step here used to charge against
        # 'response_generation', capped at 2 per turn -- so the third
        # step of ANY task failed, and every step after it, with
        # "per-level call budget exceeded". UK's trace shows exactly
        # that: a correct 6-step plan, then every write/code/verify step
        # dying without creating a file or running anything.
        #
        # PACING: a multi-step task otherwise fires its calls
        # back-to-back as fast as the network allows, which is what UK
        # saw ("bina sleep cycle ke LLM call kar raha hai"). A short
        # gap between steps keeps provider rate limits honest and makes
        # the step stream readable as it arrives, rather than ten
        # stages appearing at once.
        now = time.time()
        since_last = now - self._last_call_at
        if self._last_call_at and since_last < STEP_PACING_SECONDS:
            time.sleep(STEP_PACING_SECONDS - since_last)
        self._last_call_at = time.time()
        self._calls_made += 1

        # ADAPTIVE TOKEN CLAMP (fixed 2026-09-17, UK's trace: a 9-step
        # run where steps 3 through 9 ALL failed with the identical
        # "requested 1400/2000/500 tokens but only 186/1210 available"
        # -- every one of those was a real network round-trip that was
        # guaranteed to fail before it was even sent, because a fixed
        # max_tokens was requested without checking what was actually
        # left of the turn's output-token budget. Rather than let each
        # step demand its full default and fail outright, ask for
        # whatever fits in what remains (down to a floor still worth
        # attempting) -- most steps then get a smaller but genuine
        # answer instead of a guaranteed rejection.
        bridge = getattr(self.generate, "__self__", None)
        status_fn = getattr(bridge, "budget_status", None)
        if callable(status_fn):
            try:
                status = status_fn()
                remaining = status.get("remaining_output_tokens")
                if isinstance(remaining, (int, float)):
                    # mirrors _reserve_budget's own RESPONSE_TOKEN_FLOOR
                    # reservation for extended_thinking calls specifically
                    usable = max(0, int(remaining) - getattr(bridge, "RESPONSE_TOKEN_FLOOR", 2000))
                    if usable < max_tokens:
                        if usable < _MIN_STEP_TOKENS:
                            raise TaskBudgetExhausted(
                                f"Turn ka output-token budget is step ke liye khatam ho chuka hai "
                                f"({usable} tokens bache, {_MIN_STEP_TOKENS} chahiye kam se kam)."
                            )
                        max_tokens = usable
            except TaskBudgetExhausted:
                raise
            except Exception:
                pass  # budget introspection is best-effort; never block a call over it

        # RAW SENTINEL LEAK (found 2026-09-18, same root cause as
        # thinking.py's _call() -- see that fix's comment for the full
        # story). Concretely worse here: _run_write_step() does
        # `step.ok = bool(step.output)` -- a non-empty SENTINEL STRING
        # is truthy, so a step that actually failed because no
        # provider was reachable was being reported as a SUCCESSFULLY
        # COMPLETED step, with the raw "[LLM unavailable: ...]" text
        # shown as if it were the real output. Raising here instead
        # routes it through the `except Exception` blocks every caller
        # of _call() already has, which correctly mark the step failed
        # with an honest message.
        from .llm_bridge import LLM_UNAVAILABLE_PREFIX
        raw_result = str(self.generate(
            system_prompt=system, user_input=user,
            max_tokens=max_tokens, level="extended_thinking",
        )).strip()
        if raw_result.startswith(LLM_UNAVAILABLE_PREFIX) or raw_result.startswith("[Model Generation Error") or raw_result.startswith("[Brain Thinking Error:"):
            raise RuntimeError("LLM abhi available nahi hai (provider call fail hua)")
        return raw_result

    # ------------------------------------------------------------- stages
    def _understand(self, task: str) -> Dict[str, Any]:
        try:
            context_block = f"\n\nConversation so far (use this to resolve what \"this\"/\"continue\"/\"it\" refers to -- do NOT ask the user to re-explain something already here):\n{self.context}" if self.context else ""
            raw = self._call(
                "You are JARVIS, about to carry out a task for UK. Return ONLY JSON: "
                '{"goal": "...", "assumptions": ["..."], "done_when": ["..."]}. '
                "done_when must be CHECKABLE conditions, not restatements of the goal. "
                "If the task text alone is ambiguous (e.g. just \"continue\"), resolve it "
                "using the conversation context provided, not by asking a clarifying "
                "question -- that only happens in the final reply, never here.",
                f"Task: {task}{context_block}",
                500,
            )
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.M)
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # Fall back to the task itself rather than inventing criteria.
        return {"goal": task, "assumptions": [], "done_when": []}

    def _plan(self, task: str, understanding: Dict[str, Any], max_steps: int) -> List[Dict[str, str]]:
        """THE INTENT-DECOMPOSITION ENGINE (UK, 2026-09-14: "ensure ki
        har step nikaalne ke liye ek engine hona chahiye jo intent ko
        steps mein break kare, phir code sandboxing complete kare").

        This is that engine. It takes the raw task text and the
        understanding extracted in _understand() (goal + done-criteria)
        and turns it into a TYPED step sequence -- code/write/verify/
        system -- BEFORE anything runs. Nothing in stream() executes a
        step that did not come out of this decomposition; in
        particular, KIND_CODE steps below are handed to
        _run_code_step(), which calls brain.run_coding_task() --
        JARVIS's own sandboxed coding tool (core/skills/codebox.py),
        the same one it already has LLM-tool permission to use on its
        own. So the pipeline is exactly: intent -> decompose (here) ->
        sandboxed execution (_run_code_step) -> verify (_run_verify_step).
        """
        context_block = f"\n\nConversation so far:\n{self.context}" if self.context else ""
        raw = self._call(
            "Plan how to COMPLETE this task -- not how to describe it. Return ONLY a JSON array, "
            f"max {max_steps} items: "
            '[{"kind": "code"|"write"|"verify"|"system", "description": "..."}]. '
            "Use 'code' for anything that must actually run. Include at least one 'verify' step "
            "that checks the done_when conditions. Do not include steps that only explain. "
            "'system' is ONLY for privileged operations that need explicit user approval -- "
            "installing packages, running shell/OS-level commands, git operations, deleting or "
            "moving files outside the task's own output. Loading context, reviewing what was "
            "already produced, or understanding the task are NOT system steps -- that context is "
            "already available to every step; never plan a step whose only job is to 'load' or "
            "'review' something.",
            f"Task: {task}\n\nUnderstanding: {json.dumps(understanding, ensure_ascii=False)}{context_block}",
            700,
        )
        parsed = _parse_json_list(raw) or []
        steps: List[Dict[str, str]] = []
        for item in parsed[:max_steps]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", KIND_WRITE)).lower().strip()
            desc = str(item.get("description", "")).strip()
            if desc:
                steps.append({"kind": kind if kind in _KINDS else KIND_WRITE, "description": desc})
        if not steps:
            steps = [{"kind": KIND_WRITE, "description": task}]
        if not any(s["kind"] == KIND_VERIFY for s in steps) and len(steps) < max_steps:
            steps.append({"kind": KIND_VERIFY, "description": "Check the result against done_when."})
        return steps

    def _run_code_step(self, task: str, step: TaskStep, context: str) -> None:
        """Code steps ACTUALLY RUN. This is the difference between
        completing a task and describing one."""
        if self.brain is None or not hasattr(self.brain, "run_coding_task"):
            step.ok = False
            step.output = "Coding sandbox available nahi hai is turn mein."
            return
        try:
            # max_steps=2, not 3 (fixed 2026-09-18, UK's trace: a
            # 7-step OUTER plan ran out of its shared token pool by
            # step 5-6, tokens_used showing far more consumption than
            # 7 calls at ~1400-2000 tokens each would explain). Root
            # cause: EVERY "[code]" step in the outer plan calls this
            # nested run_coding_task, which internally retries its own
            # write/run/fix loop up to max_steps times, EACH attempt a
            # full ~2000-token call -- so one outer "code" step could
            # silently cost up to 6000 tokens of the shared pool, not
            # the ~2000 the outer step count implied. A 7-step plan
            # with 2-3 code steps could reach 14000+ tokens from
            # nested retries alone, before the plan's own write/verify
            # steps spent anything. Capping this inner loop at 2
            # keeps a real second attempt (still useful when the first
            # has a fixable bug) while roughly halving the worst-case
            # compounding.
            result = self.brain.run_coding_task(
                task=f"{task}\n\nThis step: {step.description}\n\nSo far:\n{context}",
                max_steps=2,
            )
            step.executed = True
            step.ok = bool(result.get("solved"))
            step.output = result.get("summary", "") or "(koi output nahi)"
            step.detail = {"attempts": result.get("attempts"), "session": result.get("session_id")}
        except TaskBudgetExhausted:
            # propagate to the step loop, which stops the whole
            # run with one honest message instead of retrying
            # every remaining step against the same exhausted budget
            raise
        except Exception as exc:
            step.ok = False
            step.output = f"Code step fail hua: {exc}"

    # Recognizes a plan step that is JUST asking to pip-install one or
    # more packages (2026-09-17, UK: "auto pip install ho hi jaaye...
    # git optional rakho, kaam nahi rukna chahiye"). Deliberately
    # narrow -- matches "pip install X", "install the required
    # package(s) X, Y and Z", etc. A step that ALSO wants to run other
    # shell commands, touch git, or change system/device settings does
    # NOT match this and still goes through the full login-gated
    # system-task path below; only a step that is *purely* a package
    # install is safe to auto-run, because that install is isolated to
    # this sandbox's own venv (see sandbox_policy.ensure_sandbox_venv)
    # and can't reach anything else.
    #
    # FIXED 2026-09-18 (UK's trace: "Yeh packages install nahi ho
    # paaye (sandbox venv mein): s." -- a single stray letter "s" as
    # the "package name"). Root cause: the old regex matched the
    # word "package" as a PREFIX of "packages" (no word boundary),
    # landed right after it on the plural "s", and its capture group
    # then grabbed that lone "s" before the following ":" stopped it --
    # so a step reading "Install required Python packages: music21,
    # midiutil, and pydub" silently became "install package 's'".  It
    # also only ever captured ONE package even when several were
    # listed. _extract_pip_packages below replaces the single-capture
    # regex with a real list extraction: it finds the segment naming
    # the packages (after "pip install", or after "package(s)"/
    # "librar(y|ies)" + ":") and splits it on commas/"and"/"plus" into
    # individual names, validating each one.
    _PIP_INTENT_RE = re.compile(
        r"pip\s+install\s+(?P<explicit>[a-zA-Z0-9][a-zA-Z0-9._\-\s,]*)"
        r"|install(?:ing)?\s+(?:the\s+)?(?:required\s+)?(?:python\s+)?packages?"
        r"\s*[:\-]\s*(?P<listed>[a-zA-Z0-9][a-zA-Z0-9._\-\s,]*)"
        r"|install(?:ing)?\s+(?:the\s+)?(?:required\s+)?(?:python\s+)?librar(?:y|ies)"
        r"\s*[:\-]\s*(?P<listed2>[a-zA-Z0-9][a-zA-Z0-9._\-\s,]*)",
        re.I,
    )

    def _extract_pip_packages(self, description: str) -> List[str]:
        from ..skills.sandbox_policy import _SAFE_PACKAGE_NAME
        match = self._PIP_INTENT_RE.search(description or "")
        if not match:
            return []
        raw = match.group("explicit") or match.group("listed") or match.group("listed2") or ""
        # Stop at the first sentence-ending punctuation or parenthetical
        # aside ("...pydub (plus pytest for testing)." should not pull
        # "plus pytest for testing" in as a fifth "package").
        raw = re.split(r"[.(]", raw, maxsplit=1)[0]
        tokens = re.split(r",|\band\b|\bplus\b|\bwith\b", raw, flags=re.I)
        packages = []
        for tok in tokens:
            tok = tok.strip().strip(".")
            if not tok:
                continue
            # "pip install X Y Z" is space-separated, not comma-separated
            # -- if a token still has internal whitespace after the
            # comma/and/plus split above, it's actually several package
            # names run together (real package names never contain
            # spaces), so split it again on whitespace.
            for sub in (tok.split() if " " in tok else [tok]):
                if sub and _SAFE_PACKAGE_NAME.match(sub):
                    packages.append(sub.lower())
        return packages

    def _run_system_step(self, step: TaskStep) -> None:
        """System steps are re-checked HERE, at execution -- a plan can
        drift into system work after it was approved."""
        packages = self._extract_pip_packages(step.description or "")
        if packages:
            sandbox_dir = None
            try:
                from ..skills.sandbox_policy import sandbox_dir_for
                sandbox_dir = sandbox_dir_for(role=self.role, username=getattr(self, "username", None),
                                               session_id=getattr(self, "session_id", None))
            except Exception:
                pass
            if sandbox_dir is not None:
                from ..skills.sandbox_policy import resolve_dependencies
                result = resolve_dependencies(packages, sandbox_dir=sandbox_dir)
                step.held = False
                step.executed = True
                step.ok = len(result.get("installed") or []) == len(packages)
                if result.get("installed"):
                    installed_names = ", ".join(result["installed"])
                    step.output = (
                        f"{installed_names} sandbox ke apne isolated venv mein install ho gaye "
                        f"({sandbox_dir}/.jarvis_venv) -- JARVIS ke apne Python ya system "
                        f"packages ko touch nahi kiya."
                    )
                    if result.get("refused"):
                        refused_names = ", ".join(r["package"] for r in result["refused"])
                        step.output += f"\nInstall nahi ho paaye: {refused_names}."
                else:
                    step.output = f"Install nahi ho paaya: {result.get('note') or result.get('refused')}"
                return

        from ..skills.sandbox_policy import can_run_system_task
        allowed, why = can_run_system_task(self.role, self.is_verified)
        step.held = True
        step.executed = False
        step.ok = allowed
        step.output = (
            f"System-level step: {step.description}\n"
            + ("Aap authorised ho, par bina aapke explicit 'haan' ke main ise nahi chalaunga."
               if allowed else f"Refused: {why}")
        )

    @staticmethod
    def _looks_truncated(text: str) -> bool:
        """Heuristic: did this chunk almost certainly get cut off
        mid-way rather than finishing naturally?

        Used by the chunked-generation mechanism below to decide
        whether to ask for a continuation. Bracket/brace/paren balance
        is the strongest cheap signal for code specifically (a function
        or block cut off mid-way leaves an open bracket with no match).
        Called on the FULL ACCUMULATED text so far, not a lone chunk --
        a continuation chunk often starts by closing something the
        PREVIOUS chunk opened (e.g. "-a) * b" closing an earlier "("),
        so checking any one chunk's balance in isolation is unreliable
        in both directions: it can look balanced while genuinely mid-
        expression (a stray close from finishing the prior chunk offset
        against a new unclosed bracket), or look unbalanced while
        actually fine (a chunk that starts by closing something and
        never opens anything new). The full accumulated text has no
        such ambiguity. This deliberately ignores brackets inside
        strings/comments (a real parser would be needed for that), so
        it is a heuristic, not a guarantee -- which is why the caller
        also caps the number of continuations rather than trusting
        this indefinitely.

        Deliberately does NOT flag "ends on an alphanumeric character
        with no closing punctuation" as truncated -- an earlier version
        of this check did, and it was wrong far more often than right:
        ordinary Python has no statement-terminating punctuation, so
        "return result" ending a perfectly complete function was being
        flagged as cut off (found by this fix's own test, which had to
        be corrected after that false positive burned an extra,
        unnecessary continuation call on already-complete output).
        """
        if not text or not text.strip():
            return False
        stripped = text.rstrip()
        last_char = stripped[-1] if stripped else ""

        # Ends on an opening bracket or a dangling separator/operator --
        # an unambiguous "still mid-expression" signal. Checked BEFORE
        # the overall balance count below: a continuation chunk often
        # starts by closing something the PREVIOUS chunk left open
        # (e.g. "-a) * b" closing an earlier "("), which can make the
        # open/close totals for THIS chunk alone coincidentally match
        # even while it clearly ends unfinished (found by this fix's
        # own test -- a chunk ending in "self.history = [" had equal
        # open/close counts overall and was wrongly accepted as
        # complete until this direct check was added).
        if last_char in "({[,:":
            return True

        opens = text.count("(") + text.count("{") + text.count("[")
        closes = text.count(")") + text.count("}") + text.count("]")
        if opens != closes:
            return True

        return False

    def _run_write_step(self, task: str, step: TaskStep, context: str) -> None:
        """Produce this step's output -- CHUNKED (2026-09-19, UK's own
        monitor trace plus explicit request: "10000 lines ka code bhi
        likha ja sake... chhote chunks mein bhejna aur chunks output ko
        accumulate karke poora kaam karna"). A single _call() is capped
        at a modest max_tokens (payload/response-size limits are exactly
        what was causing the repeated 413s this fix responds to) -- for
        a genuinely large piece of output, that cap alone would silently
        truncate mid-file. Instead: generate a bounded first chunk, check
        with _looks_truncated() whether it was plausibly cut off, and if
        so ask for a CONTINUATION (not a restart) from exactly where it
        left off, accumulating chunks up to a hard cap on how many
        continuations one step will ask for.
        """
        MAX_CONTINUATIONS = 4
        CHUNK_TOKENS = 1400
        accumulated = ""
        try:
            for round_num in range(MAX_CONTINUATIONS + 1):
                if round_num == 0:
                    user_prompt = (
                        f"Task: {task}\n\nSteps so far:\n{context or '(none)'}\n\n"
                        f"This step: {step.description}\n\nDo it now."
                    )
                else:
                    # Only the TAIL of what's accumulated so far goes
                    # back in as context -- sending the whole growing
                    # accumulation on every continuation would itself
                    # eventually recreate the oversized-payload problem
                    # this mechanism exists to avoid.
                    user_prompt = (
                        f"Task: {task}\n\nThis step: {step.description}\n\n"
                        f"You already wrote this much -- continue EXACTLY "
                        f"from where it stops. Do not repeat anything above, "
                        f"do not re-introduce the task, just continue the "
                        f"output itself:\n\n...{accumulated[-800:]}"
                    )
                chunk = self._call(
                    "You are JARVIS completing a task for UK, step "
                    f"{step.index}. Produce ONLY this step's actual output "
                    "-- the thing itself, not a description of it. No "
                    "preamble, no restating the plan.",
                    user_prompt,
                    CHUNK_TOKENS,
                )
                accumulated += chunk
                if not self._looks_truncated(accumulated):
                    break
            step.output = accumulated
            step.executed = True
            step.ok = bool(step.output)
        except TaskBudgetExhausted:
            # propagate to the step loop, which stops the whole
            # run with one honest message instead of retrying
            # every remaining step against the same exhausted budget
            raise
        except Exception as exc:
            step.ok = False
            step.output = f"Step fail hua: {exc}"

    def _run_verify_step(self, understanding: Dict[str, Any], step: TaskStep,
                         context: str) -> None:
        """Check the work against the criteria set in UNDERSTAND.

        Deliberately asked as a yes/no with reasons, so a vague "looks
        good" cannot pass for verification.
        """
        done_when = understanding.get("done_when") or []
        try:
            raw = self._call(
                "You are checking whether a task is genuinely complete. Return ONLY JSON: "
                '{"complete": true|false, "failures": ["..."]}. '
                "Be strict: if a condition cannot be confirmed from the work shown, it is NOT met. "
                "Do not mark complete just because the work looks reasonable.",
                f"Conditions:\n{json.dumps(done_when, ensure_ascii=False)}\n\nWork done:\n{context}",
                500,
            )
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.M)
            data = json.loads(cleaned)
            complete = bool(data.get("complete"))
            failures = data.get("failures") or []
            step.executed = True
            step.ok = complete
            step.detail = {"failures": failures}
            step.output = ("Sab conditions poori hui." if complete
                           else "Yeh reh gaya: " + "; ".join(str(f) for f in failures[:5]))
        except TaskBudgetExhausted:
            # propagate to the step loop, which stops the whole
            # run with one honest message instead of retrying
            # every remaining step against the same exhausted budget
            raise
        except Exception as exc:
            step.executed = True
            step.ok = False
            step.output = f"Verify nahi kar paya: {exc}"

    # --------------------------------------------------------------- run
    def stream_capability(self, task: str, capability: str, *, max_steps: int = 6) -> Generator[Dict[str, Any], None, None]:
        """Invoke ONE narrow capability instead of the full build loop.

        UK's explicit architectural correction (2026-09-18): "extended
        thinking is not equal to coding agent" -- a user who wants deep
        research or a plan, and explicitly does NOT want code written
        yet, must be able to get exactly that: JARVIS hiring the
        research/planning capability on its own, without also running
        _run_code_step/_run_write_step/_run_verify_step. Those steps
        are what actually touches the sandbox/filesystem; understand()
        and plan() alone are pure reasoning and were always safe to
        run standalone -- this just exposes them as their own
        capability instead of only as internal phases of the full
        stream().

        capability:
          "research" / "planning" -- run _understand() + _plan() and
              STOP. No code is written or executed. This is the
              narrow worker for "just think this through with me".
          "full_build" -- identical to stream(); the complete
              understand -> plan -> execute -> verify loop.

        Any other value raises -- silently falling through to
        full_build for an unrecognized capability would be exactly
        the "extended thinking always becomes coding" bug this method
        exists to prevent.
        """
        if capability == "full_build":
            yield from self.stream(task, max_steps=max_steps)
            return

        if capability not in ("research", "planning", "editing", "debug_fix"):
            raise ValueError(
                f"stream_capability: unknown capability {capability!r} -- "
                "must be 'research', 'planning', 'editing', 'debug_fix', "
                "or 'full_build'. Refusing to silently default to full_build."
            )

        max_steps = max(1, min(int(max_steps), MAX_STEPS, self.effort.max_task_steps))

        yield {"type": "effort", "level": self.effort.name, "label": self.effort.label,
              "max_steps": max_steps, "verify_retries": self.effort.verify_retries,
              "step_visibility": self.effort.step_visibility, "capability": capability}

        yield {"type": "stage_start", "stage": "understand"}
        understanding = self._understand(task)
        yield {"type": "stage", "stage": "understand",
               "content": (f"Goal: {understanding.get('goal', task)}\n"
                           + (f"Done when: {'; '.join(understanding.get('done_when') or []) }"
                              if understanding.get("done_when") else "Done-criteria clear nahi the.")),
               "ok": True}

        if capability == "research":
            # Research stops at understanding -- no plan, no execution.
            # This is the case where the user wants JARVIS to think
            # something through and report back, not produce a plan
            # of build steps yet.
            yield {"type": "capability_complete", "capability": "research",
                   "content": understanding}
            return

        if capability in ("editing", "debug_fix"):
            # NARROW WORKERS (2026-09-19, UK: "kuchh edit karna hai to
            # editing worker, kuchh debug karna hai to debug and fix
            # worker" -- a targeted single change or a diagnose-and-fix
            # cycle should not have to pay for a full multi-step _plan()
            # call the way full_build does. Fixed, small step sequences
            # instead of an open-ended plan:
            #   editing:   ONE write step directly on the task text.
            #   debug_fix: ONE code-fix step, then ONE verify step --
            #              exactly "diagnose, fix, confirm", nothing more.
            if self._remaining_calls() < max(MIN_BUDGET_TO_CONTINUE, self.effort.min_budget_calls):
                yield {"type": "aborted", "reason": "Budget khatam -- shuru karne se pehle hi ruk gaya."}
                return

            fixed_plan = (
                [{"kind": KIND_WRITE, "description": task}]
                if capability == "editing"
                else [
                    {"kind": KIND_CODE, "description": f"Fix: {task}"},
                    {"kind": KIND_VERIFY, "description": "Confirm the fix actually works."},
                ]
            )
            context_lines: List[str] = []
            for i, planned in enumerate(fixed_plan, 1):
                if self._remaining_calls() < MIN_BUDGET_TO_CONTINUE:
                    yield {"type": "aborted",
                           "reason": f"Budget khatam -- {i - 1}/{len(fixed_plan)} step ke baad ruka."}
                    return
                step = TaskStep(index=i, kind=planned["kind"], description=planned["description"])
                yield {"type": "stage_start", "stage": step.kind, "index": i,
                       "description": step.description, "chunk_id": 0}
                t0 = time.time()
                context = "\n\n".join(context_lines[-2:])
                try:
                    if step.kind == KIND_CODE:
                        self._run_code_step(task, step, context)
                    elif step.kind == KIND_VERIFY:
                        self._run_verify_step(understanding, step, context)
                    else:
                        self._run_write_step(task, step, context)
                except TaskBudgetExhausted as exc:
                    step.duration_ms = (time.time() - t0) * 1000
                    step.executed = False
                    step.ok = False
                    step.output = str(exc)
                    self.steps.append(step)
                    yield {"type": "stage", "stage": step.kind, "chunk_id": 0, **step.as_dict()}
                    yield {"type": "aborted", "reason": f"Budget khatam: {exc}"}
                    return
                step.duration_ms = (time.time() - t0) * 1000
                self.steps.append(step)
                context_lines.append(f"[{step.kind}] {step.description}\n{step.output}")
                yield {"type": "stage", "stage": step.kind, "chunk_id": 0, **step.as_dict()}

            all_ok = all(s.ok for s in self.steps)
            yield {"type": "capability_complete", "capability": capability,
                   "content": {"understanding": understanding, "complete": all_ok,
                               "steps": [s.as_dict() for s in self.steps]}}
            return

        if self._remaining_calls() < max(MIN_BUDGET_TO_CONTINUE, self.effort.min_budget_calls):
            yield {"type": "aborted", "reason": "Budget khatam -- plan banane se pehle hi ruk gaya."}
            return

        yield {"type": "stage_start", "stage": "plan"}
        try:
            plan = self._plan(task, understanding, max_steps)
        except TaskBudgetExhausted as exc:
            yield {"type": "aborted", "reason": f"Budget khatam -- plan banate waqt hi: {exc}"}
            return
        yield {"type": "stage", "stage": "plan",
               "content": "\n".join(f"{i}. [{s['kind']}] {s['description']}"
                                    for i, s in enumerate(plan, 1)),
               "ok": True, "detail": {"steps": len(plan)}}

        # PLANNING capability stops here -- the plan itself IS the
        # deliverable. Nothing in the plan gets executed. If the user
        # later says "ab implement karo", that becomes a SEPARATE
        # "full_build" invocation (see routes_codebox.py), not an
        # automatic continuation -- planning approving itself into
        # execution is exactly the unasked-for behavior UK rejected.
        yield {"type": "capability_complete", "capability": "planning",
               "content": {"plan": plan, "understanding": understanding}}

    def _narrative_intro(self, plan: List[Dict[str, str]]) -> str:
        """Native (zero-LLM-cost) prose framing the upcoming chunk of
        steps -- the "Let's verify with a real test reproducing the
        exact scenario:" style line UK pointed at in his screenshots.
        Built strictly from the real plan/step descriptions already
        decided by _plan() -- never invented, never a second LLM call
        just to narrate a decision that was already made.
        """
        if not plan:
            return "Let's get started."
        first = plan[0]
        verb = {
            KIND_CODE: "Let's write and run",
            KIND_WRITE: "Let's put together",
            KIND_VERIFY: "Let's verify",
            KIND_SYSTEM: "Let's set up",
        }.get(first["kind"], "Let's start with")
        return f"{verb}: {first['description']}"

    def _narrative_after_verify(self, step: "TaskStep") -> str:
        """Native prose after a verify step -- the "Found a deeper root
        cause..." style line. Built from step.detail['failures'] (real
        verification output) on failure, or a short confirmation on
        pass -- same non-fabrication rule as _narrative_intro.
        """
        if step.ok:
            return "That checks out. Continuing:"
        failures = (step.detail or {}).get("failures") or []
        if failures:
            headline = str(failures[0])
            more = f" ({len(failures) - 1} more)" if len(failures) > 1 else ""
            return f"Found an issue — {headline}{more}. Let me fix this:"
        return "That didn't verify cleanly. Let me fix this:"

    def stream(self, task: str, *, max_steps: int = 6) -> Generator[Dict[str, Any], None, None]:
        """Yields events as the task progresses. Same events drive the
        CLI panel and the frontend ThinkingSteps panel.

        NARRATIVE + CHUNKING (2026-09-19, UK's screenshot of Claude's
        own UI: prose paragraphs interleaved between collapsed "N
        steps >" groups, not one flat step list). Every execution-step
        event now carries a `chunk_id` (increments after each verify
        step -- a natural "did that work, what's next" breakpoint in
        how this loop already operates), and a `{"type": "narrative"}`
        event is yielded at the start of chunk 0 and again after every
        verify step, using the two native helpers above. This is
        commentary ABOUT decisions already made (the plan, a step's
        real output) -- never a fresh judgment call requiring its own
        LLM round-trip, matching this project's zero-cost-when-possible
        principle for anything that isn't genuinely a new decision.
        """
        started = time.time()
        # max_steps argument is now a ceiling ON TOP of the effort
        # profile's own cap, not the sole source of truth -- "low"
        # effort must stay small even if a caller passes max_steps=8.
        max_steps = max(1, min(int(max_steps), MAX_STEPS, self.effort.max_task_steps))

        yield {"type": "effort", "level": self.effort.name, "label": self.effort.label,
              "max_steps": max_steps, "verify_retries": self.effort.verify_retries,
              "step_visibility": self.effort.step_visibility}

        yield {"type": "stage_start", "stage": "understand"}
        understanding = self._understand(task)
        yield {"type": "stage", "stage": "understand",
               "content": (f"Goal: {understanding.get('goal', task)}\n"
                           + (f"Done when: {'; '.join(understanding.get('done_when') or []) }"
                              if understanding.get("done_when") else "Done-criteria clear nahi the.")),
               "ok": True}

        if self._remaining_calls() < max(MIN_BUDGET_TO_CONTINUE, self.effort.min_budget_calls):
            yield {"type": "aborted", "reason": "Budget khatam -- plan banane se pehle hi ruk gaya."}
            return

        yield {"type": "stage_start", "stage": "plan"}
        try:
            plan = self._plan(task, understanding, max_steps)
        except TaskBudgetExhausted as exc:
            # same fix as the step loop below: _plan() also calls
            # _call() and can hit this before a single step even runs
            yield {"type": "aborted", "reason": f"Budget khatam -- plan banate waqt hi: {exc}"}
            return
        yield {"type": "stage", "stage": "plan",
               "content": "\n".join(f"{i}. [{s['kind']}] {s['description']}"
                                    for i, s in enumerate(plan, 1)),
               "ok": True, "detail": {"steps": len(plan)}}

        context_lines: List[str] = []
        verify_retries = 0
        index = 0
        chunk_id = 0

        yield {"type": "narrative", "content": self._narrative_intro(plan), "chunk_id": chunk_id}

        while index < len(plan):
            planned = plan[index]
            index += 1

            if self._remaining_calls() < MIN_BUDGET_TO_CONTINUE:
                yield {"type": "aborted",
                       "reason": f"Budget khatam -- {index - 1}/{len(plan)} step ke baad ruka."}
                break

            step = TaskStep(index=index, kind=planned["kind"], description=planned["description"])
            yield {"type": "stage_start", "stage": step.kind, "index": index,
                   "description": step.description, "chunk_id": chunk_id}

            t0 = time.time()
            context = "\n\n".join(context_lines[-4:])
            try:
                if step.kind == KIND_CODE:
                    self._run_code_step(task, step, context)
                elif step.kind == KIND_SYSTEM:
                    self._run_system_step(step)
                elif step.kind == KIND_VERIFY:
                    self._run_verify_step(understanding, step, context)
                else:
                    self._run_write_step(task, step, context)
            except TaskBudgetExhausted as exc:
                # STOP HERE (fixed 2026-09-17, UK's trace: 9 steps burned
                # through the identical "token budget exceeded" failure
                # one after another). Once the budget genuinely has
                # nothing left, no remaining step in this plan can
                # succeed either -- report it once, honestly, instead of
                # letting the loop keep trying.
                step.duration_ms = (time.time() - t0) * 1000
                step.executed = False
                step.ok = False
                step.output = str(exc)
                self.steps.append(step)
                yield {"type": "stage", "stage": step.kind, "chunk_id": chunk_id, **step.as_dict()}
                yield {"type": "aborted",
                       "reason": f"Budget khatam -- {index}/{len(plan)} step ke baad ruka: {exc}"}
                break
            step.duration_ms = (time.time() - t0) * 1000

            self.steps.append(step)
            context_lines.append(f"[step {index} {step.kind}] {step.description}\n{step.output}")
            # step_visibility: "collapsed" turns still stream the raw
            # event (the frontend decides how much to render), but the
            # content is truncated hard here so a "low" effort run never
            # pays the token cost of a full step transcript it will not
            # show.
            emitted = step.as_dict()
            if self.effort.step_visibility == "collapsed":
                emitted["content"] = ""
                emitted["output"] = emitted["output"][:80]
            yield {"type": "stage", "stage": step.kind, "chunk_id": chunk_id, **emitted}

            # Verify retry count comes from the EFFORT PROFILE now, not
            # a fixed module constant -- "low" gets zero retries, "deep"
            # gets two, per UK's hierarchy.
            if step.kind == KIND_VERIFY and not step.ok and verify_retries < self.effort.verify_retries:
                verify_retries += 1
                failures = (step.detail or {}).get("failures") or []
                plan.insert(index, {
                    "kind": KIND_CODE if any(s["kind"] == KIND_CODE for s in plan) else KIND_WRITE,
                    "description": ("Fix what verification flagged: "
                                    + "; ".join(str(f) for f in failures[:3])),
                })
                plan.insert(index + 1, {"kind": KIND_VERIFY,
                                        "description": "Re-check the done_when conditions."})
                yield {"type": "retry", "reason": step.output}

            # NEW CHUNK AFTER EVERY VERIFY (2026-09-19). A verify step is
            # the natural "did that work, what's next" breakpoint this
            # loop already has -- everything since the last verify (or
            # the start) becomes one collapsible "N steps" group in the
            # UI, followed by real prose about what verify just found,
            # before the next group's steps start arriving.
            if step.kind == KIND_VERIFY and index < len(plan):
                chunk_id += 1
                yield {"type": "narrative", "content": self._narrative_after_verify(step), "chunk_id": chunk_id}

        done = sum(1 for s in self.steps if s.ok and s.executed)
        held = [s for s in self.steps if s.held]
        verified = [s for s in self.steps if s.kind == KIND_VERIFY]
        complete = bool(verified) and verified[-1].ok and not held

        conclusion = self._conclude(task, complete, held)
        yield {
            "type": "done",
            "result": {
                "task": task,
                "complete": complete,
                "steps": [s.as_dict() for s in self.steps],
                "completed_steps": done,
                "total_steps": len(self.steps),
                "awaiting_confirmation": [s.as_dict() for s in held],
                "conclusion": conclusion,
                "duration_ms": round((time.time() - started) * 1000, 1),
            },
        }

    def _conclude(self, task: str, complete: bool, held: List[TaskStep]) -> str:
        """The summary UK asked for: what was done, what works, what did
        not. Built from the real step record, not generated freely --
        a written conclusion could otherwise claim success the steps do
        not support."""
        parts = []
        code_steps = [s for s in self.steps if s.kind == KIND_CODE]
        failed = [s for s in self.steps if not s.ok and not s.held]

        parts.append(
            f"{sum(1 for s in self.steps if s.ok and s.executed)}/{len(self.steps)} step poore hue."
        )
        if code_steps:
            ran = sum(1 for s in code_steps if s.ok)
            parts.append(f"{ran}/{len(code_steps)} code step sach mein chale.")
        if held:
            parts.append(f"{len(held)} system step aapki confirmation ka intezaar kar rahe hain.")
        if failed:
            parts.append("Yeh fail hue: " + "; ".join(f"step {s.index} ({s.kind})" for s in failed[:3]) + ".")

        # BUDGET, STATED PLAINLY (2026-09-16). UK: "yeh na karo ki LLM
        # budget fail aur kaam ho raha hai -- batao ki is turn mein itna
        # kaam hua aur baaki nahi kar paya kyunki budget se upar ho
        # gaya." So when the level's budget is what stopped the run, the
        # conclusion says so and says what is left, instead of looking
        # like an unexplained failure.
        budget = self.effort.llm_call_budget
        if budget >= 0 and self._calls_made >= budget:
            parts.append(
                f"{self.effort.label} effort ka LLM budget ({budget} calls) yahin khatam hua -- "
                f"isliye ruka, kaam galat nahi hua. Aage badhane ke liye effort badha do "
                f"(Deep unbounded hai) ya agle turn mein continue bolo."
            )
            return " ".join(parts)

        parts.append("Task poora hua." if complete
                     else "Task poora NAHI hua -- upar dekho kahan ruka.")
        return " ".join(parts)

    def run(self, task: str, *, max_steps: int = 6) -> Dict[str, Any]:
        """Non-streaming wrapper for the CLI and plain callers."""
        final: Dict[str, Any] = {}
        for event in self.stream(task, max_steps=max_steps):
            if event["type"] == "done":
                final = event["result"]
            elif event["type"] == "aborted":
                final.setdefault("aborted", event["reason"])
        return final or {"complete": False, "conclusion": "Kuch chala hi nahi."}


def wants_task_loop(text: str) -> bool:
    """REMOVED (2026-09-18) -- UK explicitly rejected this keyword-list
    approach to the discuss-vs-act judgment as a brittle, single-
    language, hardcoded patch (JARVIS's architecture has nothing
    hardcoded for genuine judgment calls; only deterministic native
    patterns are, and this isn't one). Replaced by
    core/cognition/conversation_intelligence.py's
    classify_task_disposition(), an actual LLM classification call --
    see backend/routes_codebox.py's think_stream_route for the call
    site. Nothing in this codebase calls this function anymore; it
    raises rather than silently returning a guess, so any stray
    external caller fails loud instead of getting brittle behavior
    back.
    """
    raise RuntimeError(
        "wants_task_loop() was removed 2026-09-18 -- use "
        "core.cognition.conversation_intelligence.classify_task_disposition() "
        "instead, which makes this an LLM judgment call, not a keyword match."
    )
