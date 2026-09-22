# -*- coding: utf-8 -*-
"""
Everything about "who is connected and what do we tell them":
- the live set of websocket connections
- broadcast_to_clients()
- the console/log bridge (debug_log)
- server-side "is this session still thinking" state (survives refresh)
- the heartbeat/pulse background task

Kept separate from database.py and routes so both can import it without
creating an import cycle (database needs to broadcast rename events;
routes need to broadcast session changes; the ws route needs both).
"""
import asyncio
import threading

from fastapi import WebSocket

# ---------------------------------------------------------------------------
# Connection registry
# ---------------------------------------------------------------------------
active_connections: set[WebSocket] = set()
server_loop = None  # set once, from server.py's lifespan, to the running loop
console_ref = None  # optional rich.Console-like object for pretty CLI logs


def attach_console(console_instance):
    global console_ref
    console_ref = console_instance


def set_server_loop(loop):
    global server_loop
    server_loop = loop


def debug_log(msg: str, style: str = "yellow"):
    if console_ref:
        console_ref.print(f"[{style}][WEB DEBUG] {msg}[/{style}]")
    else:
        print(f"[WEB DEBUG] {msg}")


def broadcast_to_clients(data: dict, exclude_ws: WebSocket = None):
    """Fire-and-forget broadcast, safe to call from worker threads."""
    if server_loop and server_loop.is_running():

        async def _broadcast():
            disconnected = set()
            for ws in list(active_connections):
                if ws == exclude_ws:
                    continue
                try:
                    await ws.send_json(data)
                except Exception:
                    disconnected.add(ws)
            active_connections.difference_update(disconnected)

        asyncio.run_coroutine_threadsafe(_broadcast(), server_loop)


# ---------------------------------------------------------------------------
# Server-side "thinking" state tracker.
# Whenever a query starts/ends we flip this flag and broadcast it. Any
# client that (re)connects immediately receives a snapshot of what is
# still in progress, so the "Thinking..." bubble survives refresh /
# navigation / tab switches instead of getting stuck or vanishing.
# ---------------------------------------------------------------------------
active_thinking: dict[str, bool] = {}
thinking_lock = threading.Lock()


def set_thinking(session_id: str, is_thinking: bool):
    """Central helper: flips server-side state + broadcasts it in one place."""
    with thinking_lock:
        if is_thinking:
            active_thinking[session_id] = True
        else:
            active_thinking.pop(session_id, None)
    broadcast_to_clients({
        "type": "thinking_start" if is_thinking else "thinking_end",
        "session_id": session_id,
    })


def is_thinking(session_id: str) -> bool:
    with thinking_lock:
        return active_thinking.get(session_id, False)


def thinking_snapshot() -> dict:
    with thinking_lock:
        return dict(active_thinking)


def clear_thinking(session_id: str):
    with thinking_lock:
        active_thinking.pop(session_id, None)


# ---------------------------------------------------------------------------
# Background Heartbeat & Telemetry Pulse task
# ---------------------------------------------------------------------------
async def heartbeat_task():
    beats = 0
    waves = ["∿∿∿_/\\_∿∿∿", "∿∿∿∿_/\\_∿∿", "∿_/\\/\\_∿∿∿", "∿∿∿∿∿∿∿∿∿"]
    while True:
        await asyncio.sleep(2.0)
        if active_connections:
            beats += 1
            wave = waves[beats % len(waves)]
            state_str = (
                "Consolidating Memory..." if beats % 4 == 0 else "Active Listening"
            )
            pulse_data = {
                "type": "pulse",
                "wave": wave,
                "beats": beats * 15,
                "state": state_str,
            }

            disconnected = set()
            for ws in list(active_connections):
                try:
                    await ws.send_json(pulse_data)
                except Exception:
                    disconnected.add(ws)
            active_connections.difference_update(disconnected)
