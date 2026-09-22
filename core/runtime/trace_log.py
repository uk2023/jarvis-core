from __future__ import annotations

"""Persistent per-turn trace log.

Problem this fixes (UK's #4): Brain.last_turn_trace and
StateBus.pipeline_trace both hold at most one (or a handful of)
recent turns in memory -- the instant the NEXT turn happens, the
previous turn's raw perception output, semantic-understanding output,
LLM response text, grounding-check result, and budget usage are gone
forever. JARVIS itself has no durable record of its own past
reasoning to learn from or be asked about.

This module is the fix: every turn gets ONE JSON line appended to a
per-day file under runtime/trace_log/. Append-only, so a crash mid-
write can never corrupt a previous day's data (worst case: one
truncated last line, which read_recent() below tolerates by skipping
unparseable lines rather than failing the whole read).

This is deliberately a separate, dumber, more durable sibling to
StateBus (which optimizes for "one live snapshot for a monitor to
poll", not "every turn, forever, on disk"). Two consumers depend on
this data existing:
    - core/learning/native_response_learning.py (UK's #5): mines this
      log for repeated (input -> grounded, unflagged response) pairs
      to propose native response templates.
    - Any future introspection command ("JARVIS, tumhara Nth pehla
      jawab kya tha") reads directly from here.
"""

import json
import os
import threading
import time
from typing import Any, Dict, Iterator, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DIR = os.path.join(BASE_DIR, "runtime", "trace_log")
DEFAULT_RETENTION_DAYS = 30


def _safe_json(value: Any, max_chars: int = 4000) -> Any:
    """Bounded, never-raises JSON-safety pass -- a turn's raw context
    can contain nested objects (perception dataclasses, etc.) that
    json.dumps would choke on; fall back to a truncated repr rather
    than losing the whole trace line to one bad field."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > max_chars:
            return json.loads(json.dumps(str(value)[:max_chars] + "…<truncated>"))
        return json.loads(text)
    except Exception:
        try:
            return str(value)[:max_chars]
        except Exception:
            return "<unserializable>"


class TraceLog:
    """Append-only, rotating (daily file), retention-pruned turn log."""

    def __init__(self, directory: Optional[str] = None, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.directory = directory or os.getenv("JARVIS_TRACE_LOG_DIR") or DEFAULT_DIR
        self.retention_days = max(1, int(retention_days))
        self._lock = threading.RLock()
        self._last_prune = 0.0

    def _path_for(self, ts: float) -> str:
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        return os.path.join(self.directory, f"{day}.jsonl")

    def write(self, entry: Dict[str, Any]) -> bool:
        """Append one turn. Never raises -- a trace-log failure must
        never break the response already produced for the user (same
        discipline as _enqueue_learning's own try/except)."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            ts = float(entry.get("timestamp") or time.time())
            payload = {"timestamp": ts, **{k: _safe_json(v) for k, v in entry.items() if k != "timestamp"}}
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            path = self._path_for(ts)
            with self._lock:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                self._maybe_prune()
            return True
        except Exception:
            return False

    def _maybe_prune(self, min_interval: float = 3600.0) -> None:
        """Delete files older than retention_days -- at most once an
        hour, so this never becomes per-write disk-listing overhead."""
        now = time.time()
        if now - self._last_prune < min_interval:
            return
        self._last_prune = now
        try:
            cutoff = now - (self.retention_days * 86400)
            for name in os.listdir(self.directory):
                if not name.endswith(".jsonl"):
                    continue
                path = os.path.join(self.directory, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass
        except OSError:
            pass

    def iter_all(self, limit_files: int = DEFAULT_RETENTION_DAYS) -> Iterator[Dict[str, Any]]:
        """Yield every readable trace entry, oldest file first,
        skipping any line that fails to parse (see module docstring)
        rather than aborting the whole read."""
        try:
            names = sorted(f for f in os.listdir(self.directory) if f.endswith(".jsonl"))
        except OSError:
            return
        for name in names[-limit_files:]:
            path = os.path.join(self.directory, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except (ValueError, TypeError):
                            continue
            except OSError:
                continue

    def read_recent(self, limit: int = 50) -> list:
        """Most-recent-first. Reads at most the last 3 days' files
        before slicing, so this stays cheap even with weeks of history."""
        entries = list(self.iter_all(limit_files=3))
        entries.reverse()
        return entries[:limit]

    def count(self) -> int:
        return sum(1 for _ in self.iter_all())

    def status(self) -> Dict[str, Any]:
        try:
            names = sorted(f for f in os.listdir(self.directory) if f.endswith(".jsonl"))
        except OSError:
            names = []
        return {
            "directory": self.directory,
            "retention_days": self.retention_days,
            "files": len(names),
            "oldest_file": names[0] if names else None,
            "newest_file": names[-1] if names else None,
        }

    # RuntimeMonitor._stats() generic organ helper looks for this name.
    statistics = status


_default_trace_log: Optional[TraceLog] = None
_default_lock = threading.Lock()


def get_trace_log() -> TraceLog:
    """Process-wide singleton -- every caller (Brain, native response
    learning, future introspection commands) shares one instance so
    they agree on the same directory/retention without each having to
    be wired with explicit config."""
    global _default_trace_log
    with _default_lock:
        if _default_trace_log is None:
            _default_trace_log = TraceLog()
        return _default_trace_log
