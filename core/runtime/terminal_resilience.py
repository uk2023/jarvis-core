from __future__ import annotations

"""SURVIVING TERMUX GOING TO THE BACKGROUND.

THE ACTUAL CRASH, from UK's own crashes.jsonl (2026-09-16):

    04:35:08  signal:SIGHUP        rss=74.8MB  peak=219.1MB  uptime=17667s
    04:35:08  unhandled:OSError    [Errno 5] Input/output error
              File "rich/console.py", line 2124, in _write_buffer
                  self.file.write(text)
              OSError: [Errno 5] Input/output error

This is NOT an out-of-memory crash, and it never was. RSS at the moment
of death was 74.8 MB with 2250 MB free on the device. Every memory fix
this project made -- the ONNX arena caps, the TLS session reuse, the
episode flattening -- was real work on real problems, but none of them
could ever have stopped THIS, because this is a different failure
entirely.

WHAT ACTUALLY HAPPENS
=====================
Android backgrounds Termux (UK: "background se apne aap kill ho raha").
The terminal's pty is torn down. The kernel sends SIGHUP to the
foreground process group -- that is precisely what SIGHUP means: the
terminal hung up.

Python's default SIGHUP action terminates the process. And even where
it does not, the next thing JARVIS does is print a status line through
`rich`, which writes to a file descriptor that no longer has a terminal
on the other end -- so the write fails with OSError Errno 5, which
nothing catches, and the process dies with an unhandled exception.

Two deaths, same root cause, both visible in the crash log above,
0.4 seconds apart.

THE FIX
=======
  1. IGNORE SIGHUP. A long-running background service has no business
     dying because a terminal closed. Once ignored, backgrounding
     Termux no longer signals JARVIS at all.

  2. SURVIVE WRITES TO A DEAD TERMINAL. Ignoring the signal alone is
     not enough -- stdout still points at a closed pty, so the very
     next print raises OSError. install_resilient_stdio() wraps stdout
     and stderr so that an EIO/EBADF write is swallowed rather than
     raised, and flips the process into "terminal is gone" mode: output
     goes to the log file from that point on instead of being thrown at
     a descriptor that cannot accept it.

WHY NOT JUST nohup?
===================
`nohup python3 cli.py &` would also ignore SIGHUP, and UK can still do
that. But it requires him to remember, every single time, and it does
nothing about the OSError on write -- the process would survive the
signal and then die on the next status line anyway. Handling it in-
process fixes it for every way of launching JARVIS, including the ones
UK already has muscle memory for.
"""

import os
import signal
import sys
import threading
from typing import Any, Optional, TextIO

_lock = threading.RLock()
_terminal_alive = True
_fallback_log_path = "data/logs/detached_output.log"
_fallback_handle: Optional[TextIO] = None

# Errors that mean "this descriptor can no longer be written to". Not a
# transient failure -- once the pty is gone it never comes back, so the
# right response is to stop writing to it, not to retry.
_DEAD_FD_ERRNOS = {
    5,    # EIO   -- terminal hung up (the one in UK's crash log)
    9,    # EBADF -- descriptor closed
    32,   # EPIPE -- other end gone
}


def terminal_is_alive() -> bool:
    return _terminal_alive


def _open_fallback() -> Optional[TextIO]:
    """Where output goes once the terminal is gone. Opened lazily -- a
    process whose terminal never dies never creates this file."""
    global _fallback_handle
    if _fallback_handle is not None:
        return _fallback_handle
    try:
        os.makedirs(os.path.dirname(_fallback_log_path), exist_ok=True)
        _fallback_handle = open(_fallback_log_path, "a", encoding="utf-8", errors="replace")
        _fallback_handle.write(
            "\n--- terminal detached; JARVIS still running, output continues here ---\n"
        )
        _fallback_handle.flush()
    except Exception:
        _fallback_handle = None
    return _fallback_handle


class _ResilientStream:
    """Wraps stdout/stderr so a dead terminal cannot kill the process.

    Deliberately NOT a full io.TextIOBase subclass: only the methods
    actually used on stdout are overridden, and everything else is
    delegated. A partial, honest wrapper is safer here than a
    reimplementation that might differ subtly from the real stream in
    some path nobody tested.
    """

    def __init__(self, wrapped: TextIO):
        self._wrapped = wrapped

    def write(self, text: str) -> int:
        global _terminal_alive
        if _terminal_alive:
            try:
                return self._wrapped.write(text)
            except OSError as exc:
                if exc.errno not in _DEAD_FD_ERRNOS:
                    raise
                # The terminal just died. Note it once, then fall
                # through to the log file -- do NOT re-raise, which is
                # exactly what killed the process before this existed.
                with _lock:
                    _terminal_alive = False
            except ValueError:
                # "I/O operation on closed file" -- same situation,
                # different exception type depending on how it closed.
                with _lock:
                    _terminal_alive = False

        handle = _open_fallback()
        if handle is None:
            return 0
        try:
            return handle.write(text)
        except Exception:
            return 0

    def flush(self) -> None:
        target = self._wrapped if _terminal_alive else _fallback_handle
        if target is None:
            return
        try:
            target.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        if not _terminal_alive:
            return False
        try:
            return self._wrapped.isatty()
        except Exception:
            return False

    def fileno(self) -> int:
        return self._wrapped.fileno()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def install_resilient_stdio() -> None:
    """Make stdout/stderr survive the terminal disappearing."""
    if not isinstance(sys.stdout, _ResilientStream):
        sys.stdout = _ResilientStream(sys.stdout)   # type: ignore[assignment]
    if not isinstance(sys.stderr, _ResilientStream):
        sys.stderr = _ResilientStream(sys.stderr)   # type: ignore[assignment]


def ignore_terminal_hangup() -> bool:
    """Stop SIGHUP from killing JARVIS when Termux is backgrounded.

    Returns True if the signal is now ignored. SIGHUP does not exist on
    every platform, so failure here is not an error -- it just means
    there was nothing to guard against.
    """
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        return True
    except (AttributeError, ValueError, OSError):
        return False


def harden_against_backgrounding() -> dict:
    """Both halves of the fix, applied together.

    Call this ONCE, as early as possible in the entry point -- before
    any output is produced, so no print can land in the window between
    the terminal dying and this being installed.
    """
    sighup_ignored = ignore_terminal_hangup()
    install_resilient_stdio()
    return {
        "sighup_ignored": sighup_ignored,
        "stdio_hardened": True,
        "fallback_log": _fallback_log_path,
    }
