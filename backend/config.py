# -*- coding: utf-8 -*-
"""
Central configuration & constants for the JARVIS web server.

Everything path/constant related used to be scattered as module-level
globals at the top of the old single-file dashboard.py. Pulling it into
its own module means every other module (database, routes, server) can
import just what it needs without pulling in FastAPI app wiring.
"""
import os
from datetime import datetime, timezone, timedelta

# Root of the whole Jarvis Organism project on the device.
#
# THE ACTUAL BUG: this used to be hardcoded to
# "/storage/emulated/0/Jarvis_Organism" -- a leftover from before the
# project moved. cli.py and llm_bridge.py already compute BASE_DIR
# dynamically from their own file location (so they work whether the
# project lives in Termux, a Kali proot-distro chroot, or anywhere
# else); config.py was the one file that never got the same fix. That
# mismatch is exactly why the FastAPI backend (DB path, frontend path,
# everything routed through config.py) breaks when the project is run
# from a different location (e.g. /root/Jarvis_Work in a Kali chroot)
# even though cli.py's own model-loading path was already correct.
#
# Override with JARVIS_BASE_DIR if you ever need to force a specific
# location (e.g. keeping the DB on shared Android storage while the
# code itself runs from a chroot).
BASE_DIR = os.environ.get(
    "JARVIS_BASE_DIR"
) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Frontend now lives in its own folder with split html/css/js instead of a
# single index.html with everything inlined.
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
INDEX_HTML_PATH = os.path.join(FRONTEND_DIR, "index.html")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

# =============================================================
# V6 REACT/TYPESCRIPT FRONTEND (web_frontend/)
# =============================================================
# Source lives at <BASE_DIR>/web_frontend (Vite + React + TS). It is
# built separately (`cd web_frontend && npm install && npm run build`)
# and Vite is configured (see web_frontend/vite.config.ts) to output
# straight into FRONTEND_V6_DIST_DIR below, so the backend can serve
# it with zero copy step. If this directory doesn't exist yet (build
# not run), routes_http.py falls back to the legacy dashboard above --
# nothing breaks either way.
WEB_FRONTEND_SRC_DIR = os.path.join(BASE_DIR, "web_frontend")
FRONTEND_V6_DIST_DIR = os.path.join(FRONTEND_DIR, "dist_v6")
FRONTEND_V6_INDEX = os.path.join(FRONTEND_V6_DIST_DIR, "index.html")
FRONTEND_V6_ASSETS_DIR = os.path.join(FRONTEND_V6_DIST_DIR, "assets")

DB_PATH = os.path.join(BASE_DIR, "database", "jarvis.db")

# System Mode: 'dev' or 'normal' (Mode 2)
JARVIS_MODE = os.environ.get("JARVIS_MODE", "dev").lower()

# Indian Standard Timezone (IST: UTC +5:30) with High Precision
IST = timezone(timedelta(hours=5, minutes=30))

# Placeholder titles that should be auto-replaced by the first real user
# message in a thread (ChatGPT/Gemini-style auto-titling).
DEFAULT_SESSION_TITLES = ("New Conversation", "New Neural Thread", "")


def get_local_ist_timestamp() -> str:
    """Returns a high-precision IST timestamp (incl. microseconds) for absolute sync."""
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S.%f")
