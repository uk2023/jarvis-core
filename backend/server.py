# -*- coding: utf-8 -*-
"""
Assembles the FastAPI app from the split modules and exposes
start_server_in_thread(), exactly like the old dashboard.py did -- so any
existing integration code that imports start_server_in_thread /
set_shared_organism / attach_console / bind_query_executor keeps working
unchanged (see main.py for the compatibility re-exports).
"""
import asyncio
import os
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, database
from .ws_manager import debug_log, set_server_loop, heartbeat_task
from .file_watcher import start_universal_file_watcher
from .routes_http import router as http_router
from .routes_ws import router as ws_router
from .routes_frontend_v6 import router as frontend_v6_router
from .routes_cognitive import router as cognitive_router
from .routes_auth import router as auth_router
from .routes_codebox import router as codebox_router
from .routes_voice_call import router as voice_call_router

# Make sure tables exist / migrations run before the app starts serving.
database.db_write(database.init_db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_server_loop(asyncio.get_running_loop())
    debug_log("FastAPI Lifespan Started - Event Loop Captured", "green")

    heartbeat_job = asyncio.create_task(heartbeat_task())
    start_universal_file_watcher()
    debug_log("Universal file watcher & background services online.", "green")

    yield
    heartbeat_job.cancel()
    debug_log("FastAPI Lifespan Shutting Down", "red")


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # CORS -- harmless if you only ever hit this from the same origin, but
    # if the PWA is ever opened from a different host/port (a proxied
    # tunnel, a different LAN IP, ngrok, etc.) missing CORS headers make
    # fetch() calls for pin/rename/delete fail silently in the browser
    # console, which looks exactly like "the button doesn't work".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(http_router)
    app.include_router(ws_router)
    app.include_router(frontend_v6_router)
    app.include_router(cognitive_router)
    app.include_router(auth_router)
    app.include_router(codebox_router)
    app.include_router(voice_call_router)

    # Serve the split css/js assets. index.html now references
    # /static/css/style.css and /static/js/app.js instead of everything
    # being inlined into one giant file.
    if os.path.isdir(config.STATIC_DIR):
        app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

    # V6 React frontend's built assets (JS/CSS bundles from Vite). Only
    # mounted if the build actually exists yet -- see
    # web_frontend/vite.config.ts (build.outDir -> frontend/dist_v6).
    # routes_http.py's "/" route already falls back to the legacy
    # dashboard when this directory is missing, so mounting is purely
    # additive and safe to skip.
    if os.path.isdir(config.FRONTEND_V6_ASSETS_DIR):
        app.mount(
            "/assets",
            StaticFiles(directory=config.FRONTEND_V6_ASSETS_DIR),
            name="v6_assets",
        )

    return app


app = create_app()


def start_server_in_thread(host="0.0.0.0", port=8000):
    def _run_server():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            uv_config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="warning",
                loop="asyncio",
                ws="auto",
                # Protocol-level keepalive pings on the websocket transport
                # itself, with tolerant timing. Flaky mobile data / a
                # backgrounded browser can easily miss a ping or two -- a
                # tight interval/timeout pairing is enough for one slow
                # round-trip to tear the socket down and trigger a full
                # reconnect (the "Connected/Disconnected" flapping).
                ws_ping_interval=25,
                ws_ping_timeout=60,
            )
            server = uvicorn.Server(uv_config)
            server.install_signal_handlers = lambda: None
            debug_log(
                f"Uvicorn Server Starting on http://{host}:{port} [Mode:"
                f" {config.JARVIS_MODE.upper()}]",
                "bold green",
            )
            loop.run_until_complete(server.serve())
        except Exception as server_err:
            debug_log(f"Uvicorn Thread Crashed:\n{server_err}", "bold red")

    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()
    return thread
