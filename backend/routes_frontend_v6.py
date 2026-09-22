# -*- coding: utf-8 -*-
"""
Endpoints consumed by the V6 React/TypeScript frontend (web_frontend/,
built from JARVIS_v6-main). Every one of these used to be served by a
Node/Express mock (server.ts) that fabricated numbers with
Math.random(). None of that ships here -- every field below is read
from the live jarvis/brain/memory/goal_manager/evolution objects via
backend/integration.py, or from the same SQLite chat history used by
the CLI and the legacy dashboard.

Endpoint <-> frontend contract (see web_frontend/src/types.ts + App.tsx):
    GET    /api/organism/state        -> OrganismTelemetry (no wrapper)
    GET    /api/memory/engrams        -> { engrams: EngramFact[] }
    POST   /api/memory/engrams        -> { engram: EngramFact }
    DELETE /api/memory/engrams/{id}   -> { status }
    GET    /api/memory/pending_rules  -> { rules: PendingSelfRule[] }
    POST   /api/memory/pending_rules/{id}/confirm  -> { status, rule }
    POST   /api/memory/pending_rules/{id}/reject   -> { status, rule }
    GET    /api/memory/pending_rules/{id}/explain  -> { rule, status, evidence }
    GET    /api/memory/contested_facts -> { facts: ContestedFact[] }
    POST   /api/memory/contested_facts/{id}/resolve -> { status, current_value }
    GET    /api/autonomy/state        -> { goals, proposals }
    GET    /api/autonomy/standing_instructions     -> { instructions: StandingInstruction[] }
    DELETE /api/autonomy/standing_instructions/{id} -> { status }
    POST   /api/autonomy/trigger-idle -> { goal: CuriosityGoal }
    POST   /api/chat                  -> { jarvisMessage: ChatMessage }
"""
import json
import resource
import time
import traceback
import asyncio

from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from . import database
from . import integration
from .ws_manager import debug_log
from .trace_utils import real_turn_trace, turn_trace_to_json, turn_trace_summary, extracted_fact_from_trace
from core.organism.organ_descriptions import describe_organ

router = APIRouter()

# BUILD/DEPLOY VERIFICATION (2026-09-22, UK: "not working neither frontend
# nor backend" after a tarball that -- on inspection -- had the fix in it).
# The most likely explanation for "I shipped the fix but it's not there" is
# a stale server process still running the OLD code from before extraction/
# restart -- something no amount of code review from this side can rule
# out. This endpoint exists so THAT can be checked directly instead of
# guessed at: hit it after every deploy, before testing anything else.
# If read_uploaded_file is missing from tool_names below, the running
# process is not this build -- restart it, don't keep debugging the code.
_BUILD_MARKER = "2026-09-22-attachment-fix-v2"


@router.get("/api/debug/build_info")
async def build_info():
    from core.orchestration.tool_registry import build_tool_schemas
    try:
        tool_names = sorted(t.get("function", {}).get("name", "?") for t in build_tool_schemas())
    except Exception as exc:
        tool_names = [f"<build_tool_schemas() failed: {exc}>"]
    return {
        "build_marker": _BUILD_MARKER,
        "read_uploaded_file_registered": "read_uploaded_file" in tool_names,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
    }


# =====================================================================
# HELPERS
# =====================================================================

def _resident_memory_mb() -> float:
    """
    Real resident-set-size of THIS process, in MB. Uses the stdlib
    `resource` module (ru_maxrss is KB on Linux/Android/Termux, which
    is the deployment target here) instead of pulling in psutil as a
    dependency just for one number.
    """
    try:
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024.0, 1)
    except Exception:
        return 0.0


