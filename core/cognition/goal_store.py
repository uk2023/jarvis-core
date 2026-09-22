"""LONG-TERM GOAL STORE (2026-09-19, UK: "session goal, current goal,
long term goal sab clear ho").

Session goals and per-turn goals live in ConversationState (reset each
session). Long-term goals are different: they must survive a restart,
so they're stored as plain JSON on disk, the same durable-without-git
pattern backup_tracker.py already uses for change history.

A goal only ever gets added here EXPLICITLY -- either the user directly
states one, or the correction-audit process (see correction_audit.py)
consolidates a repeated correction into one and a caller adds it. This
module never infers a long-term goal from a single turn on its own.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LongTermGoal:
    text: str
    added_at: float
    evidence: str
    source: str = "explicit"  # "explicit" (user said it directly) or "audit" (consolidated from repeated corrections)
    times_reinforced: int = 1
    last_reinforced_at: float = field(default_factory=time.time)
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "added_at": self.added_at,
            "evidence": self.evidence,
            "source": self.source,
            "times_reinforced": self.times_reinforced,
            "last_reinforced_at": self.last_reinforced_at,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LongTermGoal":
        return cls(
            text=d["text"], added_at=d["added_at"], evidence=d.get("evidence", ""),
            source=d.get("source", "explicit"), times_reinforced=d.get("times_reinforced", 1),
            last_reinforced_at=d.get("last_reinforced_at", d.get("added_at", time.time())),
            active=d.get("active", True),
        )


class LongTermGoalStore:
    """File-backed, append-and-update persistence for goals that
    outlive one session. Never silently drops a goal -- deactivating
    one (retire_goal) keeps its record with active=False rather than
    deleting it, so "why did JARVIS stop working on X" has a real,
    inspectable answer."""

    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._goals: Dict[str, LongTermGoal] = {}  # normalized text -> goal
        self._load()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("goals", []):
                g = LongTermGoal.from_dict(entry)
                self._goals[self._normalize(g.text)] = g
        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupt/unreadable file -- start fresh rather than crash,
            # never silently claim goals that couldn't actually be read.
            self._goals = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(
                {"goals": [g.to_dict() for g in self._goals.values()]},
                f, ensure_ascii=False, indent=2,
            )

    def add_goal(self, text: str, evidence: str, source: str = "explicit") -> LongTermGoal:
        """Add a new long-term goal, or reinforce an existing matching
        one (same normalized text) rather than duplicating it."""
        key = self._normalize(text)
        if key in self._goals:
            existing = self._goals[key]
            existing.times_reinforced += 1
            existing.last_reinforced_at = time.time()
            existing.active = True
            self._save()
            return existing
        goal = LongTermGoal(text=text, added_at=time.time(), evidence=evidence, source=source)
        self._goals[key] = goal
        self._save()
        return goal

    def retire_goal(self, text: str) -> bool:
        """Mark a goal inactive -- kept on record, not deleted."""
        key = self._normalize(text)
        if key not in self._goals:
            return False
        self._goals[key].active = False
        self._save()
        return True

    def get_active_goals(self) -> List[str]:
        return [g.text for g in self._goals.values() if g.active]

    def get_all_goals(self) -> List[LongTermGoal]:
        return list(self._goals.values())
