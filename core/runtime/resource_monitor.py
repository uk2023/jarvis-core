from __future__ import annotations

"""WHERE THE MEMORY IS GOING, AND WHAT KILLED THE PROCESS.

UK, after the last tarball: "abhi bhi crash hota hai, RAM explode ho
raha hai... monitor.py pe trace lagao RAM ka, aur JARVIS ne kitna use
kiya live aur average sab show ho, saath hi system unexpected crash pe
log ho kya error tha."

He is right to ask for measurement rather than another guess. I fixed
the episode-nesting bomb and it is still crashing, which means either
that was not the only cause or not the main one. Guessing again would
waste another round.

WHAT THIS RECORDS
=================
  * RSS every few seconds -- current, peak, and a rolling average, so
    "it grows over a long session" becomes a number instead of a
    feeling.
  * GROWTH ATTRIBUTION: alongside each sample, the sizes of the things
    that plausibly grow -- DB files on disk, the learning queue depth,
    Brain's context cache, the FAISS index, thread count. When RSS
    climbs, the sample beside it says what climbed with it.
  * CRASH CAPTURE: an excepthook and a SIGTERM handler that write the
    traceback, the last RSS reading and the recent samples BEFORE the
    process dies. Five Termux crashes so far have left no record of
    what happened, which is the actual reason this is still unsolved.

HONEST LIMITS
=============
An OOM kill by the Android kernel does NOT run Python's excepthook --
the process is simply gone. Nothing in-process can catch that. What we
CAN do is leave a breadcrumb trail: samples are flushed to disk as they
are taken, so after an OOM the last sample still shows how much RSS had
grown and what was large at the time. That is how a kill gets diagnosed
-- from what was written before it, not from a handler that never runs.

psutil is used when present and a /proc fallback is used when not,
because Termux installs vary and a missing dependency must not take the
monitoring down with it.
"""

import json
import os
import signal
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

SAMPLE_DIR = Path("data/resource")
SAMPLES_FILE = SAMPLE_DIR / "samples.jsonl"
CRASH_FILE = SAMPLE_DIR / "crashes.jsonl"

SAMPLE_INTERVAL = 5.0
IN_MEMORY_SAMPLES = 240          # ~20 min at 5s, bounded on purpose
MAX_SAMPLE_FILE_BYTES = 2 * 1024 * 1024

_lock = threading.RLock()
_samples: Deque[Dict[str, Any]] = deque(maxlen=IN_MEMORY_SAMPLES)
_peak_rss = 0.0
_started_at = time.time()
_sampler_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_brain_ref: Any = None


def ist(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), IST).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# --------------------------------------------------------------- reading
def _rss_mb() -> float:
    """Resident set size in MB. psutil if available, /proc otherwise."""
    try:
        import psutil  # type: ignore
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        # /proc/self/statm: field 2 is resident pages.
        with open("/proc/self/statm", "r") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except Exception:
        return 0.0


def _system_mem() -> Dict[str, float]:
    """Device-wide memory, so 'JARVIS is 400MB' can be read against how
    much the phone actually has."""
    try:
        info: Dict[str, float] = {}
        with open("/proc/meminfo", "r") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[0].rstrip(":") in ("MemTotal", "MemAvailable"):
                    info[parts[0].rstrip(":")] = float(parts[1]) / 1024.0
        return {
            "total_mb": round(info.get("MemTotal", 0.0), 1),
            "available_mb": round(info.get("MemAvailable", 0.0), 1),
        }
    except Exception:
        return {"total_mb": 0.0, "available_mb": 0.0}


def _db_sizes_mb() -> Dict[str, float]:
    """On-disk growth. A DB that balloons is usually the same thing that
    is ballooning in memory, because it gets read back in."""
    out: Dict[str, float] = {}
    try:
        for path in Path("data").rglob("*.db"):
            try:
                out[path.name] = round(path.stat().st_size / (1024 * 1024), 2)
            except Exception:
                continue
        for extra in (Path("data").rglob("*.index"), Path("data").rglob("*.faiss")):
            for path in extra:
                try:
                    out[path.name] = round(path.stat().st_size / (1024 * 1024), 2)
                except Exception:
                    continue
    except Exception:
        pass
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:6])


