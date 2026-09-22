# -*- coding: utf-8 -*-
"""The single /ws realtime endpoint: chat messages, ping/pong, thinking sync."""
import asyncio
import json
import time
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import database, integration
from .ws_manager import (
    active_connections,
    debug_log,
    broadcast_to_clients,
    set_thinking,
    thinking_snapshot,
)
from .config import get_local_ist_timestamp
from .trace_utils import real_turn_trace, turn_trace_to_json, turn_trace_summary, extracted_fact_from_trace, derive_thinking_steps

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    client_host = websocket.client.host if websocket.client else "Unknown"
    debug_log(f"WebSocket Connected: {client_host}", "green")

    # As soon as a client connects, push it a snapshot of every session
    # that is currently mid-query. This is what makes the "Thinking..."
    # bubble survive refresh / backgrounding / thread-switching.
    snapshot = thinking_snapshot()
    if snapshot:
        try:
            await websocket.send_json({"type": "thinking_sync", "sessions": snapshot})
        except Exception:
            pass

    try:
        while True:
            # Don't let a single receive_text() call block forever with no
            # signal to the outside world. A short timeout here just lets
            # the loop check in periodically -- it does NOT close the
            # connection on timeout, it just avoids the socket looking
            # "dead" from the server's perspective while genuinely idle.
            try:
                raw_data = await asyncio.wait_for(websocket.receive_text(), timeout=45)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
                continue

            # A malformed frame must never kill the socket -- it used to
            # bubble up and force a reconnect, which was a big part of why
            # the CLI showed rapid Connected/Disconnected flapping.
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                debug_log(f"Ignoring malformed WS frame: {raw_data[:120]}", "bold red")
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "user_message":
                await _handle_user_message(websocket, data)

    except WebSocketDisconnect:
        debug_log(f"WebSocket Disconnected: {client_host}", "yellow")
    except Exception as ws_err:
        debug_log(f"WebSocket Exception: {ws_err}", "bold red")
    finally:
        active_connections.discard(websocket)


async def _handle_user_message(websocket: WebSocket, data: dict):
    user_text = data.get("text", "")
    session_id = data.get("session_id", "main_session")
    debug_log(f"Processing Query [{session_id}]: '{user_text}'", "bold cyan")

    database.save_message_to_db(session_id=session_id, sender="user", text=user_text, source="web")

    broadcast_to_clients(
        {
            "type": "chat_sync",
            "sender": "user",
            "text": user_text,
            "session_id": session_id,
            "source": "web",
        },
        exclude_ws=websocket,
    )

    executor = integration.get_query_executor()
    if not executor:
        await websocket.send_json({
            "type": "chat_error",
            "text": "Query Executor Engine Not Bound.",
        })
        return

    set_thinking(session_id, True)
    start_time = time.time()
    try:
        reply = await asyncio.to_thread(executor, user_text, "web")
        latency = round(time.time() - start_time, 3)
        reply_str = str(reply)

        # The REAL trace this turn produced -- the exact same
        # brain.last_turn_trace dict cli.py's execute_cognitive_query()
        # and deep_inspector.py render (see backend/trace_utils.py).
        # Previously this read trace["memory"]/trace["learning_queue"],
        # neither of which the real trace object ever sets, so every
        # turn printed "0 matching frames retrieved" regardless of what
        # actually happened.
        trace = real_turn_trace(integration.brain)
        trace_summary = turn_trace_summary(trace, integration.brain)
        extracted_fact = extracted_fact_from_trace(trace)

        # CLAUDE-STYLE STEP LIST (2026-09-17, UK's evidence: this used
        # to render live and vanish on refresh, because it was never
        # saved. Computed from the SAME trace dict (trace["tool_calls"],
        # folded in by real_turn_trace()) that is about to be persisted
        # below -- baked INTO that trace dict before it is JSON-encoded,
        # so it round-trips through the existing trace_log column with
        # no new schema, and /api/history can read it back the exact
        # same way after a refresh.
        thinking_steps = derive_thinking_steps(trace, integration.brain)
        if isinstance(trace, dict) and thinking_steps:
            trace["thinking_steps"] = thinking_steps

        database.save_message_to_db(
            session_id=session_id,
            sender="jarvis",
            text=reply_str,
            source="web",
            trace_log=turn_trace_to_json(trace),
            extracted_fact=json.dumps(extracted_fact) if extracted_fact else None,
        )

        broadcast_to_clients({
            "type": "chat_response",
            "sender": "jarvis",
            "text": reply_str,
            "session_id": session_id,
            "timestamp": get_local_ist_timestamp(),
            "trace": trace,
            "trace_log": trace_summary,
            "thinking_steps": thinking_steps,
            "extracted_fact": extracted_fact,
            "source": "web",
        })
    except Exception as exec_err:
        err_trace = traceback.format_exc()
        debug_log(f"Query Execution Error:\n{err_trace}", "bold red")
        broadcast_to_clients({
            "type": "system_error",
            "source": "Query Executor Engine",
            "error": str(exec_err),
            "traceback": err_trace,
        })
        try:
            await websocket.send_json({
                "type": "chat_error",
                "text": f"Query failed: {exec_err}",
            })
        except Exception:
            pass
    finally:
        # Always clear the thinking flag, success or failure, so a crashed
        # query can never leave the UI stuck on "Thinking...".
        set_thinking(session_id, False)