def _knowledge_to_engram(item) -> dict:
    """Knowledge dataclass -> EngramFact shape (src/types.ts)."""
    d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
    return {
        "id": d.get("knowledge_id"),
        "subject": d.get("subject"),
        "predicate": d.get("predicate"),
        "value": d.get("value"),
        "confidence": d.get("confidence", 0.5),
        "importance": d.get("importance", 0.5),
        "evidenceCount": d.get("evidence_count", 1),
        "source": d.get("source") or "unknown",
        # Provenance refinement (2026-09-11): distinguishes "verified"
        # (externally checked / UK-confirmed) from "llm_unverified"
        # (JARVIS's own guess, nothing checked it) vs "user_stated" vs
        # "unknown" (legacy rows). See core/memory/semantic_memory.py.
        "sourceType": d.get("source_type") or "unknown",
        "tags": d.get("tags") or [],
        "createdAt": int((d.get("created_at") or time.time()) * 1000),
        "updatedAt": int((d.get("updated_at") or time.time()) * 1000),
        "faissId": d.get("faiss_id", 0) or 0,
        # SemanticMemory doesn't track a separate pending/accepted
        # state on Knowledge itself -- anything actually persisted
        # here already passed through KnowledgeBuilder/SelfEvaluator
        # (or was inserted directly via this API), so it's accurate
        # to report it as ACCEPTED rather than invent a fake pipeline
        # stage the object doesn't actually carry.
        "status": "ACCEPTED",
    }


def _goal_to_curiosity_goal(g: dict) -> dict:
    origin = g.get("origin", "user")
    if origin not in ("user", "curiosity", "self"):
        origin = "self"
    return {
        "id": g.get("id"),
        "text": g.get("text"),
        "priority": g.get("priority", 0.5),
        "status": g.get("status", "pending"),
        "origin": origin,
        "progress": g.get("progress") or [],
        "createdAt": int((g.get("created_at") or time.time()) * 1000),
    }


def _proposal_to_evolution_proposal(p: dict) -> dict:
    trigger = p.get("trigger") or {}
    return {
        "id": p.get("id"),
        "target": p.get("target"),
        "reason": p.get("reason"),
        "status": p.get("status", "PROPOSED"),
        "score": trigger.get("evaluation_score", 0.5),
        "createdAt": int((p.get("created_at") or time.time()) * 1000),
    }


# =====================================================================
# GET /api/organism/state
# =====================================================================

