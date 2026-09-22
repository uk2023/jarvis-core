from __future__ import annotations

"""HTTP surface for the codebox, uploads and extended thinking.

Every route here takes the speaker from the auth dependency rather than
from the request body. A body-supplied username would let any caller
claim to be UK and land in his sandbox, which is the whole point of
having per-role sandboxes in the first place.
"""

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .routes_auth import get_speaker
from . import database


def _fresh_llm_turn(brain) -> None:
    """Starts a NEW LLM budget turn for a standalone action (2026-09-17,
    the real cause behind UK's screenshots: codebox/coding-agent panel
    runs failing with 'LLM call budget exceeded: 8 calls per turn' even
    on the very first thing he did after opening the tab).

    begin_turn_budget() is ONLY ever called from blueprint_brain.py's
    think_and_respond() -- the normal chat entrypoint -- and nothing,
    anywhere, ever calls it again to END a turn. _turn_active simply
    stays True for the rest of the process's life once any chat has
    happened. So a CodeBox/Coding-Agent action triggered from this
    HTTP surface (no think_and_respond() involved) was silently
    inheriting whatever was LEFT of the budget from the last unrelated
    chat message -- sometimes already at the 8-call ceiling before the
    agent's own first generate() call even ran. Every entry point that
    does NOT go through think_and_respond() (this file's three run
    routes, cli.py's /codebox and /coding_agent, codebase.py) must
    start its own fresh turn, exactly as think_and_respond() does,
    because each one IS its own logical unit of work the user just
    asked for -- not a continuation of an unrelated chat turn from
    however long ago."""
    begin = getattr(getattr(brain, "llm", None), "begin_turn_budget", None)
    if callable(begin):
        begin()


def _live_brain():
    """The running organism's brain. integration.py holds it as a
    module-level global that is set at startup, so it must be read
    through the module rather than imported by value -- importing the
    name once would capture None from before startup."""
    from . import integration
    return getattr(integration, "brain", None)


def _record_standalone_trace(brain, name: str, arguments: Dict[str, Any], result: Any) -> None:
    """Appends this HTTP-surface call to brain.last_tool_call_trace, the
    SAME list cli.py's /tool_trace reads (see tool_registry.py's
    run_tool_loop). Codebox/coding-agent calls made from these REST
    routes bypass the normal chat tool-loop entirely (that is the whole
    point of a dedicated surface -- see this module's own docstring),
    which meant they were previously invisible to /tool_trace even
    though they are exactly the kind of action UK wants traceable.
    Best-effort: a tracing failure must never break the actual call."""
    if brain is None:
        return
    try:
        trace = getattr(brain, "last_tool_call_trace", None)
        if not isinstance(trace, list):
            trace = []
        trace.append({"name": name, "arguments": arguments,
                       "result": result if isinstance(result, dict) else {"value": result},
                       "surface": "http"})
        brain.last_tool_call_trace = trace[-20:]   # bounded, same posture as the chat loop's
    except Exception:
        pass

router = APIRouter(prefix="/api", tags=["codebox"])


def _principal(speaker: Any) -> Dict[str, Any]:
    """Normalise whatever get_speaker() returned into a plain dict.

    THE CRASH (fixed 2026-09-14). get_speaker() returns a Speaker
    DATACLASS, not a dict. This called .get() on it, so every request to
    /api/think/stream, /api/codebox/* and /api/upload raised
    `AttributeError: 'Speaker' object has no attribute 'get'` --
    a 500 and a full traceback in the CLI on EVERY turn.

    routes_frontend_v6.py had it right (speaker.as_dict()); this file
    did not, and the two were written a round apart. Accepting both
    shapes here means a future change to either side cannot re-break it
    the same way.
    """
    if speaker is None:
        data: Dict[str, Any] = {}
    elif isinstance(speaker, dict):
        data = speaker
    elif hasattr(speaker, "as_dict"):
        try:
            data = speaker.as_dict() or {}
        except Exception:
            data = {}
    else:
        data = {
            "role": getattr(speaker, "role", None),
            "username": getattr(speaker, "username", None),
            "is_verified": getattr(speaker, "is_verified", None),
        }

    # Speaker has NO 'username' field -- it carries display_name. Reading
    # "username" off it returned None for everybody, which silently sent
    # every authenticated user into the shared guest sandbox.
    username = data.get("username") or data.get("display_name")

    role = data.get("role") or "guest"
    role = role.value if hasattr(role, "value") else str(role)
    return {
        "role": role.lower(),
        "username": username,
        "is_verified": bool(data.get("is_verified")),
    }


