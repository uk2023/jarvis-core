from __future__ import annotations

"""Procedural memory (UK's #2 recall/learning/memory proposal).

Memory psychology draws a real distinction between three memory
types: DECLARATIVE (facts you know -- semantic_memory.py),
EPISODIC (events you experienced -- episodic_memory.py), and
PROCEDURAL (learned habits/skills for HOW to do something, recalled
without deliberate thought). JARVIS already had the first two as
first-class organs, but procedural memory was only ever an implicit
side effect living inside native_response_learning.py's own private
dict -- there was no formal "this is a skill/habit JARVIS learned"
concept anywhere.

This module gives procedural memory a proper home: a small,
persistent key -> learned-procedure store. native_response_learning.py
now delegates its actual storage here instead of keeping its own
private dict, so "JARVIS learned a habit" is a real, named, queryable
memory type -- not an implementation detail of one specific feature.
Future procedural learning (e.g. a learned SKILL, not just a response
template) has a real place to live now instead of needing its own
bespoke storage each time.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_STORAGE_PATH = os.path.join(BASE_DIR, "runtime", "procedural_memory.json")


class ProceduralMemory:
    """Key -> learned procedure. A procedure is "what to do" given a
    trigger, plus provenance (how confident, how many times it fired,
    when it was learned, which kind of procedure it is)."""

    VERSION = "0.1.0"

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path or DEFAULT_STORAGE_PATH
        self._lock = threading.RLock()
        self.procedures: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.storage_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self.procedures = data
        except (OSError, ValueError):
            self.procedures = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            tmp = self.storage_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.procedures, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)
        except OSError:
            pass

    def learn(self, trigger: str, action: Any, kind: str = "response_template",
              metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record a learned procedure. `trigger` is the normalized key
        that recalls it (e.g. a normalized greeting); `action` is what
        to do/say; `kind` distinguishes procedure types so future
        skill-learning doesn't get confused with response templates."""
        with self._lock:
            self.procedures[trigger] = {
                "action": action,
                "kind": kind,
                "metadata": metadata or {},
                "learned_at": time.time(),
                "hits": 0,
            }
            self._save()

    def recall(self, trigger: str) -> Optional[Any]:
        """Exact-key lookup, incrementing the hit counter -- the
        procedural-memory equivalent of SemanticMemory.reinforce():
        a habit that keeps getting used is worth knowing is actually
        being used."""
        with self._lock:
            entry = self.procedures.get(trigger)
            if entry is None:
                return None
            entry["hits"] = int(entry.get("hits", 0)) + 1
            return entry.get("action")

    def has(self, trigger: str) -> bool:
        """Existence check that does NOT increment the hit counter --
        for callers (like mining's dedup check) that need to know
        "is this already learned" without counting it as a genuine
        recall/use. See .recall() for the counting version."""
        with self._lock:
            return trigger in self.procedures

    def forget(self, trigger: str) -> bool:
        with self._lock:
            if trigger in self.procedures:
                del self.procedures[trigger]
                self._save()
                return True
            return False

    def by_kind(self, kind: str) -> List[Dict[str, Any]]:
        return [dict(v, trigger=k) for k, v in self.procedures.items() if v.get("kind") == kind]

    def status(self) -> Dict[str, Any]:
        by_kind_counts: Dict[str, int] = {}
        total_hits = 0
        for entry in self.procedures.values():
            kind = str(entry.get("kind", "unknown"))
            by_kind_counts[kind] = by_kind_counts.get(kind, 0) + 1
            total_hits += int(entry.get("hits", 0))
        return {
            "version": self.VERSION,
            "procedure_count": len(self.procedures),
            "by_kind": by_kind_counts,
            "total_hits": total_hits,
        }

    statistics = status


_default_procedural_memory: Optional[ProceduralMemory] = None
_default_lock = threading.Lock()


def get_procedural_memory() -> ProceduralMemory:
    global _default_procedural_memory
    with _default_lock:
        if _default_procedural_memory is None:
            _default_procedural_memory = ProceduralMemory()
        return _default_procedural_memory