@router.get("/api/organism/state")
async def organism_state():
    jarvis = integration.jarvis
    if jarvis is None:
        return JSONResponse(
            {"status": "error", "message": "Organism not initialized in this process."},
            status_code=503,
        )

    try:
        hb = jarvis.heartbeat.status() if hasattr(jarvis, "heartbeat") and jarvis.heartbeat else {}
        beat_count = hb.get("beat_count", 0)
        is_idle = hb.get("is_idle", True)
        interval = hb.get("interval", 5.0) or 5.0
        uptime = hb.get("uptime", 0.0)

        brain = jarvis.get_organ("brain") if hasattr(jarvis, "get_organ") else None
        brain_status = brain.status() if brain and hasattr(brain, "status") else {}

        organs_status = jarvis.get_organ_status() if hasattr(jarvis, "get_organ_status") else {}
        organs = []
        for name, info in organs_status.items():
            attached = info.get("attached", False)
            organs.append({
                "name": name,
                "classType": info.get("type", "Subsystem"),
                "isAttached": attached,
                "role": describe_organ(jarvis, name, info),
                "metrics": "online" if attached else "offline",
                "health": "green" if attached else "red",
            })

        # Async learning queue lives inside Brain, not jarvis.organs --
        # surface it as one more organ row so the web UI sees it too.
        queue_status = brain_status.get("async_learning_queue", {})
        organs.append({
            "name": "async_learning_queue",
            "classType": "Background Thread",
            "isAttached": bool(queue_status.get("alive", False)),
            "role": "Ordered background learning worker (response sync, learning async)",
            "metrics": (
                f"pending={queue_status.get('pending', 0)} "
                f"processed={queue_status.get('processed', 0)} "
                f"failed={queue_status.get('failed', 0)}"
            ),
            "health": "green" if queue_status.get("alive") else "yellow",
        })

        # "llm" is likewise never a registered jarvis organ -- it's
        # just brain.llm assigned post-hoc, so it never appeared in
        # this list at all before. Sourced from the real
        # is_ready/last_error state (see llm_bridge.py's
        # verify_offline_ready()), not just "attribute exists".
        llm_bridge_for_organ = getattr(brain, "llm", None) if brain else None
        if llm_bridge_for_organ is not None:
            llm_ready = getattr(llm_bridge_for_organ, "is_ready", False)
            llm_error = getattr(llm_bridge_for_organ, "last_error", None)
            organs.append({
                "name": "llm",
                "classType": "HybridLLMBridge",
                "isAttached": True,
                "role": "Local LLM Neural Bridge (Qwen 2.5 LlamaCpp Interface)",
                "metrics": "verified loaded" if llm_ready else (f"error: {llm_error}" if llm_error else "not yet verified"),
                "health": "green" if llm_ready else ("red" if llm_error else "yellow"),
            })
        else:
            organs.append({
                "name": "llm",
                "classType": "HybridLLMBridge",
                "isAttached": False,
                "role": "Local LLM Neural Bridge (Qwen 2.5 LlamaCpp Interface)",
                "metrics": "brain.llm is None -- never connected",
                "health": "red",
            })

        llm_bridge = getattr(brain, "llm", None) if brain else None
        # THE ACTUAL BUG: this used to read llm_bridge.model_path,
        # an attribute that has never existed on HybridLLMBridge (the
        # real attribute is the private _model_filename) -- so this
        # ALWAYS fell through to the hardcoded fallback string below,
        # regardless of whether the model was actually loaded, failed
        # to import, or was never connected at all. That's the "dummy
        # data" the UI kept showing no matter what was really going
        # on. Now it reports genuine state via is_ready/last_error
        # (see llm_bridge.py's verify_offline_ready()).
        if llm_bridge is None:
            active_model = "disconnected"
        elif getattr(llm_bridge, "is_ready", False):
            active_model = f"{getattr(llm_bridge, '_model_filename', 'unknown.gguf')} (offline, verified)"
        elif getattr(llm_bridge, "last_error", None):
            active_model = f"MODEL LOAD FAILED: {llm_bridge.last_error}"
        else:
            active_model = f"{getattr(llm_bridge, '_model_filename', 'unknown.gguf')} (not yet verified)"

        telemetry = {
            "pulseState": "idle" if is_idle else "active",
            "beatCount": beat_count,
            # Real bpm derived from the heartbeat's actual interval,
            # not a random number -- 60s / interval-seconds.
            "bpm": round(60.0 / interval, 1),
            "pulseWave": "SYS_UPTIME",
            "runtimeSeconds": round(uptime, 1),
            "isIdle": is_idle,
            "activeModel": str(active_model),
            "ramUsageMB": _resident_memory_mb(),
            "totalTokensProcessed": brain_status.get("total_tokens_estimate", 0),
            "avgLatencyMs": brain_status.get("avg_latency_ms", 0.0),
            "organs": organs,
        }
        return JSONResponse(telemetry)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"organism_state Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# MEMORY ENGRAMS
# =====================================================================

@router.get("/api/memory/engrams")
async def list_engrams():
    brain = integration.brain
    if brain is None or brain.memory is None:
        return JSONResponse({"status": "success", "engrams": []})

    try:
        items = brain.memory.list_all_knowledge(limit=500)
        engrams = [_knowledge_to_engram(item) for item in items]
        return JSONResponse({"status": "success", "engrams": engrams})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"list_engrams Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/memory/engrams")