def _sandbox_identity(p: Dict[str, Any], request: Any = None) -> Dict[str, Any]:
    """Who owns the sandbox for this call.

    WHY GUESTS ARE ALLOWED HERE (fixed 2026-09-14). Every codebox route
    used to require is_verified, so an unauthenticated caller got 401 on
    run, task, files AND upload -- which is why the CodeBox page showed
    "error fetching" for everything and the build button appeared dead.
    UK had no account at the time and no way to make one from the web.

    Running code in your OWN isolated sandbox is not a privileged
    operation -- it touches nothing outside that directory (see
    sandbox_policy.py). What IS privileged is system-level work, and
    that check lives separately and still requires owner/co-owner.

    A guest gets a sandbox keyed to their connection, so two guests do
    not share a directory.
    """
    if p["is_verified"] and p["username"]:
        return {"role": p["role"], "username": p["username"]}
    ip = "anon"
    try:
        if request is not None and request.client:
            ip = (request.client.host or "anon").replace(":", "_").replace(".", "_")
    except Exception:
        pass
    return {"role": "user", "username": f"guest_{ip}"}


# ------------------------------------------------------------------ uploads
@router.post("/upload")
async def upload_file(file: UploadFile = File(...), request: Request = None, speaker: Dict = Depends(get_speaker)):
    """Accept a file or archive into the CALLER'S OWN sandbox.

    Nothing is executed here. Archives are extracted with path-escape
    and symlink protection, then scanned; the response tells the user
    what was found so they can decide before running anything.
    """
    from core.skills.upload_guard import accept_upload

    p = _principal(speaker)
    who = _sandbox_identity(p, request)

    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"File padhi nahi gayi: {exc}")

    result = accept_upload(data, file.filename or "upload",
                           role=who["role"], username=who["username"])
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "note": result.get("note")}
    return result


@router.get("/uploads")
async def list_my_uploads(request: Request = None, speaker: Dict = Depends(get_speaker)):
    from core.skills.upload_guard import list_uploads
    p = _principal(speaker)
    who = _sandbox_identity(p, request)
    return {"uploads": list_uploads(role=who["role"], username=who["username"])}


# ------------------------------------------------------------------ codebox
class CodeRunRequest(BaseModel):
    code: str
    filename: Optional[str] = "main.py"


class CodeTaskRequest(BaseModel):
    task: str
    max_steps: int = 4


@router.post("/codebox/run")
async def codebox_run(req: CodeRunRequest, request: Request = None, speaker: Dict = Depends(get_speaker)):
    """Run code the user wrote, in their own sandbox. No LLM involved."""
    from core.skills.codebox import CodeBox

    p = _principal(speaker)
    who = _sandbox_identity(p, request)
    if not (req.code or "").strip():
        raise HTTPException(status_code=400, detail="Code khali hai.")

    box = CodeBox(role=who["role"], username=who["username"])
    step = box.run_python(req.code, filename=req.filename or "main.py")
    payload = step.as_dict() if hasattr(step, "as_dict") else dict(step)
    payload["workdir"] = str(box.session.workdir)
    payload["files"] = box.list_files()
    _record_standalone_trace(_live_brain(), "codebox_run",
                              {"filename": req.filename}, payload)
    return payload


@router.post("/codebox/task")
async def codebox_task(req: CodeTaskRequest, request: Request = None, speaker: Dict = Depends(get_speaker)):
    """Ask JARVIS to write and iterate on code -- the multi-step path."""
    p = _principal(speaker)
    who = _sandbox_identity(p, request)

    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")
    _fresh_llm_turn(brain)   # see _fresh_llm_turn's docstring

    from core.skills.codebox import run_coding_session
    result = run_coding_session(
        brain.llm.generate_response,
        task=req.task,
        system_prompt="You are JARVIS, writing code for the user.",
        max_steps=max(1, min(int(req.max_steps), 12)),
        role=who["role"], username=who["username"],
    )
    _record_standalone_trace(brain, "codebox_task", {"task": req.task}, result)
    return result


