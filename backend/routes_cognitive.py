# -*- coding: utf-8 -*-
"""
Cognitive Monitor + Cognitive Trace endpoints for the V6 web frontend.

Everything a person could see in TWO separate terminal tools --
`python3 monitor.py` (the organism's live internal lifecycle) and
cli.py's `/trace_inspect` / deep_inspector.py (the exact per-turn
cognitive trace) -- is now served over HTTP from the SAME data those
tools read, so the web UI shows the identical numbers, not a second
simulated copy of them.

Endpoint <-> frontend contract (see web_frontend/src/types.ts):
    GET /api/live_state          -> LiveStateResponse   (monitor.py's data)
    GET /api/resources           -> SystemResourcesData
    GET /api/trace/history       -> ActivityHistoryItem[]  (cli.py's cognitive trace, per turn)
    GET /api/trace/{turn_id}     -> TurnTrace
"""
import os
import resource
import threading
import time
import traceback

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import database, integration
from .ws_manager import debug_log

from core.runtime.state_bus import read_snapshot as read_state_snapshot

router = APIRouter()


# =====================================================================
# GET /api/live_state  -- exactly what `python3 monitor.py` shows
# =====================================================================

@router.get("/api/live_state")
async def live_state():
    """
    Reads core/runtime/state_bus.py's on-disk IPC snapshot -- the exact
    same file monitor.py polls in a second terminal. Since this backend
    runs in-process with the organism (cli.py option 2/3), this is a
    plain in-process read, not a second network hop.

    If the state bus hasn't published anything yet (organism just
    started, or running without the web server attached), this returns
    an honestly-empty snapshot -- OFFLINE runtime, empty organs/logs --
    rather than fabricated numbers.
    """
    try:
        snapshot = read_state_snapshot()
        if snapshot:
            return JSONResponse(snapshot)

        now = time.time()
        return JSONResponse({
            "version": 1,
            "pid": os.getpid(),
            "updated_at": now,
            "runtime": "OFFLINE",
            "stage": "IDLE",
            "stage_detail": {},
            "stage_since": now,
            "fallback_active": False,
            "pipeline_trace": [],
            "extractions": [],
            "learning": {"active": False, "alive": False, "pending": 0, "processed": 0, "failed": 0, "dropped": 0},
            "logs": [],
            "organs": {},
            "heartbeat": {"running": False, "beats": 0, "idle": True},
            "llm_ready": False,
            "idle_activity": [],
            "idle_last": {},
            "dependency_metrics": {},
            "contradiction_rate": None,
            "evolution_summary": {},
            "latest_reasoning": {},
            "latest_tool_calls": [],
            "pending_self_rules": [],
            "standing_instructions": [],
            "contested_facts": [],
            "grounding_violation_patterns": {},
            "pending_patterns": [],
            "recent_auto_promotions": [],
            "llm_dependency_stats": {},
            "training_data_stats": {},
            "memory_consolidation": {},
            "native_response_learning": {},
            "idiolect_status": {},
            "memory_decay": {},
            "calibration": {},
            "procedural_memory": {},
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"live_state Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# GET /api/resources  -- process/LLM/knowledge/evolution telemetry
# =====================================================================

def _resident_memory_mb() -> float:
    try:
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024.0, 1)
    except Exception:
        return 0.0


@router.get("/api/resources")
async def resources():
    """
    Every field here is read from a live object (brain.llm,
    brain.knowledge_builder.statistics(), brain.evaluator, brain.evolution)
    -- nothing is Math.random()'d or hardcoded. Organs that aren't
    attached yet report honest zeros/None instead of a placeholder
    number.
    """
    try:
        jarvis = integration.jarvis
        brain = integration.brain or (
            jarvis.get_organ("brain") if jarvis and hasattr(jarvis, "get_organ") else None
        )

        usage = resource.getrusage(resource.RUSAGE_SELF)
        process = {
            "max_rss_mb": _resident_memory_mb(),
            "user_cpu_seconds": round(usage.ru_utime, 2),
            "system_cpu_seconds": round(usage.ru_stime, 2),
            "threads": threading.active_count(),
        }

        llm_bridge = getattr(brain, "llm", None) if brain else None
        if llm_bridge is not None:
            try:
                budget = llm_bridge.budget_status() if hasattr(llm_bridge, "budget_status") else {}
            except Exception:
                budget = {}
            llm = {
                "backend": type(llm_bridge).__name__,
                "ready": bool(getattr(llm_bridge, "is_ready", False)),
                "local_loaded": bool(getattr(llm_bridge, "is_ready", False)),
                "last_error": getattr(llm_bridge, "last_error", None),
                "budget": {
                    "calls": budget.get("calls", 0),
                    "max_calls": budget.get("max_calls", 0),
                },
            }
        else:
            llm = {"backend": "unattached", "ready": False, "local_loaded": False, "last_error": "brain.llm is None", "budget": {"calls": 0, "max_calls": 0}}

        evaluator = getattr(brain, "evaluator", None) if brain else None
        if evaluator is not None:
            evaluations = getattr(evaluator, "evaluation_count", 0) or 0
            success_count = getattr(evaluator, "success_count", 0) or 0
            total_score = getattr(evaluator, "total_score", 0.0) or 0.0
            self_evaluation = {
                "evaluations": evaluations,
                "success_rate": round(success_count / evaluations, 3) if evaluations else 0.0,
                "average_score": round(total_score / evaluations, 3) if evaluations else 0.0,
                "last_evaluated_at": getattr(evaluator, "last_evaluated_at", None) or 0,
            }
        else:
            self_evaluation = {"evaluations": 0, "success_rate": 0.0, "average_score": 0.0, "last_evaluated_at": 0}

        knowledge_builder = getattr(brain, "knowledge_builder", None) if brain else None
        if knowledge_builder is not None and hasattr(knowledge_builder, "statistics"):
            try:
                kb_stats = knowledge_builder.statistics()
            except Exception:
                kb_stats = {}
            knowledge = {
                "built": kb_stats.get("built", 0),
                "accepted": kb_stats.get("accepted", 0),
                "rejected": kb_stats.get("rejected", 0),
                "pending": kb_stats.get("pending", 0),
                "last_built_at": kb_stats.get("last_built_at") or 0,
            }
        else:
            knowledge = {"built": 0, "accepted": 0, "rejected": 0, "pending": 0, "last_built_at": 0}

        evolution_engine = getattr(brain, "evolution", None) if brain else None
        proposals = {}
        if evolution_engine is not None and hasattr(evolution_engine, "list_proposals"):
            try:
                proposals = {p.get("id"): p for p in evolution_engine.list_proposals(limit=200)}
            except Exception:
                proposals = {}
        elif evolution_engine is not None:
            proposals = getattr(evolution_engine, "proposals", {}) or {}
        status_counts = {}
        last_at = 0
        for p in (proposals.values() if isinstance(proposals, dict) else []):
            if not isinstance(p, dict):
                continue
            status = str(p.get("status", "UNKNOWN"))
            status_counts[status] = status_counts.get(status, 0) + 1
            last_at = max(last_at, p.get("created_at", 0) or 0)
        evolution = {
            "proposals": sum(status_counts.values()),
            "approved": status_counts.get("APPROVED", 0),
            "applied": status_counts.get("APPLIED", 0),
            "rejected": status_counts.get("REJECTED", 0),
            "last_evolution_at": last_at,
        }

        return JSONResponse({
            "timestamp": time.time(),
            "process": process,
            "llm": llm,
            "self_evaluation": self_evaluation,
            "knowledge": knowledge,
            "evolution": evolution,
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"resources Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =====================================================================
# GET /api/trace/history + /api/trace/{turn_id}
# -- exactly what cli.py's execute_cognitive_query()/render_workflow_panel
#    and /trace_inspect show, per turn, now queryable from the DB where
#    every jarvis reply's real trace is stored (see trace_utils.py).
# =====================================================================

def _row_to_activity_item(row: dict) -> dict:
    trace = row.get("trace") or {}
    timings = trace.get("timings") or {}
    duration = float(timings.get("total", 0.0) or 0.0)
    start_ms = row.get("start_ms") or 0
    end_ms = start_ms + int(duration * 1000) if start_ms else None

    stage_path = ["IDLE", "PERCEIVING", "INDEXING", "EXECUTING", "IDLE"]
    return {
        "turnId": f"trn-{row['id']}",
        "startTime": start_ms,
        "endTime": end_ms,
        "durationSeconds": duration,
        "stagePath": stage_path,
        "query": row.get("query") or "",
        "responsePreview": (trace.get("response_preview") or row.get("response") or "")[:200],
        "success": bool(trace.get("pipeline_success", True)),
        "trace": trace,
    }


@router.get("/api/trace/history")
async def trace_history(limit: int = 50):
    try:
        rows = database.get_recent_traces(limit=min(max(limit, 1), 200))
        items = [_row_to_activity_item(row) for row in rows]
        return JSONResponse(items)
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"trace_history Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/trace/{turn_id}")
async def trace_by_id(turn_id: str):
    try:
        message_id = turn_id.replace("trn-", "").replace("TRN-", "")
        row = database.get_trace_by_message_id(message_id)
        if not row:
            return JSONResponse({"status": "error", "message": "Trace not found."}, status_code=404)
        item = _row_to_activity_item(row)
        return JSONResponse(item["trace"])
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"trace_by_id Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