async def add_engram(payload: dict):
    brain = integration.brain
    if brain is None or brain.memory is None:
        return JSONResponse({"status": "error", "message": "Memory organ not connected."}, status_code=503)

    subject = (payload or {}).get("subject")
    predicate = (payload or {}).get("predicate")
    value = (payload or {}).get("value")
    tags = (payload or {}).get("tags") or []

    if not subject or not predicate or value in (None, ""):
        return JSONResponse(
            {"status": "error", "message": "subject, predicate and value are required."},
            status_code=400,
        )

    try:
        knowledge = brain.memory.remember_knowledge(
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=0.9,   # manually entered via UI -> high confidence
            importance=0.6,
            source="web_ui_manual_entry",
            tags=tags,
        )
        return JSONResponse({"status": "success", "engram": _knowledge_to_engram(knowledge)})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"add_engram Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.delete("/api/memory/engrams/{knowledge_id}")
async def delete_engram(knowledge_id: str):
    brain = integration.brain
    if brain is None or brain.memory is None:
        return JSONResponse({"status": "error", "message": "Memory organ not connected."}, status_code=503)

    try:
        deleted = brain.memory.forget_knowledge(knowledge_id)
        return JSONResponse({"status": "success" if deleted else "not_found", "id": knowledge_id})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"delete_engram Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# SELF-AUTHORED RULES -- JARVIS-proposed rules awaiting UK's review
# (see Brain.list_pending_self_rules/confirm_self_rule/reject_self_rule/
# explain_self_rule in core/orchestration/brain.py). Previously only
# reachable via cli.py's /pending_rules, /confirm_rule, /reject_rule --
# this is the same data/actions, over HTTP, for the web frontend.
# =====================================================================

@router.get("/api/memory/pending_rules")
async def list_pending_rules():
    brain = integration.brain
    if brain is None or not hasattr(brain, "list_pending_self_rules"):
        return JSONResponse({"status": "success", "rules": []})
    try:
        return JSONResponse({"status": "success", "rules": brain.list_pending_self_rules()})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"list_pending_rules Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/memory/pending_rules/{knowledge_id}/confirm")
async def confirm_pending_rule(knowledge_id: str):
    brain = integration.brain
    if brain is None or not hasattr(brain, "confirm_self_rule"):
        return JSONResponse({"status": "error", "message": "Brain organ not connected."}, status_code=503)
    try:
        result = brain.confirm_self_rule(knowledge_id)
        status_code = 200 if result.get("status") == "confirmed" else 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"confirm_pending_rule Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/memory/pending_rules/{knowledge_id}/reject")
async def reject_pending_rule(knowledge_id: str):
    brain = integration.brain
    if brain is None or not hasattr(brain, "reject_self_rule"):
        return JSONResponse({"status": "error", "message": "Brain organ not connected."}, status_code=503)
    try:
        result = brain.reject_self_rule(knowledge_id)
        status_code = 200 if result.get("status") == "rejected" else 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"reject_pending_rule Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/memory/pending_rules/{knowledge_id}/explain")
async def explain_pending_rule(knowledge_id: str):
    brain = integration.brain
    if brain is None or not hasattr(brain, "explain_self_rule"):
        return JSONResponse({"status": "error", "message": "Brain organ not connected."}, status_code=503)
    try:
        result = brain.explain_self_rule(knowledge_id)
        status_code = 404 if result.get("status") == "not_found" else 200
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"explain_pending_rule Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# CONTESTED FACTS -- confidence/provenance-weighted contradiction
# resolution (M6, 2026-09-11). See SemanticMemory.remember() and
# Brain.list_contested_facts/resolve_contested_fact.
# =====================================================================

@router.get("/api/memory/contested_facts")
async def list_contested_facts_route():
    brain = integration.brain
    if brain is None or not hasattr(brain, "list_contested_facts"):
        return JSONResponse({"status": "success", "facts": []})
    try:
        return JSONResponse({"status": "success", "facts": brain.list_contested_facts()})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"list_contested_facts Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/memory/contested_facts/{knowledge_id}/resolve")