def _brain_internals() -> Dict[str, Any]:
    """In-process structures that are known to grow. Read defensively --
    a missing attribute must never break sampling."""
    info: Dict[str, Any] = {}
    brain = _brain_ref
    if brain is None:
        return info
    try:
        cache = getattr(brain, "_context_cache", None)
        if cache is not None:
            info["context_cache_entries"] = len(cache)
    except Exception:
        pass
    for attr, label in (("_learning_queue", "learning_queue"),
                        ("reasoning_history", "reasoning_history"),
                        ("_post_response_history", "post_response_history")):
        try:
            value = getattr(brain, attr, None)
            if value is not None and hasattr(value, "__len__"):
                info[label] = len(value)
            elif value is not None and hasattr(value, "qsize"):
                info[label] = value.qsize()
        except Exception:
            continue
    return info


def sample() -> Dict[str, Any]:
    """One reading. Cheap enough to take every few seconds."""
    global _peak_rss
    rss = _rss_mb()
    with _lock:
        _peak_rss = max(_peak_rss, rss)
    entry = {
        "ts": time.time(),
        "ts_ist": ist(),
        "rss_mb": round(rss, 1),
        "threads": threading.active_count(),
        "system": _system_mem(),
        "dbs": _db_sizes_mb(),
        "brain": _brain_internals(),
        "uptime_s": round(time.time() - _started_at, 1),
    }
    with _lock:
        _samples.append(entry)
    return entry


