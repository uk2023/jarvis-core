"""TOKEN MANAGEMENT (2026-09-21, UK's explicit spec, given twice).

UK's own words, translated: a dedicated module that records every real
LLM call's token usage, tracked BOTH per-key AND per "portion"
(purpose/call-site -- chat, coding agent, extended thinking, etc.) AND
as one overall aggregate, with the last 3 days of records kept and
older ones auto-purged, and the whole thing PERSISTENT across a JARVIS
restart.

This module does not talk to Groq itself and does not make selection
decisions -- core/orchestration/llm_bridge.py's GroqEngine already owns
real-time per-key telemetry (headers, cooldowns, capacity ordering) for
THAT. This module is the durable RECORD/LEDGER sitting alongside it:
every real call GroqEngine completes gets logged here too, so the
numbers survive a restart and can be broken down by who/what actually
spent the tokens -- exactly what a live in-memory-only telemetry dict
can never give you.

Every number in here comes from a real response body's `usage` block
(prompt_tokens/completion_tokens/total_tokens) passed in by the caller
-- this module never estimates or invents a token count itself.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

RETENTION_SECONDS = 3 * 24 * 3600  # UK: "last 3 days ka data, uske baad delete"


@dataclass
class TokenRecord:
    """One real LLM call's real token usage. Nothing here is estimated."""
    timestamp: float
    purpose: str            # e.g. "chat", "coding_agent", "extended_thinking", "capability_worker"
    provider: str            # e.g. "groq"
    key_index: Optional[int]
    model: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp, "purpose": self.purpose, "provider": self.provider,
            "key_index": self.key_index, "model": self.model,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens, "request_id": self.request_id,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TokenRecord":
        return TokenRecord(
            timestamp=float(d.get("timestamp", 0.0)), purpose=str(d.get("purpose", "unknown")),
            provider=str(d.get("provider", "unknown")), key_index=d.get("key_index"),
            model=d.get("model"), prompt_tokens=int(d.get("prompt_tokens", 0) or 0),
            completion_tokens=int(d.get("completion_tokens", 0) or 0),
            total_tokens=int(d.get("total_tokens", 0) or 0), request_id=d.get("request_id"),
        )


class TokenManager:
    """Disk-backed (JSON, same durable-without-git pattern as
    goal_store.py/backup_tracker.py), thread-safe token ledger.

    Storage shape on disk: {"records": [TokenRecord.to_dict(), ...]}
    -- a flat list, purged of anything older than RETENTION_SECONDS on
    every load AND on every write, so the file itself never grows
    unbounded and a restart picks up exactly what's still "recent".
    """

    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._records: List[TokenRecord] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            # A corrupt/unreadable file must never crash the LLM call
            # path that logs to it -- start fresh rather than raise.
            return
        records = raw.get("records", []) if isinstance(raw, dict) else []
        self._records = [TokenRecord.from_dict(r) for r in records if isinstance(r, dict)]
        self._purge_old(time.time())

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        payload = {"records": [r.to_dict() for r in self._records]}
        tmp_path = self.storage_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, self.storage_path)  # atomic on POSIX -- never a half-written file

    def _purge_old(self, now_t: float) -> None:
        cutoff = now_t - RETENTION_SECONDS
        self._records = [r for r in self._records if r.timestamp >= cutoff]

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(self, purpose: str, provider: str, prompt_tokens: int, completion_tokens: int,
              total_tokens: int, key_index: Optional[int] = None,
              model: Optional[str] = None, request_id: Optional[str] = None) -> None:
        """Log one real call's real usage. Called from GroqEngine right
        after a successful response body is parsed (see llm_bridge.py's
        _record_key_telemetry) -- never from a place that only has an
        estimate."""
        now_t = time.time()
        rec = TokenRecord(
            timestamp=now_t, purpose=purpose or "unknown", provider=provider,
            key_index=key_index, model=model, prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0), total_tokens=int(total_tokens or 0),
            request_id=request_id,
        )
        with self._lock:
            self._records.append(rec)
            self._purge_old(now_t)
            try:
                self._save()
            except Exception:
                # Persistence failing must never break the LLM call that
                # triggered this record -- the in-memory list still has
                # it for this process's lifetime even if the disk write
                # failed once.
                pass

    # ------------------------------------------------------------------
    # Reporting -- what llm_monitor.py / the CLI panel actually reads
    # ------------------------------------------------------------------
    def summary(self, now_t: Optional[float] = None) -> Dict[str, Any]:
        """Real aggregate, per-key, and per-purpose token totals over
        the retained window (up to 3 days). Every number here is a sum
        of real recorded usage -- nothing estimated or backfilled."""
        now_t = now_t if now_t is not None else time.time()
        with self._lock:
            self._purge_old(now_t)
            records = list(self._records)

        overall = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        by_key: Dict[str, Dict[str, Any]] = {}
        by_purpose: Dict[str, Dict[str, Any]] = {}

        for r in records:
            overall["prompt_tokens"] += r.prompt_tokens
            overall["completion_tokens"] += r.completion_tokens
            overall["total_tokens"] += r.total_tokens
            overall["calls"] += 1

            key_label = f"{r.provider}#{r.key_index}" if r.key_index is not None else r.provider
            slot = by_key.setdefault(key_label, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0})
            slot["prompt_tokens"] += r.prompt_tokens
            slot["completion_tokens"] += r.completion_tokens
            slot["total_tokens"] += r.total_tokens
            slot["calls"] += 1

            slot2 = by_purpose.setdefault(r.purpose, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0})
            slot2["prompt_tokens"] += r.prompt_tokens
            slot2["completion_tokens"] += r.completion_tokens
            slot2["total_tokens"] += r.total_tokens
            slot2["calls"] += 1

        return {
            "window_seconds": RETENTION_SECONDS,
            "overall": overall,
            "by_key": by_key,
            "by_purpose": by_purpose,
            "record_count": len(records),
            "oldest_record_at": min((r.timestamp for r in records), default=None),
            "newest_record_at": max((r.timestamp for r in records), default=None),
        }


_shared_manager: Optional[TokenManager] = None
_shared_lock = threading.Lock()


def get_token_manager(storage_path: Optional[str] = None) -> TokenManager:
    """Process-wide shared instance, same lazy-singleton pattern used
    elsewhere in this codebase (e.g. state_bus.get_state_bus). Default
    path follows the same JARVIS_DATA_DIR convention as goal_store.py/
    backup_tracker.py -- core/ must not import backend/config.py, so
    the env var is read directly here too."""
    global _shared_manager
    with _shared_lock:
        if _shared_manager is None:
            if storage_path is None:
                data_dir = os.environ.get("JARVIS_DATA_DIR") or os.path.join(os.getcwd(), "data")
                storage_path = os.path.join(data_dir, "token_usage.json")
            _shared_manager = TokenManager(storage_path)
        return _shared_manager