async def resolve_contested_fact_route(knowledge_id: str, payload: dict):
    brain = integration.brain
    if brain is None or not hasattr(brain, "resolve_contested_fact"):
        return JSONResponse({"status": "error", "message": "Brain organ not connected."}, status_code=503)
    accept_new_value = bool((payload or {}).get("accept_new_value", False))
    try:
        result = brain.resolve_contested_fact(knowledge_id, accept_new_value=accept_new_value)
        status_code = 404 if result.get("status") == "not_found" else 200
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"resolve_contested_fact Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# STANDING INSTRUCTIONS -- daily time-triggers UK stated directly in
# conversation (e.g. "roz subah good morning bolo"). See core/autonomy/
# standing_instructions.py + Brain.list_standing_instructions/
# remove_standing_instruction.
# =====================================================================

@router.get("/api/autonomy/standing_instructions")
async def list_standing_instructions_route():
    brain = integration.brain
    if brain is None or not hasattr(brain, "list_standing_instructions"):
        return JSONResponse({"status": "success", "instructions": []})
    try:
        return JSONResponse({"status": "success", "instructions": brain.list_standing_instructions()})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"list_standing_instructions Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.delete("/api/autonomy/standing_instructions/{knowledge_id}")
async def delete_standing_instruction_route(knowledge_id: str):
    brain = integration.brain
    if brain is None or not hasattr(brain, "remove_standing_instruction"):
        return JSONResponse({"status": "error", "message": "Brain organ not connected."}, status_code=503)
    try:
        result = brain.remove_standing_instruction(knowledge_id)
        status_code = 200 if result.get("status") == "removed" else 404
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"delete_standing_instruction Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# AUTONOMY
# =====================================================================

@router.get("/api/autonomy/state")
async def autonomy_state():
    jarvis = integration.jarvis
    if jarvis is None:
        return JSONResponse({"status": "success", "goals": [], "proposals": []})

    try:
        goal_manager = jarvis.get_organ("goal_manager") if hasattr(jarvis, "get_organ") else None
        goals = [_goal_to_curiosity_goal(g) for g in (goal_manager.goals if goal_manager else [])]

        brain = jarvis.get_organ("brain") if hasattr(jarvis, "get_organ") else None
        evolution = getattr(brain, "evolution", None) if brain else None
        proposals = []
        if evolution is not None and hasattr(evolution, "list_proposals"):
            proposals = [_proposal_to_evolution_proposal(p) for p in evolution.list_proposals(limit=50)]

        return JSONResponse({"status": "success", "goals": goals, "proposals": proposals})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"autonomy_state Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/autonomy/trigger-idle")
async def trigger_idle():
    """
    Runs one REAL idle cycle right now (core/autonomy/idle_loop.py),
    instead of waiting for the next heartbeat pulse -- this is the
    "Trigger Idle Curiosity Cycle" button. It's the exact same
    idle_loop.step() the heartbeat calls automatically when idle; this
    just calls it on demand and reports back whichever goal actually
    changed as a result.
    """
    jarvis = integration.jarvis
    if jarvis is None:
        return JSONResponse({"status": "error", "message": "Organism not initialized."}, status_code=503)

    idle_loop = jarvis.get_organ("idle_loop") if hasattr(jarvis, "get_organ") else None
    goal_manager = jarvis.get_organ("goal_manager") if hasattr(jarvis, "get_organ") else None

    if idle_loop is None or goal_manager is None:
        return JSONResponse({"status": "error", "message": "Autonomy organs not attached."}, status_code=503)

    try:
        before_ids = {g["id"] for g in goal_manager.goals}
        result = idle_loop.step()

        # Prefer a goal that's genuinely new/changed this cycle so the
        # UI reflects what actually happened, not just "the newest
        # goal in the list" (which might be unrelated/older).
        new_goals = [g for g in goal_manager.goals if g["id"] not in before_ids]
        if new_goals:
            chosen = new_goals[-1]
        else:
            target_text = result.get("goal")
            chosen = next((g for g in reversed(goal_manager.goals) if g.get("text") == target_text), None)

        if chosen is None:
            # Genuinely nothing changed this cycle -- report that
            # honestly instead of fabricating a goal.
            chosen = {
                "id": f"idle-noop-{int(time.time())}",
                "text": f"Idle cycle ran, no change ({result.get('action', 'noop')}: {result.get('reason', 'no pending work')})",
                "priority": 0.1,
                "status": "completed",
                "origin": "self",
                "progress": [],
                "created_at": time.time(),
            }

        return JSONResponse({"status": "success", "goal": _goal_to_curiosity_goal(chosen), "cycle_result": result})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"trigger_idle Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# CHAT (REST alternative to the /ws socket, same real pipeline)
