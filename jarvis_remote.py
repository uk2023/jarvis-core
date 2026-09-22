#!/usr/bin/env python3
"""jarvis_remote.py -- expose local JARVIS to a friend's phone (or any
device off your local network) via a public HTTPS ngrok tunnel,
without disturbing normal localhost access.

UK's explicit request (2026-09-12): a single command that
  1. checks/starts FastAPI on :8000 if it isn't already running
  2. checks/starts Vite on :5173 if it isn't already running
  3. keeps /api and /ws proxied through Vite to :8000 (see
     web_frontend/vite.config.ts -- added alongside this script,
     since a tunnel only exposes ONE port and the frontend used to
     talk to :8000 directly, which a tunnel can't reach)
  4. starts an ngrok tunnel on :5173 (reads NGROK_AUTHTOKEN from the
     environment / .env -- never hardcoded, never logged)
  5. prints the public URL
  6. on Ctrl+C, cleanly stops ONLY what this script itself started --
     if FastAPI/Vite were already running before this script ran
     (UK's normal `python3 cli.py` session), they are left running
     untouched. Existing localhost:5173 / localhost:8000 access is
     never affected either way.

Usage:
    python3 jarvis_remote.py

Requires `pyngrok` (pip install pyngrok --break-system-packages) and
an ngrok authtoken in .env as NGROK_AUTHTOKEN=... (UK confirmed this
is already saved).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def _load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Minimal, dependency-free .env loader -- only sets a variable if
    it isn't already in the real environment, so an explicitly exported
    shell variable always wins over the file."""
    if not path.exists():
        return
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def _wait_for_port(port: int, seconds: int = 40) -> bool:
    for _ in range(seconds * 2):
        if _is_port_open(port):
            return True
        time.sleep(0.5)
    return False


def _start_backend() -> "subprocess.Popen | None":
    if _is_port_open(BACKEND_PORT):
        print(f"[jarvis-remote] FastAPI already running on :{BACKEND_PORT} -- leaving it alone.")
        return None
    print(f"[jarvis-remote] Starting FastAPI on :{BACKEND_PORT} ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
        cwd=str(PROJECT_ROOT),
    )
    if not _wait_for_port(BACKEND_PORT):
        print("[jarvis-remote] WARNING: FastAPI didn't come up within 40s -- check for errors above.")
    return proc


def _start_frontend() -> "subprocess.Popen | None":
    if _is_port_open(FRONTEND_PORT):
        print(f"[jarvis-remote] Vite already running on :{FRONTEND_PORT} -- leaving it alone.")
        return None
    print(f"[jarvis-remote] Starting Vite on :{FRONTEND_PORT} ...")
    frontend_dir = PROJECT_ROOT / "web_frontend"
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(FRONTEND_PORT)],
        cwd=str(frontend_dir),
    )
    if not _wait_for_port(FRONTEND_PORT, seconds=60):
        print("[jarvis-remote] WARNING: Vite didn't come up within 60s -- check for errors above.")
    return proc


def _start_tunnel():
    try:
        from pyngrok import conf, ngrok
    except ImportError:
        print(
            "[jarvis-remote] pyngrok isn't installed. Run:\n"
            "    pip install pyngrok --break-system-packages\n"
            "then try again."
        )
        sys.exit(1)

    authtoken = os.environ.get("NGROK_AUTHTOKEN")
    if not authtoken:
        print("[jarvis-remote] NGROK_AUTHTOKEN not found in environment or .env -- ngrok needs it to start a tunnel.")
        sys.exit(1)
    conf.get_default().auth_token = authtoken
    print(f"[jarvis-remote] Starting ngrok tunnel -> :{FRONTEND_PORT} ...")
    tunnel = ngrok.connect(FRONTEND_PORT, "http")
    return tunnel


def main() -> None:
    _load_dotenv()

    backend_proc = _start_backend()
    frontend_proc = _start_frontend()
    tunnel = _start_tunnel()

    public_url = tunnel.public_url
    print("\n" + "=" * 60)
    print(f"  JARVIS is now reachable at:  {public_url}")
    print("  (this is a public HTTPS URL -- share it, don't post it anywhere public)")
    print("  Local access still works exactly as before:")
    print(f"    http://localhost:{FRONTEND_PORT}")
    print(f"    http://localhost:{BACKEND_PORT}")
    print("=" * 60 + "\n")
    print("Press Ctrl+C to stop the tunnel (and anything this script started).\n")

    def _cleanup(*_args) -> None:
        print("\n[jarvis-remote] Stopping ...")
        try:
            from pyngrok import ngrok
            ngrok.disconnect(public_url)
            ngrok.kill()
        except Exception:
            pass
        # Only terminate what THIS script started -- if FastAPI/Vite
        # were already running before jarvis_remote.py ran, those
        # Popen handles are None and nothing here touches them.
        if frontend_proc is not None:
            frontend_proc.terminate()
        if backend_proc is not None:
            backend_proc.terminate()
        print("[jarvis-remote] Done. Anything that was already running before this script (e.g. your own "
              "`python3 cli.py` session) is untouched.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