def _flush(entry: Dict[str, Any]) -> None:
    """Write each sample immediately.

    Buffering would be cheaper and useless: an OOM kill takes the buffer
    with it, and the last minutes before a kill are exactly the data
    worth having.
    """
    try:
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        if SAMPLES_FILE.exists() and SAMPLES_FILE.stat().st_size > MAX_SAMPLE_FILE_BYTES:
            # Keep the tail; the run that matters is the current one.
            lines = SAMPLES_FILE.read_text(encoding="utf-8").splitlines()[-2000:]
            SAMPLES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with open(SAMPLES_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
    except Exception:
        pass


SPIKES_FILE = SAMPLE_DIR / "spikes.jsonl"

# THE UNRESOLVED SPIKE (2026-09-14). UK's own 9.5-hour sample log shows
# the fix in this file (arena disabled, threads capped on the ONNX
# sessions) did NOT change the peak: RSS still jumps to ~1.7-2.1GB in
# ~13 seconds, repeatedly -- not just at startup, but roughly every
# 700-1400 seconds throughout a long-running process. That rules out
# "one-time model load" as the sole explanation; something periodic is
# doing this, and static reading of the codebase did not conclusively
# identify what.
#
# Rather than keep guessing, this captures what is ACTUALLY RUNNING the
# moment a spike is detected: every live thread's current stack frame.
# The spike takes ~13s and sampling runs every 5s, so a jump this large
# between two consecutive samples is caught while the responsible code
# is still on the stack (or immediately after) far more often than not.
# Next time this happens, spikes.jsonl will name the actual function,
# not just the number.
SPIKE_THRESHOLD_MB = 300.0


def _capture_spike(prev_rss: float, entry: Dict[str, Any]) -> None:
    """Dump every thread's current frame. Cheap enough to call inline --
    this only runs on the rare tick where RSS jumped, not every sample."""
    import sys
    import traceback

    frames = {}
    try:
        for thread_id, frame in sys._current_frames().items():
            frames[str(thread_id)] = "".join(traceback.format_stack(frame))
    except Exception as exc:
        frames = {"error": str(exc)}

    spike = {
        "ts": entry["ts"],
        "ts_ist": entry["ts_ist"],
        "rss_before_mb": prev_rss,
        "rss_after_mb": entry["rss_mb"],
        "jump_mb": round(entry["rss_mb"] - prev_rss, 1),
        "uptime_s": entry.get("uptime_s"),
        "thread_stacks": frames,
    }
    try:
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        with open(SPIKES_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(spike, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass


def _loop() -> None:
    prev_rss: Optional[float] = None
    while not _stop.wait(SAMPLE_INTERVAL):
        try:
            entry = sample()
            if prev_rss is not None and (entry["rss_mb"] - prev_rss) >= SPIKE_THRESHOLD_MB:
                _capture_spike(prev_rss, entry)
            prev_rss = entry["rss_mb"]
            _flush(entry)
        except Exception:
            continue


def start(brain: Any = None) -> None:
    """Begin sampling. Idempotent."""
    global _sampler_thread, _brain_ref, _started_at
    if brain is not None:
        _brain_ref = brain
    if _sampler_thread and _sampler_thread.is_alive():
        return
    _started_at = time.time()
    _stop.clear()
    _install_crash_handlers()
    _flush(sample())
    _sampler_thread = threading.Thread(target=_loop, name="resource-sampler", daemon=True)
    _sampler_thread.start()


def stop() -> None:
    _stop.set()


# ---------------------------------------------------------------- crashes
def record_crash(kind: str, detail: str, tb: Optional[str] = None) -> None:
    """Write what happened, with the last resource reading attached."""
    try:
        SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            last = _samples[-1] if _samples else None
            recent = list(_samples)[-12:]
        entry = {
            "ts": time.time(),
            "ts_ist": ist(),
            "kind": kind,
            "detail": detail[:4000],
            "traceback": (tb or "")[:8000],
            "rss_mb_at_crash": last.get("rss_mb") if last else None,
            "peak_rss_mb": round(_peak_rss, 1),
            "uptime_s": round(time.time() - _started_at, 1),
            "recent_samples": recent,
        }
        with open(CRASH_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass


def _install_crash_handlers() -> None:
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        record_crash(
            kind=f"unhandled:{getattr(exc_type, '__name__', 'Exception')}",
            detail=str(exc_value),
            tb="".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook

    def _thread_hook(args):
        record_crash(
            kind=f"thread:{getattr(args.exc_type, '__name__', 'Exception')}",
            detail=f"{args.thread.name if args.thread else '?'}: {args.exc_value}",
            tb="".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass

    for sig, name in ((signal.SIGTERM, "SIGTERM"), (getattr(signal, "SIGHUP", None), "SIGHUP")):
        if sig is None:
            continue
        try:
            previous = signal.getsignal(sig)

            def _make(signame, prev):
                def _handler(signum, frame):
                    # SIGTERM is what Android's low-memory killer sends
                    # before SIGKILL, so this one IS catchable and is the
                    # most likely crash signal on a phone.
                    record_crash(kind=f"signal:{signame}",
                                 detail=f"process received {signame}",
                                 tb="".join(traceback.format_stack(frame)))
                    if callable(prev):
                        prev(signum, frame)
                    else:
                        raise SystemExit(143)
                return _handler

            signal.signal(sig, _make(name, previous))
        except Exception:
            continue


# ------------------------------------------------------------- reporting
def report() -> Dict[str, Any]:
    """Live, peak, average and what is growing -- for monitor.py."""
    with _lock:
        samples = list(_samples)
        peak = _peak_rss

    if not samples:
        current = sample()
        samples = [current]
        peak = current["rss_mb"]

    rss_values = [s["rss_mb"] for s in samples if s.get("rss_mb")]
    avg = sum(rss_values) / len(rss_values) if rss_values else 0.0
    latest = samples[-1]

    # Growth over the window: the number that says whether this is a
    # leak or just a high baseline.
    growth = 0.0
    window_minutes = 0.0
    if len(samples) > 1:
        growth = samples[-1]["rss_mb"] - samples[0]["rss_mb"]
        window_minutes = (samples[-1]["ts"] - samples[0]["ts"]) / 60.0

    system = latest.get("system") or {}
    return {
        "rss_mb": latest.get("rss_mb", 0.0),
        "peak_mb": round(peak, 1),
        "avg_mb": round(avg, 1),
        "growth_mb": round(growth, 1),
        "window_minutes": round(window_minutes, 1),
        "growth_per_hour_mb": round(growth / window_minutes * 60, 1) if window_minutes > 0.5 else None,
        "threads": latest.get("threads"),
        "system_total_mb": system.get("total_mb"),
        "system_available_mb": system.get("available_mb"),
        "dbs": latest.get("dbs") or {},
        "brain": latest.get("brain") or {},
        "uptime_s": latest.get("uptime_s", 0),
        "samples": len(samples),
    }


def recent_crashes(limit: int = 5) -> List[Dict[str, Any]]:
    try:
        if not CRASH_FILE.exists():
            return []
        lines = CRASH_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                entry.pop("recent_samples", None)   # too big for a list view
                out.append(entry)
            except Exception:
                continue
        return out
    except Exception:
        return []


def recent_spikes(limit: int = 3, full_stacks: bool = False) -> List[Dict[str, Any]]:
    """RSS jumps caught in the act. With full_stacks=False (the monitor
    panel's default) this returns just the innermost frame of each
    thread's stack -- one line, enough to name the function that was
    running -- since the full multi-thread traceback is usually too
    long for a status panel but is always in spikes.jsonl on disk for a
    deeper look."""
    try:
        if not SPIKES_FILE.exists():
            return []
        lines = SPIKES_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if not full_stacks:
                    innermost = {}
                    for thread_id, stack in (entry.get("thread_stacks") or {}).items():
                        last_line = [l for l in stack.strip().splitlines() if l.strip()][-1:] or [""]
                        innermost[thread_id] = last_line[0].strip()
                    entry["thread_stacks"] = innermost
                out.append(entry)
            except Exception:
                continue
        return out
    except Exception:
        return []
