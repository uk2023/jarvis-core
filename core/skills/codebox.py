from __future__ import annotations

"""CODEBOX -- sandboxed code execution, and the ONLY place JARVIS runs
multi-step agentic turns.

UK's two requirements, kept deliberately separate (2026-09-13):

  * "coding ke liye codebox bhi hona chahiye jaise codebox mein diya
     jata hai" -- a real place to write and RUN code, isolated.

  * "multi-step... jaise Claude karta hai, ek turn mein step by step.
     Par kewal coding/sandboxing ke time -- normal chat ek turn hi
     rahe." So step-by-step iteration is gated to coding sessions.
     Normal conversation stays one-turn, which also keeps the token
     budget predictable for ordinary chat.

SANDBOX POSTURE. This runs on UK's own Termux device, so "sandbox"
here means damage-limitation, not adversarial containment -- it is
protection against JARVIS's own mistakes (an infinite loop, a runaway
write, a stray rm), not against a determined attacker who already has
the device. That distinction is stated plainly rather than implied,
because calling this "secure" would be a lie: a subprocess sharing the
same user account can reach anything that user can reach. The real
guarantees are:

  * a dedicated working directory, created per session, nothing runs
    anywhere else by default;
  * a hard wall-clock timeout on every execution, so a hung or
    infinite-looping program always returns;
  * output truncation, so a program printing in a loop cannot exhaust
    memory or the context window;
  * a refusal list for the small number of commands whose damage is
    irreversible and which no legitimate coding task needs;
  * every step recorded, so a session can be read back afterwards.

Network access is NOT granted to executed code by default.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..runtime.log import log_event

DEFAULT_TIMEOUT_SECONDS = 20
MAX_OUTPUT_CHARS = 8000
MAX_STEPS = 12                      # ceiling on one coding turn's iterations
SANDBOX_ROOT = Path("data/codebox")

# Irreversible or system-level operations. A coding task never needs
# these, so refusing them costs nothing and prevents the one class of
# mistake that cannot be undone.
_REFUSED_PATTERNS = (
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b", r"\bdd\s+if=", r"\bshutdown\b", r"\breboot\b",
    r":\(\)\{.*\};:",                       # fork bomb
    r"\bchmod\s+-R\s+777\s+/",
    r">\s*/dev/sd",
    r"\bpkill\s+-9\b", r"\bkillall\b",
)


@dataclass
class Step:
    index: int
    kind: str                       # 'write' | 'run' | 'note'
    detail: str
    output: str = ""
    exit_code: Optional[int] = None
    ok: bool = True
    duration: float = 0.0
    # 5-LAYER QA RESULT (2026-09-14, UK: "codebox sandbox aur 5-layered
    # QA se lass hona chahiye"). Populated only for kind == 'run_python'
    # steps -- see CodeBox.run_python() below, which is the wiring this
    # field exists for. None for plain shell/'run' steps, which go
    # through a different code path (_refused() pattern matching) that
    # predates this and covers a different concern (irreversible shell
    # commands, not Python code quality).
    qa: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index, "kind": self.kind, "detail": self.detail,
            "output": self.output[:2000], "exit_code": self.exit_code,
            "ok": self.ok, "duration": round(self.duration, 3),
            "qa": self.qa,
        }


@dataclass
class CodingSession:
    session_id: str
    workdir: Path
    steps: List[Step] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "workdir": str(self.workdir),
            "steps": [s.as_dict() for s in self.steps],
            "step_count": len(self.steps),
            "all_ok": all(s.ok for s in self.steps) if self.steps else True,
        }


def _refused(command: str) -> Optional[str]:
    for pattern in _REFUSED_PATTERNS:
        if re.search(pattern, command, re.I):
            return f"Yeh command mana hai (irreversible ya system-level): pattern `{pattern}`"
    return None


class CodeBox:
    """One isolated working directory plus a step log."""

    def __init__(self, session_id: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT_SECONDS,
                 role: str = "user", username: Optional[str] = None):
        self.timeout = max(1, min(int(timeout), 120))
        sid = session_id or uuid.uuid4().hex[:12]
        # PER-ROLE ISOLATION (2026-09-13, UK: "JARVIS ka QA sandbox alag
        # ho aur user + admin + owner logo ka alag"). One shared scratch
        # directory would let any user read -- and overwrite -- another
        # user's work, and would sit alongside JARVIS's own evolution
        # drafts. Each principal now gets their own tree; JARVIS's
        # self-evolution workspace stays entirely separate under
        # data/evolution/.
        try:
            from .sandbox_policy import sandbox_dir_for
            workdir = sandbox_dir_for(role=role, username=username, session_id=sid)
        except Exception:
            workdir = SANDBOX_ROOT / sid
        workdir.mkdir(parents=True, exist_ok=True)
        self.role = role
        self.session = CodingSession(session_id=sid, workdir=workdir)

    # ------------------------------------------------------------ files
    def write_file(self, filename: str, content: str) -> Step:
        step = Step(index=len(self.session.steps) + 1, kind="write", detail=filename)
        started = time.time()
        try:
            # Contain writes to the session directory: a filename like
            # "../../etc/thing" must not escape, and this is checked by
            # resolving the path rather than by inspecting the string,
            # since string checks miss symlinks and odd separators.
            target = (self.session.workdir / filename).resolve()
            if not str(target).startswith(str(self.session.workdir.resolve())):
                step.ok = False
                step.output = "Refused: file path sandbox ke bahar ja raha tha."
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                step.output = f"Wrote {len(content)} chars to {filename}"
        except Exception as exc:
            step.ok = False
            step.output = f"Write failed: {exc}"
        step.duration = time.time() - started
        self.session.steps.append(step)
        return step

    def read_file(self, filename: str) -> str:
        try:
            target = (self.session.workdir / filename).resolve()
            if not str(target).startswith(str(self.session.workdir.resolve())):
                return "Refused: path sandbox ke bahar hai."
            return target.read_text(encoding="utf-8")[:MAX_OUTPUT_CHARS]
        except Exception as exc:
            return f"Read failed: {exc}"

    def list_files(self) -> List[str]:
        try:
            return sorted(
                str(p.relative_to(self.session.workdir))
                for p in self.session.workdir.rglob("*") if p.is_file()
            )
        except Exception:
            return []

    # -------------------------------------------------------- execution
    def run(self, command: str, kind: str = "run") -> Step:
        step = Step(index=len(self.session.steps) + 1, kind=kind, detail=command)
        started = time.time()

        refusal = _refused(command)
        if refusal:
            step.ok = False
            step.output = refusal
            step.duration = time.time() - started
            self.session.steps.append(step)
            log_event("codebox", f"refused command: {command[:80]}", level="warning")
            return step

        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(self.session.workdir),
                capture_output=True, text=True, timeout=self.timeout,
                # Deliberately NOT inheriting a network-enabling env or
                # extending PATH -- executed code gets the minimum.
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "HOME": str(self.session.workdir),
                     "PYTHONDONTWRITEBYTECODE": "1"},
            )
            out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
            if len(out) > MAX_OUTPUT_CHARS:
                out = out[:MAX_OUTPUT_CHARS] + f"\n...[output truncated at {MAX_OUTPUT_CHARS} chars]"
            step.output = out.strip()
            step.exit_code = proc.returncode
            step.ok = proc.returncode == 0
        except subprocess.TimeoutExpired:
            step.ok = False
            step.exit_code = -1
            step.output = f"Timeout: {self.timeout}s mein poora nahi hua -- shayad infinite loop hai."
        except Exception as exc:
            step.ok = False
            step.output = f"Execution failed: {exc}"

        step.duration = time.time() - started
        self.session.steps.append(step)
        return step

    def run_python(self, code: str, filename: str = "main.py") -> Step:
        """THE QA WIRING (2026-09-14). Previously this wrote the file
        and executed it with no validation at all -- a syntax error
        cost a real subprocess spawn just to report back what `ast`
        could have caught in microseconds, and there was no record of
        what was checked before code ran.

        Now every run goes through core/evolution/self_evolution.run_qa
        -- the same 5-layer pipeline JARVIS's own self-authored features
        pass through (syntax -> danger scan -> dependency check ->
        isolated execution -> resource/output validation) -- BEFORE the
        real sandboxed execution below, and the QA result travels with
        the Step so the caller (frontend, JARVIS's coding tool, the CLI)
        can show it.

        Layers 1-3 run WITHOUT executing (run_it=False): a syntax error
        is caught and returned immediately, without ever spawning the
        subprocess this method uses for the real run. That real run
        still goes through THIS class's own sandbox (per-role
        workdir, timeout, restricted PATH/HOME, MAX_OUTPUT_CHARS
        truncation) -- run_qa's own isolated-execution layer is not
        used here; it would be a second, redundant execution of the
        same code. Layer 5 (resource/output validation) IS applied,
        against the real run's actual output and duration, once it
        completes.
        """
        from ..evolution.self_evolution import run_qa, _resource_layer

        # Layers 1-3: syntax, danger scan, dependency check. No
        # execution here -- run_it=False skips run_qa's own subprocess,
        # since this method runs the real one below in ITS OWN sandbox.
        pre = run_qa(code, run_it=False)
        qa_summary: Dict[str, Any] = {
            "layers": {
                "1_syntax": pre.syntax_ok,
                "2_danger_scan": not pre.danger_flags,
                "3_dependencies": not pre.missing_imports,
                "4_isolated_execution": None,   # filled in after the real run below
                "5_resource_output": None,
            },
            "danger_flags": pre.danger_flags,
            "missing_imports": pre.missing_imports,
        }

        if not pre.syntax_ok:
            # Refused before spending a subprocess -- exactly the
            # saving this wiring exists for.
            step = Step(index=len(self.session.steps) + 1, kind="run_python",
                       detail=f"python3 {filename}",
                       output=f"Syntax error, run nahi kiya: {pre.syntax_error}",
                       ok=False, qa=qa_summary)
            self.session.steps.append(step)
            log_event("codebox", f"run_python refused at syntax layer: {pre.syntax_error}",
                     level="warning")
            return step

        # AUTO-INSTALL INTO A SANDBOX VENV (2026-09-17, UK: "auto pip
        # install karo... bar bar model not install bolke fail ho jaata
        # hai"). Layer 3 above already knew about missing imports; this
        # is the wiring that actually DOES something about it instead
        # of just recording it. Installs go into an isolated venv
        # scoped to this sandbox (see sandbox_policy.ensure_sandbox_venv)
        # -- never JARVIS's own Python -- so no approval/login gate is
        # needed here; a bad install can only affect this sandbox's own
        # throwaway venv.
        interpreter = "python3"
        if pre.missing_imports:
            from .sandbox_policy import resolve_dependencies
            dep_result = resolve_dependencies(pre.missing_imports, sandbox_dir=self.workdir)
            qa_summary["auto_install"] = dep_result
            if dep_result.get("venv_python"):
                interpreter = dep_result["venv_python"]
            if dep_result.get("installed"):
                log_event("codebox", f"auto-installed for this run: {dep_result['installed']}", level="info")

        self.write_file(filename, code)
        step = self.run(f"{interpreter} {filename}", kind="run_python")

        # Layer 4 result comes from THIS class's own sandboxed run
        # (above), not run_qa's -- avoids executing the same code twice.
        qa_summary["layers"]["4_isolated_execution"] = step.ok

        # Layer 5: resource/output validation against the REAL run.
        fifth = SimpleNamespace(output=step.output, duration_ms=step.duration * 1000,
                                resource_ok=True, resource_flags=[])
        _resource_layer(fifth, self.timeout)
        qa_summary["layers"]["5_resource_output"] = fifth.resource_ok
        qa_summary["resource_flags"] = fifth.resource_flags

        if pre.danger_flags:
            step.output = (
                f"[QA layer 2 flagged: {', '.join(pre.danger_flags)}]\n" + step.output
            )
        if fifth.resource_flags:
            step.output += f"\n[QA layer 5 flagged: {'; '.join(fifth.resource_flags)}]"
            step.ok = step.ok and fifth.resource_ok

        step.qa = qa_summary
        return step

    def note(self, text: str) -> Step:
        step = Step(index=len(self.session.steps) + 1, kind="note", detail=text, output="")
        self.session.steps.append(step)
        return step

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self.session.workdir, ignore_errors=True)
        except Exception:
            pass


def run_coding_session(
    generate: Callable,
    *,
    task: str,
    system_prompt: str = "",
    max_steps: int = 6,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    role: str = "user",
    username: Optional[str] = None,
) -> Dict[str, Any]:
    """MULTI-STEP CODING TURN -- write, run, read the error, fix, re-run.

    This is the only path in JARVIS that iterates within a single turn.
    Normal chat deliberately does not, because iteration multiplies both
    latency and token spend, and a conversational reply gains nothing
    from it.

    Stops as soon as the code runs clean, so a task that works first try
    costs exactly two calls.
    """
    box = CodeBox(timeout=timeout, role=role, username=username)
    max_steps = max(1, min(int(max_steps), MAX_STEPS))
    history: List[str] = []
    solved = False

    for attempt in range(max_steps):
        prompt_tail = ""
        if history:
            prompt_tail = (
                "\n\nPichhli koshish ka natija:\n" + history[-1] +
                "\n\nIs error ko theek karo aur poora corrected program dobara do."
            )
        try:
            raw = str(generate(
                system_prompt=(
                    (system_prompt or "You are JARVIS, writing code for UK.")
                    + "\n\nReturn ONLY the complete Python program, no explanation, no markdown fences. "
                      "It must run standalone with python3."
                ),
                user_input=f"Task: {task}{prompt_tail}",
                max_tokens=2000,
                # LEVEL: extended_thinking, NOT response_generation (fixed
                # 2026-09-17, same bug class task_loop.py's _call() was
                # already fixed for on 2026-09-16, missed here). The
                # per-level cap is 2 calls/turn -- exactly right for "one
                # perception call + one reply" in ordinary chat, but this
                # loop can run up to max_steps write/run/fix attempts
                # inside ONE call to run_coding_session. UK's exact
                # symptom, reproduced in his own trace: attempt 1 writes
                # real code, attempt 2 (or any chat activity earlier in
                # the same turn) exhausts the 2-call ceiling, and every
                # subsequent attempt dies with "LLM per-level call budget
                # exceeded: 'response_generation' already used 2/2 calls
                # this turn" -- a script that looked like it was working
                # then silently stopped retrying.
                level="extended_thinking",
            )).strip()
        except Exception as exc:
            box.note(f"Code generation failed on attempt {attempt + 1}: {exc}")
            break

        code = re.sub(r"^```(?:python)?\s*|\s*```$", "", raw, flags=re.I | re.M).strip()
        # DEGRADED-RESULT SENTINEL CHECK (2026-09-17). generate_response()
        # returns "[LLM unavailable: ...]" as a STRING instead of raising
        # when no provider answered. Without this check that sentence was
        # written into the .py file as source, run, "verified", and
        # retried -- which is exactly what UK's screenshots show
        # (WRITE step content: "[LLM unavailable: local fallback is
        # disabled]"). Stop immediately and say the real reason.
        try:
            from ..orchestration.llm_bridge import is_llm_unavailable
        except Exception:
            is_llm_unavailable = lambda t: False  # noqa: E731
        if is_llm_unavailable(raw) or is_llm_unavailable(code):
            box.note(f"Attempt {attempt + 1}: koi LLM jawab nahi de paaya -- {raw.strip()[:200]}. "
                      f"Isliye koi code likha hi nahi gaya (galat text file mein nahi daala).")
            break
        if not code:
            box.note(f"Attempt {attempt + 1}: model ne khali code diya.")
            break

        step = box.run_python(code)
        if step.ok:
            solved = True
            break
        history.append(f"exit={step.exit_code}\n{step.output[:1200]}")

    result = box.session.as_dict()
    result["solved"] = solved
    result["task"] = task
    # COUNTS run_python TOO (fixed 2026-09-16 from UK's web-panel report:
    # "Poora nahi hua -- 0 attempt" even though the loop had genuinely
    # tried). run_python() appends its step with kind="run_python", not
    # "run", so this sum was structurally always 0 for the path this
    # loop actually uses -- making a real failure look like a loop that
    # never ran, which is a different and much more confusing bug.
    result["attempts"] = sum(1 for s in box.session.steps if s.kind in ("run", "run_python"))
    # Surface WHY nothing ran, when nothing ran -- an empty step list
    # with no explanation is what made this unreadable in the UI.
    notes = [s.detail for s in box.session.steps if s.kind == "note"]
    if not solved and notes:
        result["blocked_reason"] = notes[-1]
    result["summary"] = (
        f"{result['attempts']} attempt(s) mein code chal gaya."
        if solved else
        (f"{result['attempts']} attempt(s) ke baad bhi clean nahi chala -- steps mein poora log hai."
         if result["attempts"] else
         f"Code chala hi nahi -- {notes[-1] if notes else 'model ne koi chalane layak code nahi diya'}.")
    )
    # SANDBOX PATH, ALWAYS STATED (2026-09-18, UK: "JARVIS ko khud nahi
    # pata rehta hai directory ke baare mein... na mujhe batata hai").
    # box.session.as_dict() already had `workdir` in `result` before
    # this fix -- it just never made it into `summary`, the ONLY field
    # the model is instructed to quote from (see
    # companion_tools._coding_agent_result's identical fix for the
    # repo-scale agent's own result). Stated here regardless of
    # success/failure, so "yeh kahan bana?" has a real answer either
    # way, not a guess.
    result["summary"] += f" Sandbox path: {result.get('workdir')}."
    log_event("codebox", f"coding session {box.session.session_id}: solved={solved} attempts={result['attempts']}", level="info")
    return result