@router.get("/codebox/files")
async def codebox_files(request: Request = None, speaker: Dict = Depends(get_speaker)):
    from core.skills.codebox import CodeBox
    p = _principal(speaker)
    who = _sandbox_identity(p, request)
    box = CodeBox(role=who["role"], username=who["username"])
    return {"workdir": str(box.session.workdir), "files": box.list_files()}


# --------------------------------------------------------- extended thinking
class ThinkRequest(BaseModel):
    message: str
    mode: str = "auto"          # off | on | auto
    context: str = ""
    effort: str = "medium"      # low | medium | high | aggressive | deep
    # THREAD IDENTITY (2026-09-19) -- previously absent entirely, which
    # meant this SSE route had no way to know WHICH chat thread it was
    # part of for a full-thread search (see thread_search.py). Defaults
    # to "main_session" for backward compatibility with any caller that
    # doesn't send it yet, matching routes_frontend_v6.py's own fallback.
    session_id: str = "main_session"


@router.post("/think/stream")
async def think_stream_route(req: ThinkRequest, speaker: Dict = Depends(get_speaker)):
    """Server-sent events so the UI renders each reasoning stage as it
    arrives, rather than waiting for the whole run."""
    from core.cognition.thinking import think_stream
    from core.identity.persona import persona_prompt
    from core.identity.user_memory import context_block

    p = _principal(speaker)
    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")

    persona = persona_prompt(role=p["role"], speaker_name=p["username"],
                             is_verified=p["is_verified"])
    user_ctx = context_block(p["username"], role=p["role"])

    # CONVERSATION CONTINUITY CONTEXT (2026-09-18, UK's Bug 3: "unnecessary
    # respond kar raha hai... discuss bhi nahi kar paya" -- traced to this
    # route building combined_ctx from ONLY persona identity info
    # (context_block), never from the Conversation Intelligence Layer.
    # The main chat pipeline gets active_focus/conversation_focus/recap
    # via build_response_brief(); this SSE "Extended Thinking" pipeline
    # had none of that, so "understand" stage genuinely had no idea what
    # topic/entity was already active and had to ask -- not a reasoning
    # failure, a missing-input failure.
    # 2026-09-20: formatting logic MOVED into ConversationContinuityLayer.
    # format_relevant_context_text() -- see that method's docstring for
    # why (this inline copy was exactly the kind of divergence-between-
    # surfaces bug this project keeps re-discovering; now there is one
    # place that can go stale instead of two).
    continuity_ctx = ""
    if hasattr(brain, "conversation_continuity"):
        continuity_ctx = brain.conversation_continuity.format_relevant_context_text()

    # THREAD-WIDE SEARCH (2026-09-19, UK's explicit architecture: a
    # user never gives JARVIS a precise time interval -- they just
    # reference something naturally ("humne pehle decide kiya tha...")
    # and the intelligence layer must scan the FULL chat thread to find
    # it, no matter how old. Only runs when the message actually reads
    # as a backward reference (has_backward_reference -- a cheap native
    # check, not an LLM call) so this never adds latency to an ordinary
    # turn; the scan itself is a single native pass over this thread's
    # persisted history (thread_search.py), never an LLM call, and only
    # the found snippet -- never the whole thread -- reaches the brief.
    try:
        from core.cognition.thread_search import (
            has_backward_reference, extract_time_hint_hours,
            search_thread_for_reference, format_thread_matches,
        )
        if has_backward_reference(req.message):
            rows = database.get_history_rows(req.session_id)
            thread_messages = [
                {
                    "sender": "user" if r["sender"] == "user" else "jarvis",
                    "text": r["text"],
                    "timestamp": database._timestamp_to_epoch_ms(r["timestamp"]) / 1000.0,
                }
                for r in rows
            ]
            time_hint = extract_time_hint_hours(req.message)
            matches = search_thread_for_reference(
                req.message, thread_messages, max_results=3, time_hint_hours=time_hint,
            )
            if matches and hasattr(brain, "conversation_continuity"):
                brain.conversation_continuity.set_retrieved_reference(format_thread_matches(matches))
    except Exception:
        pass  # thread search is an enhancement -- never block a turn over it

    combined_ctx = "\n\n".join(x for x in (req.context, continuity_ctx, user_ctx) if x)

    def event_source():
        try:
            # MULTI-TURN STEP COMPLETION, UNIFIED WITH THINKING
            # (2026-09-14, UK: "multi-turn/step-turn sab extended
            # thinking se hi hoga on karne pe"). If the mode is not
            # 'off' AND this turn wants a task carried out rather than
            # discussed, this runs the full plan/act/verify loop
            # instead of the staged reasoner. thinking.py's understand/
            # explore/critique stages answer a QUESTION; task_loop
            # actually CARRIES OUT a task to a verified conclusion.
            #
            # REVERTED 2026-09-18 (UK caught this on-device, two days
            # of frustration traced back to it): a 2026-09-16 change
            # here made `req.mode == "extended"` bypass this decision
            # entirely -- "choosing Extended IS the instruction" -- so
            # every single Extended Thinking turn launched a full
            # unattended TaskLoop no matter what the message said.
            #
            # SUPERSEDED AGAIN, SAME DAY: the first fix used a keyword
            # list ("no coding", "pehle discuss", ...) to decide
            # discuss-vs-act. UK explicitly rejected that as still a
            # brittle, single-language, hardcoded patch -- his exact
            # point: "LLM kaunsa filter ho sakta hai -- intent se
            # filter ho sakta hai", i.e. this is a judgment call, and
            # judgment calls are what the LLM is FOR in this
            # architecture, not something a phrase table can
            # substitute for. classify_task_disposition() (Conversation
            # Intelligence Layer, phase 1 -- see
            # core/cognition/conversation_intelligence.py) makes that
            # judgment via an actual LLM classification call, in any
            # language or phrasing, with a zero-cost native shortcut
            # only for the one case that IS genuinely deterministic (a
            # plain question), and an honest, logged degraded fallback
            # when the LLM truly can't be reached -- never a keyword
            # table pretending to be understanding.
            # SUPERSEDED AGAIN, 2026-09-18 SAME DAY, second correction:
            # UK's exact words -- "extended thinking is not equal to
            # coding agent" -- and the concrete architectural gap he
            # named: research/planning are genuine capabilities in
            # their own right, hireable individually, distinct from
            # "run the full build-and-execute loop". A binary discuss-
            # vs-act classifier can't express "deep-think this with me
            # but don't write any code" -- it can only ever pick
            # think_stream() (shallow staged reasoner) or the full
            # TaskLoop (which touches the sandbox). classify_capability()
            # is the real four-way authority UK asked for in section 7
            # ("JARVIS decides... which worker is needed"):
            # discussion / research / planning / full_build. Only
            # full_build reaches TaskLoop.stream() (the complete
            # understand->plan->execute->verify loop that writes and
            # runs code); research and planning reach
            # TaskLoop.stream_capability() (understand-only, or
            # understand+plan-only -- pure reasoning, nothing executed).
            from core.orchestration.task_loop import TaskLoop
            from core.cognition.conversation_intelligence import (
                classify_capability, DISCUSSION, RESEARCH, PLANNING, FULL_BUILD,
                EDITING, DEBUG_FIX,
            )
            capability = {"capability": DISCUSSION, "source": "mode_off"}
            if req.mode != "off":
                capability = classify_capability(
                    getattr(brain, "llm", None), req.message,
                    native_intent=None,
                )
                yield f"data: {json.dumps({'type': 'capability', **capability}, ensure_ascii=False)}\n\n"

                # CLI/WEB EXTENDED-THINKING VISIBILITY GAP (2026-09-19, UK:
                # "extended thinking use ke baad bhi false dikhata hai CLI
                # mein" -- and separately, the live SSE steps shown on the
                # web frontend never appear in the CLI at all). Root cause:
                # CLI's monitor panel (cli.py's "4e. EXTENDED THINKING")
                # only ever reads brain.last_thinking_decision, which is
                # set exclusively by brain.py's OWN separate THINK FIRST
                # block (the CLI/API '/think on' toggle from an earlier
                # pass) -- this SSE route (the actual Extended Thinking UI
                # button on the web frontend) is a completely different
                # code path that never touched that attribute. Since brain
                # is the one shared organism instance both CLI and web
                # talk to, setting it here makes a web-originated Extended
                # Thinking decision visible in the CLI monitor too. Only
                # set inside this if-block -- an off-mode turn genuinely
                # did no thinking and must not claim otherwise. This does
                # NOT yet make CLI's own /think toggle drive this SSE
                # route (the reverse direction) -- that would need CLI to
                # call classify_capability()/TaskLoop itself, a larger
                # unification left for a future pass.
                try:
                    brain.last_thinking_decision = {
                        "think": capability["capability"] != DISCUSSION,
                        "mode": f"web_extended:{capability['capability']}",
                        "reason": f"Capability classifier ({capability.get('source', '?')}) chose '{capability['capability']}' for this web turn.",
                    }
                except Exception:
                    pass

            # SECOND GATE: even when the classifier says full_build,
            # JARVIS's own continuity layer must also agree (UK
            # requirement section 7: "coding agent tabhi call ho jab
            # ... conversation intelligence bole ki user chahta hai
            # now code" -- the continuity layer, not the LLM alone, is
            # the final authority on whether the coding agent actually
            # fires). This also carries forward the "not right after a
            # correction" and "not mid-discussion" guards already in
            # should_invoke_coding_agent().
            chosen = capability["capability"]
            if chosen == FULL_BUILD and not (
                hasattr(brain, "conversation_continuity")
                and brain.conversation_continuity.should_invoke_coding_agent()
            ):
                chosen = PLANNING  # fall back to the safe, non-executing capability

            if chosen == FULL_BUILD:
                loop = TaskLoop(
                    brain.llm.generate_response, brain=brain,
                    role=p["role"], is_verified=p["is_verified"],
                    effort=req.effort, context=combined_ctx,
                )
                for event in loop.stream(req.message):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                return

            # BUG FIXED 2026-09-19 (UK caught this from real logs:
            # "Continue" inside Extended Thinking produced "What's being
            # asked: user wants me to continue something... ambiguous"
            # -- TaskLoop's _understand()/_plan() were never given
            # combined_ctx at all, even though it was built right above
            # for think_stream()'s benefit. Fixed by adding a `context`
            # param TaskLoop actually uses -- see task_loop.py's
            # __init__ comment. SEPARATELY, EDITING/DEBUG_FIX were
            # classify_capability() outcomes that had NO matching
            # branch here at all -- they fell through to plain
            # think_stream() instead of actually running the narrow
            # worker stream_capability() already supports for them.
            if chosen in (RESEARCH, PLANNING, EDITING, DEBUG_FIX):
                loop = TaskLoop(
                    brain.llm.generate_response, brain=brain,
                    role=p["role"], is_verified=p["is_verified"],
                    effort=req.effort, context=combined_ctx,
                )
                for event in loop.stream_capability(req.message, chosen):
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                return

            for event in think_stream(
                brain.llm.generate_response,
                user_input=req.message, mode=req.mode,
                context=combined_ctx, persona_prompt=persona,
                effort=req.effort,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/think/decide")
async def think_decide(req: ThinkRequest, speaker: Dict = Depends(get_speaker)):
    """What JARVIS would choose in AUTO mode for this message -- lets the
    UI show the toggle lighting up on its own, honestly."""
    from core.cognition.thinking import resolve_mode
    return resolve_mode(req.mode, req.message)


# ------------------------------------------------------------- step goals
class GoalRequest(BaseModel):
    goal: str
    max_steps: int = 6


@router.post("/goal/stepwise")
async def goal_stepwise(req: GoalRequest, speaker: Dict = Depends(get_speaker)):
    """Owner/co-owner only -- enforced inside run_goal_stepwise too."""
    p = _principal(speaker)
    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")
    result = brain.run_goal_stepwise(
        goal=req.goal, role=p["role"], is_verified=p["is_verified"],
        max_steps=req.max_steps,
    )
    if not result.get("allowed", True):
        raise HTTPException(status_code=403, detail=result.get("reason"))
    return result


@router.get("/sandbox/overview")
async def sandbox_overview_route(speaker: Dict = Depends(get_speaker)):
    from core.skills.sandbox_policy import sandbox_overview
    p = _principal(speaker)
    if p["role"] not in {"owner", "co_owner"} or not p["is_verified"]:
        raise HTTPException(status_code=403, detail="Sandbox overview sirf owner/co-owner ke liye.")
    return sandbox_overview()


@router.get("/diagnose")
async def diagnose_route(speaker: Dict = Depends(get_speaker)):
    """Read-only diagnostic report -- anyone signed in can see what
    JARVIS thinks is wrong with itself; applying a fix is restricted
    below."""
    from core.runtime.diagnostics import run_diagnostics
    return run_diagnostics(auto_fix=False)


class DiagnoseFixRequest(BaseModel):
    name: str = ""   # empty = apply every safe AUTO remedy


@router.post("/diagnose/fix")
async def diagnose_fix_route(req: DiagnoseFixRequest, speaker: Dict = Depends(get_speaker)):
    """Applying a remedy -- even an AUTO one -- is owner/co-owner only.
    A read-only report is fine for anyone; actually changing runtime
    state is not."""
    from core.runtime.diagnostics import run_diagnostics, apply_remedy
    p = _principal(speaker)
    if p["role"] not in {"owner", "co_owner"} or not p["is_verified"]:
        raise HTTPException(status_code=403, detail="Fix apply karna sirf owner/co-owner ke liye.")
    if req.name:
        return apply_remedy(req.name)
    return run_diagnostics(auto_fix=True)


# ------------------------------------------------- repo-scale coding agent
# (2026-09-16) The CodeBox panel above is single-script. These routes expose
# the REPO-SCALE agent (core/skills/coding_agent/) to the same frontend, so
# /codebox stops being a separate island: one panel, two depths of the SAME
# capability, both going through Brain -- never a second agent implementation.
class CodingAgentRequest(BaseModel):
    objective: str
    repo_path: Optional[str] = None
    max_iterations: int = 6


class CodingAgentApproval(BaseModel):
    approve: bool


@router.post("/coding_agent/run")
async def coding_agent_run(req: CodingAgentRequest, request: Request = None,
                            speaker: Dict = Depends(get_speaker)):
    """Same Brain method cli.py's /coding_agent calls -- not a parallel path."""
    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")
    if not (req.objective or "").strip():
        raise HTTPException(status_code=400, detail="objective required")
    _fresh_llm_turn(brain)   # see _fresh_llm_turn's docstring
    result = brain.run_coding_agent(
        req.objective, repo_path=req.repo_path or None,
        max_iterations=max(1, min(int(req.max_iterations), 20)),
    )
    _record_standalone_trace(brain, "run_coding_agent",
                              {"objective": req.objective, "repo_path": req.repo_path}, result)
    return result


@router.post("/coding_agent/approve")
async def coding_agent_approve(req: CodingAgentApproval, request: Request = None,
                                speaker: Dict = Depends(get_speaker)):
    """Answers a WAITING_APPROVAL pause -- the API half of the approval UI."""
    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")
    _fresh_llm_turn(brain)   # a paused task may resume long after an unrelated chat turn
    result = brain.resume_coding_agent(approve=bool(req.approve))
    _record_standalone_trace(brain, "resume_coding_agent", {"approve": req.approve}, result)
    return result


@router.get("/coding_agent/state")
async def coding_agent_state(request: Request = None, speaker: Dict = Depends(get_speaker)):
    """Full current task -- plan, observations, tool calls, verifications,
    diffs, pending approval. This is what a frontend workspace panel renders;
    returns an honest empty state when no run has happened, never a stub."""
    brain = _live_brain()
    if brain is None:
        raise HTTPException(status_code=503, detail="Organism abhi ready nahi hai.")
    task = getattr(brain, "_last_coding_task", None)
    if task is None:
        return {"task": None, "note": "Abhi tak koi coding-agent run nahi hua."}
    agent = getattr(brain, "_last_coding_agent", None)
    return {
        "task": task.as_dict(),
        "tools": agent.registry.list_tools() if agent is not None else [],
        "workspace": str(agent.workspace.root) if agent is not None else None,
    }