# =====================================================================

@router.post("/api/chat")
async def chat_v6(payload: dict, request: Request = None, authorization: Optional[str] = Header(None)):
    """
    Same underlying executor as the websocket path (routes_ws.py) --
    cli.py's execute_cognitive_query(), which calls the real
    brain.think_and_respond(). Both surfaces persist to the same
    SQLite chat history and build their trace from the same
    brain.last_turn_trace, so nothing here is simulated or duplicated
    logic that could drift from the CLI/websocket behaviour.

    trace/traceLog below are the REAL brain.last_turn_trace (full) and
    a real condensed summary of it (see trace_utils.py) -- previously
    this read trace["vector_matches"]/trace["memory_signal"]/
    trace["learning_queue"], none of which the real trace object ever
    sets (see core/orchestration/brain.py's _trace()), so those fields
    were always empty/zero regardless of what the turn actually did.
    """
    executor = integration.get_query_executor()
    if executor is None:
        return JSONResponse({"status": "error", "message": "Cognitive engine not bound yet."}, status_code=503)

    # SPEAKER IDENTITY (2026-09-13). Resolved from the Authorization
    # header, never from the payload -- a body-supplied username would
    # let any caller claim to be someone else and reach that person's
    # private memory. Unauthenticated callers stay an unverified guest
    # rather than being rejected, so existing local/CLI flows keep
    # working; they simply get no personal memory.
    speaker_ctx = None
    try:
        from .routes_auth import get_speaker
        from core.runtime.session_registry import touch_session

        speaker = get_speaker(authorization)
        speaker_ctx = speaker.as_dict() if hasattr(speaker, "as_dict") else dict(speaker or {})

        # WHO IS TALKING. Registered per request so several people can
        # be in conversation at once and each turn is attributed to the
        # right one -- previously nothing recorded the caller at all,
        # which is why the monitor could not show it and why JARVIS
        # could not answer "kaun baat kar raha hai".
        client_ip = "unknown"
        try:
            if request is not None and request.client:
                client_ip = request.client.host or "unknown"
        except Exception:
            pass
        token = (authorization or "").replace("Bearer ", "").strip()
        session = touch_session(
            token or f"guest@{client_ip}",
            username=speaker_ctx.get("username"),
            role=speaker_ctx.get("role", "guest"),
            ip=client_ip,
            channel="web",
            counts_as_turn=True,
        )
        speaker_ctx["ip"] = client_ip
        speaker_ctx["session_turns"] = session.get("turns", 0)
        # request_id + session_id so every trace can answer WHO / WHICH
        # SESSION / WHICH REQUEST (spec section 12).
        from core.runtime.identity_trace import new_request_id
        speaker_ctx["request_id"] = new_request_id()
        speaker_ctx["session_id"] = session.get("session_key")
        speaker_ctx["channel"] = "web"

        brain = getattr(integration, "brain", None)
        if brain is not None:
            brain.current_speaker = speaker_ctx
    except Exception:
        speaker_ctx = None

    # Thinking mode from the composer toggle. 'auto' lets JARVIS decide
    # per turn (see core/cognition/thinking.py); the brain reads this
    # off itself rather than taking another parameter through the whole
    # call chain.
    try:
        brain_obj = getattr(integration, "brain", None)
        if brain_obj is not None:
            mode = str((payload or {}).get("thinking_mode", "auto")).lower()
            brain_obj.thinking_mode = mode if mode in ("off", "auto", "on") else "auto"
    except Exception:
        pass

    message = (payload or {}).get("message", "")
    session_id = (payload or {}).get("sessionId") or "main_session"
    if not message.strip():
        return JSONResponse({"status": "error", "message": "message is required."}, status_code=400)

    # EXTENDED THINKING GROUNDING (2026-09-18, UK's repeated report:
    # the reply text described something completely different from
    # what the visible Extended Thinking steps panel had just shown --
    # e.g. the panel showing a real package-install failure and a
    # token-budget stop, the reply instead claiming "workdir uplabdh
    # nahi hai", a reason the steps never mentioned).
    #
    # Root cause: the steps panel (Extended Thinking's own TaskLoop
    # run, streamed over SSE) and this reply (the normal chat pipeline,
    # which decides for itself via tool-calling whether to invoke
    # coding) are two INDEPENDENT attempts at the same request. When
    # this reply's own tool-calling also decided the message needed
    # coding, it started a SECOND, unrelated attempt -- different
    # sandbox session, different randomness, often a different result
    # -- and then honestly described THAT one, which reads as
    # "hallucinating" against the panel the person was just watching.
    #
    # extended_thinking_context carries a plain-text digest of what the
    # SSE run actually did, built by the frontend from real events (see
    # UserChatView.tsx's groundingRef).
    #
    # THE ACTUAL BUG (found 2026-09-18, UK caught it in his own on-
    # device chat log): this used to be glued directly onto the
    # message text itself before being sent all the way down as THE
    # user's message -- so perception/semantic understanding parsed
    # the ENTIRE internal reasoning dump as if UK had typed it, and
    # EpisodicMemory.remember() then PERSISTED that polluted blob as
    # "what UK said this turn", which is exactly what UK saw leaking
    # into his own chat log and poisoning every later turn's recap.
    # Fixed: grounding_context now travels as its OWN argument all the
    # way to build_response_brief()'s new grounding_context field
    # (core/orchestration/response_brief.py) -- message/user_input
    # reaching perception, episodic memory, and the DB is the user's
    # clean original text, always.
    grounding_context = str((payload or {}).get("extended_thinking_context") or "").strip()

    # ATTACHMENT GROUNDING (2026-09-21, root-cause pass -- see
    # upload_guard.py's read_uploaded_file() docstring for the full
    # chain of the bug this closes). UserChatView.tsx's chat-file
    # picker now keeps the REAL upload_id(s) from a successful
    # /api/upload this turn and sends them here as their own field --
    # same "own field, never concatenated into message" pattern as
    # extended_thinking_context above, and for the identical reason:
    # this must never become part of the persisted user_input or it
    # pollutes perception/episodic memory exactly the way that bug did.
    #
    # Resolved into a short, factual digest with the REAL path and
    # (for text-like files) real content, then merged into
    # grounding_context so the wording stage has true material to
    # describe. This does not replace read_uploaded_file as a tool --
    # the model can still call it mid-turn for an upload referenced
    # without an ID, or from an earlier turn -- it just means an
    # attachment picked THIS turn doesn't require a follow-up message
    # before anything can act on it, which was UK's exact complaint
    # ("attach karke bhi kuch nahi hota, dubara poochna padta hai").
    try:
        attachment_ids = (payload or {}).get("attachment_upload_ids") or []
        if isinstance(attachment_ids, str):
            attachment_ids = [attachment_ids]
        attachment_ids = [str(a).strip() for a in attachment_ids if str(a or "").strip()][:5]
        if attachment_ids and speaker_ctx:
            from core.skills.upload_guard import read_uploaded_file
            digest_lines = []
            for aid in attachment_ids:
                res = read_uploaded_file(aid, role=speaker_ctx.get("role", "user"),
                                         username=speaker_ctx.get("username"))
                if not res.get("ok"):
                    digest_lines.append(f"[Attachment {aid}: not found in your sandbox -- {res.get('error')}]")
                    continue
                for f in res.get("files", [])[:3]:
                    line = f"[Attached this turn: {f['name']} (upload_id={aid}), real path: {f['absolute_path']}"
                    content = f.get("content")
                    if content:
                        snippet = content if len(content) <= 4000 else content[:4000] + " ...(truncated)"
                        line += f"\nContent:\n{snippet}"
                    else:
                        line += f" -- {f.get('note', 'binary/non-text file, content not shown')}"
                    line += "]"
                    digest_lines.append(line)
            if digest_lines:
                attachment_digest = "\n\n".join(digest_lines)
                grounding_context = (
                    (attachment_digest + "\n\n" + grounding_context) if grounding_context else attachment_digest
                )
    except Exception:
        pass  # attachment grounding is an enhancement -- never block a turn over it

    # THREAD-WIDE SEARCH (2026-09-19) -- see routes_codebox.py's
    # identical block for the full rationale (UK's explicit
    # architecture: no time interval required, full-thread scan, only
    # the found snippet reaches the brief). Wired here too since this
    # /chat endpoint is the NORMAL (non-extended-thinking) pipeline --
    # the same backward-reference capability must work whichever mode
    # UK is in, not just Extended Thinking.
    try:
        from core.cognition.thread_search import (
            has_backward_reference, extract_time_hint_hours,
            search_thread_for_reference, format_thread_matches,
        )
        if has_backward_reference(message):
            rows = database.get_history_rows(session_id)
            thread_messages = [
                {
                    "sender": "user" if r["sender"] == "user" else "jarvis",
                    "text": r["text"],
                    "timestamp": database._timestamp_to_epoch_ms(r["timestamp"]) / 1000.0,
                }
                for r in rows
            ]
            time_hint = extract_time_hint_hours(message)
            matches = search_thread_for_reference(
                message, thread_messages, max_results=3, time_hint_hours=time_hint,
            )
            brain_for_search = getattr(integration, "brain", None)
            if matches and brain_for_search is not None and hasattr(brain_for_search, "conversation_continuity"):
                brain_for_search.conversation_continuity.set_retrieved_reference(format_thread_matches(matches))
    except Exception:
        pass  # thread search is an enhancement -- never block a turn over it

    _turn_started = time.time()
    try:
        database.save_message_to_db(session_id=session_id, sender="user", text=message, source="web")

        reply = await asyncio.to_thread(executor, message, "web", grounding_context)
        reply_str = str(reply)

        trace = real_turn_trace(integration.brain)

        # IDENTITY-TAGGED TRACE (spec section 12). Recorded here, where
        # the speaker and the outcome are both known, so the entry can
        # answer who/which session/which request without guessing.
        try:
            from core.runtime.identity_trace import record as _trace_record
            _trace_record(
                request_id=(speaker_ctx or {}).get("request_id") or "req_unknown",
                speaker=speaker_ctx or {"role": "guest"},
                user_input=message,
                response=reply_str,
                workflow=trace if isinstance(trace, dict) else {"trace": str(trace)[:1500]},
                duration_ms=(time.time() - _turn_started) * 1000,
                status="completed",
            )
        except Exception:
            pass
        trace_summary = turn_trace_summary(trace, integration.brain)
        extracted_fact = extracted_fact_from_trace(trace)

        message_id = database.save_message_to_db(
            session_id=session_id,
            sender="jarvis",
            text=reply_str,
            source="web",
            trace_log=turn_trace_to_json(trace),
            extracted_fact=json.dumps(extracted_fact) if extracted_fact else None,
        )

        jarvis_message = {
            "id": str(message_id) if message_id else f"msg-{int(time.time() * 1000)}-j",
            "sessionId": session_id,
            "sender": "jarvis",
            "text": reply_str,
            "timestamp": time.strftime("%H:%M:%S"),
            "source": "web",
            "trace": trace,
            "traceLog": trace_summary,
            "extractedFact": extracted_fact,
        }

        return JSONResponse({"status": "success", "jarvisMessage": jarvis_message})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"chat_v6 Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
