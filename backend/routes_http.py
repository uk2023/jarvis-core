# -*- coding: utf-8 -*-
"""All plain HTTP (non-websocket) routes."""
import os
import time
import json
import traceback
from datetime import datetime

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import config, database
from . import integration
from .ws_manager import debug_log, broadcast_to_clients, thinking_snapshot, is_thinking, clear_thinking
from .trace_utils import real_turn_trace, derive_thinking_steps

router = APIRouter()


@router.get("/api/health")
async def health_check():
    """Plain liveness probe for the web frontend's connection indicator
    (WebSocketStatusIndicator.tsx / api.testConnection()). Separate from
    /api/status on purpose: this must answer even if the organism itself
    hasn't finished booting yet, so the UI can distinguish "backend is up,
    organism still starting" from "backend unreachable"."""
    return JSONResponse({
        "status": "ok",
        "organism_attached": integration.jarvis is not None,
    })


@router.get("/api/status")
async def get_status():
    """
    Real organism diagnostics for the web dashboard: organ matrix,
    heartbeat, async learning queue, goals/autonomy snapshot.

    This endpoint did not exist before -- the dashboard had no way to
    see anything beyond the raw heartbeat "pulse" beat count broadcast
    over the websocket, which is why organ/queue/autonomy state never
    showed up on the web side even though it was tracked internally.
    """
    jarvis = integration.jarvis
    if jarvis is None:
        return JSONResponse(
            {"status": "error", "message": "Organism not initialized in this process."},
            status_code=503,
        )

    try:
        organs = jarvis.get_organ_status() if hasattr(jarvis, "get_organ_status") else {}

        heartbeat_status = {}
        if hasattr(jarvis, "heartbeat") and jarvis.heartbeat:
            heartbeat_status = jarvis.heartbeat.status()

        brain = jarvis.get_organ("brain") if hasattr(jarvis, "get_organ") else None
        brain_status = brain.status() if brain and hasattr(brain, "status") else {}

        goal_manager = jarvis.get_organ("goal_manager") if hasattr(jarvis, "get_organ") else None
        goals = goal_manager.snapshot() if goal_manager and hasattr(goal_manager, "snapshot") else {}

        scheduler = jarvis.get_organ("scheduler") if hasattr(jarvis, "get_organ") else None
        scheduler_status = scheduler.snapshot() if scheduler and hasattr(scheduler, "snapshot") else {}

        last_turn_trace = real_turn_trace(brain)

        return JSONResponse({
            "status": "success",
            "organs": organs,
            "heartbeat": heartbeat_status,
            "brain": brain_status,
            "goals": goals,
            "scheduler": scheduler_status,
            "last_turn_trace": last_turn_trace,
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"get_status Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/")
async def get_dashboard():
    # Prefer the built V6 React frontend if it exists (see
    # web_frontend/ -> `npm run build` -> frontend/dist_v6/). Falls
    # back to the legacy static dashboard otherwise so nothing breaks
    # before the first build.
    if os.path.isfile(config.FRONTEND_V6_INDEX):
        try:
            with open(config.FRONTEND_V6_INDEX, "r", encoding="utf-8") as f:
                html_content = f.read()
            return HTMLResponse(
                html_content,
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        except Exception as e:
            debug_log(f"V6 index.html read error: {e}", "bold red")
            # fall through to legacy dashboard below

    try:
        with open(config.INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        html_content = (
            "<h3>index.html not found at path: "
            f"{config.INDEX_HTML_PATH} ({e})</h3>"
        )

    config_injection = f"""
    <script>
        window.JARVIS_MODE = "{config.JARVIS_MODE}";
    </script>
    </head>
    """
    html_content = html_content.replace("</head>", config_injection)

    return HTMLResponse(
        html_content,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/api/config")
async def get_config():
    return JSONResponse({"status": "success", "mode": config.JARVIS_MODE})


@router.get("/api/sessions")
async def get_sessions():
    try:
        rows = database.list_sessions()
        sessions = []
        today_str = datetime.now(config.IST).strftime("%Y-%m-%d")

        for row in rows:
            c_date = row["created_at"].split(" ")[0] if row["created_at"] else today_str
            category = "Today" if c_date == today_str else "Previous"
            # Both snake_case (legacy dashboard) and camelCase (V6 React
            # frontend, see src/types.ts SessionItem) keys are included
            # so one real endpoint serves both UIs -- no forked routes,
            # no simulated data on either side.
            sessions.append({
                "session_id": row["session_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "pinned": bool(row["pinned"]),
                "msg_count": row["msg_count"],
                "category": category,
                "sessionId": row["session_id"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
                "msgCount": row["msg_count"],
            })
        return JSONResponse({"status": "success", "sessions": sessions})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"get_sessions Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/api/history")
async def get_history(session_id: str = "main_session"):
    try:
        rows = database.get_history_rows(session_id)
        history = [dict(row) for row in rows]
        # SURFACE THE PERSISTED THINKING STEPS (2026-09-17). trace_log
        # already stores the full per-turn trace, including
        # thinking_steps baked in by routes_ws.py -- this is what makes
        # a coding-agent/codebox step list survive a page refresh
        # instead of only existing in the live websocket push. Parsed
        # defensively per-row: one bad/old row's trace_log must never
        # 500 the whole history endpoint.
        for row in history:
            row["thinking_steps"] = []
            row["thinking_narratives"] = []
            raw = row.get("trace_log")
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                steps = parsed.get("thinking_steps") if isinstance(parsed, dict) else None
                row["thinking_steps"] = steps if isinstance(steps, list) else []
                narratives = parsed.get("thinking_narratives") if isinstance(parsed, dict) else None
                row["thinking_narratives"] = narratives if isinstance(narratives, list) else []
            except Exception:
                pass
        return JSONResponse({
            "status": "success",
            "session_id": session_id,
            "history": history,
            "is_thinking": is_thinking(session_id),
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"get_history Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


class AttachThinkingStepsRequest(BaseModel):
    session_id: str = "main_session"
    thinking_steps: list = []
    # NARRATIVE PERSISTENCE (2026-09-19) -- see
    # database.py's _attach_thinking_steps_to_last_message_impl
    # docstring for the full story.
    narratives: list = []


@router.post("/api/history/attach_thinking_steps")
async def attach_thinking_steps(req: AttachThinkingStepsRequest):
    """Persists the Extended Thinking panel's steps onto the latest
    JARVIS message in this session (2026-09-17). See
    database.attach_thinking_steps_to_last_message's docstring for the
    full root-cause explanation: the SSE-streamed /api/think/stream
    panel was never connected to trace_log at all, so it rendered live
    and vanished on refresh regardless of the earlier fix for the
    run_coding_task/run_coding_agent tool-call trace (a different
    source entirely). Called by the frontend right after streamThinking
    finishes and the reply has been attached in-memory."""
    try:
        ok = database.attach_thinking_steps_to_last_message(
            req.session_id, req.thinking_steps, req.narratives,
        )
        return JSONResponse({"status": "success" if ok else "no_message_found"})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"attach_thinking_steps Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/sessions/new")
async def create_new_session():
    session_id = f"session_{int(time.time())}"
    try:
        database.create_new_session(session_id)
        return JSONResponse({
            "status": "success",
            "session_id": session_id,
            "title": "New Conversation",
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"create_new_session Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/api/sessions")
async def create_new_session_v6(payload: dict = None):
    """
    Same real create-session logic as /api/sessions/new, but returns
    the shape the V6 React frontend expects: {"session": {...camelCase}}
    (see src/App.tsx handleNewSession -> data.session). Added instead
    of changing /api/sessions/new so the legacy dashboard is untouched.
    """
    session_id = f"session_{int(time.time())}"
    try:
        database.create_new_session(session_id)
        title = "New Conversation"
        if payload and payload.get("title"):
            database.rename_session(session_id, payload["title"])
            title = payload["title"]

        now = config.get_local_ist_timestamp()
        return JSONResponse({
            "status": "success",
            "session": {
                "sessionId": session_id,
                "title": title,
                "createdAt": now,
                "updatedAt": now,
                "pinned": False,
                "msgCount": 0,
                "category": "Today",
            },
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"create_new_session_v6 Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.patch("/api/sessions/{session_id}")
async def update_session_v6(session_id: str, payload: dict):
    """
    Unified rename/pin for the V6 frontend, which PATCHes
    /api/sessions/:id directly with {title} and/or {pinned} rather
    than the legacy /rename and /pin sub-routes below. Both paths hit
    the same real database.py functions -- no separate code path.
    """
    try:
        if payload and "title" in payload and payload["title"]:
            database.rename_session(session_id, payload["title"])
        if payload and "pinned" in payload:
            database.pin_session(session_id, {"pinned": payload["pinned"]})
        return JSONResponse({"status": "success", "session_id": session_id})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"update_session_v6 Error:\n{err_str}", "bold red")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.patch("/api/sessions/{session_id}/rename")
async def rename_session(session_id: str, payload: dict):
    new_title = (payload or {}).get("title", "").strip()
    if not new_title:
        return JSONResponse(
            {"status": "error", "message": "Title cannot be empty"}, status_code=400
        )
    try:
        updated = database.rename_session(session_id, new_title)
        if updated == 0:
            return JSONResponse(
                {"status": "error", "message": "Session not found"}, status_code=404
            )
        broadcast_to_clients({
            "type": "session_renamed",
            "session_id": session_id,
            "title": new_title,
        })
        return JSONResponse({"status": "success", "session_id": session_id, "title": new_title})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"rename_session Error:\n{err_str}", "bold red")
        broadcast_to_clients({
            "type": "system_error",
            "source": "rename_session",
            "error": str(e),
            "traceback": err_str,
        })
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.patch("/api/sessions/{session_id}/pin")
async def pin_session(session_id: str, payload: dict = None):
    try:
        new_pinned = database.pin_session(session_id, payload)
        if new_pinned is None:
            return JSONResponse(
                {"status": "error", "message": "Session not found"}, status_code=404
            )
        broadcast_to_clients({
            "type": "session_pinned",
            "session_id": session_id,
            "pinned": bool(new_pinned),
        })
        return JSONResponse({
            "status": "success",
            "session_id": session_id,
            "pinned": bool(new_pinned),
        })
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"pin_session Error:\n{err_str}", "bold red")
        broadcast_to_clients({
            "type": "system_error",
            "source": "pin_session",
            "error": str(e),
            "traceback": err_str,
        })
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id == "main_session":
        return JSONResponse(
            {"status": "error", "message": "Cannot delete the default session"},
            status_code=400,
        )
    try:
        deleted = database.delete_session(session_id)
        clear_thinking(session_id)

        if deleted == 0:
            return JSONResponse(
                {"status": "error", "message": "Session not found"}, status_code=404
            )

        broadcast_to_clients({"type": "session_deleted", "session_id": session_id})
        return JSONResponse({"status": "success", "session_id": session_id})
    except Exception as e:
        err_str = traceback.format_exc()
        debug_log(f"delete_session Error:\n{err_str}", "bold red")
        broadcast_to_clients({
            "type": "system_error",
            "source": "delete_session",
            "error": str(e),
            "traceback": err_str,
        })
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.get("/manifest.json")
async def get_manifest():
    return JSONResponse({
        "name": "JARVIS AI OS",
        "short_name": "JARVIS",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#090a0f",
        "theme_color": "#090a0f",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/4712/4712035.png",
                "sizes": "192x192",
                "type": "image/png",
            }
        ],
    })


@router.get("/sw.js")
async def get_sw():
    sw_script = """
    self.addEventListener('install', (e) => self.skipWaiting());
    self.addEventListener('activate', (e) => clients.claim());
    self.addEventListener('fetch', (e) => e.respondWith(fetch(e.request)));
    """
    return Response(content=sw_script, media_type="application/javascript")
