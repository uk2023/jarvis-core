from __future__ import annotations

"""Internal, non-stdout logging for the JARVIS runtime.

Several organs used to fall back to bare print() on error paths
(EventBus subscriber failures, learning-queue job failures, ONNX
embedder warnings, LLM bridge backend switches). Under cli.py's Rich
Live console, an interleaved print() call corrupts the live render
and is the single biggest contributor to "crowded/unreadable" output.

This module gives every organ a single, cheap, dependency-free way to
record that same information WITHOUT ever touching stdout/stderr:

    from core.runtime.log import log_event
    log_event("learning_queue", "job failed: ...", level="error")

Events go to:
  1. a rotating-by-size plain text file at logs/jarvis_runtime.log
  2. the in-memory ring buffer inside core.runtime.state_bus (if the
     state bus has already been initialized in this process), so
     monitor.py can show the last N runtime log lines live.

Both sinks are best-effort: a logging failure must never raise into
the caller's real code path.
"""

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "jarvis_runtime.log")

_lock = threading.Lock()
_logger: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    with _lock:
        if _logger is not None:
            return _logger
        logger = logging.getLogger("jarvis.runtime")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # never bubble up to root -> never stdout
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            handler = RotatingFileHandler(
                LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
            logger.addHandler(handler)
        except OSError:
            # Filesystem unavailable (read-only, sandboxed, etc.) --
            # keep a null handler so log calls remain cheap no-ops
            # instead of raising.
            logger.addHandler(logging.NullHandler())
        _logger = logger
    return _logger


_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def log_event(tag: str, message: str, level: str = "info") -> None:
    """Record one runtime event. Never raises, never prints."""
    try:
        _get_logger().log(_LEVELS.get(level, logging.INFO), "[%s] %s", tag, message)
    except Exception:
        pass

    # Best-effort mirror into the live state bus, if one is running in
    # this process. Imported lazily to avoid a hard import cycle
    # (state_bus does not depend on log, but keeping the import local
    # here means core.runtime.log has zero import-time dependencies).
    try:
        from core.runtime.state_bus import get_state_bus

        bus = get_state_bus(create=False)
        if bus is not None:
            bus.record_log(tag=tag, message=message, level=level)
    except Exception:
        pass
