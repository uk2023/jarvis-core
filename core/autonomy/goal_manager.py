from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event


class GoalManager:
    """
    Tracks JARVIS's goals and persists them through the SQLiteStore's
    organism_meta table (key = 'goals'), so goals survive restarts.

    A goal is a plain dict:
        {
            "id": str,
            "text": str,
            "priority": float,   # 0..1, higher = more important
            "status": "pending" | "active" | "completed" | "abandoned",
            "origin": str,       # "user" | "curiosity" | "self"
            "created_at": float,
            "updated_at": float,
            "progress": list[dict],
            "plan": list[dict],
            "step_index": int,
        }

    No LLM calls happen here. This module only manages bookkeeping;
    the Planner decides *how* to pursue a goal.
    """

    META_KEY = "goals"

    def __init__(self, store=None):
        self.store = store
        self.goals: List[Dict[str, Any]] = []

        if self.store is not None:
            self._load()

    # =============================================================
    # PERSISTENCE
    # =============================================================

    def _load(self) -> None:
        try:
            saved = self.store.get_meta(self.META_KEY)
        except Exception:
            saved = None

        if isinstance(saved, list):
            self.goals = saved

    def _save(self) -> None:
        if self.store is None:
            return

        try:
            self.store.set_meta(self.META_KEY, self.goals)
        except Exception as exc:
            log_event("goal_manager", f"failed to persist goals: {exc}", level="error")

    # =============================================================
    # MUTATIONS
    # =============================================================

    def add(
        self,
        text: str,
        priority: float = 0.5,
        origin: str = "user",
    ) -> Dict[str, Any]:
        if not text:
            raise ValueError("Goal text cannot be empty.")

        now = time.time()

        goal = {
            "id": str(uuid.uuid4()),
            "text": text,
            "priority": max(0.0, min(1.0, priority)),
            "status": "pending",
            "origin": origin,
            "created_at": now,
            "updated_at": now,
            "progress": [],
            "plan": [],
            "step_index": 0,
        }

        self.goals.append(goal)
        self._save()
        return goal

    def update_status(self, goal_id: str, status: str) -> Optional[Dict[str, Any]]:
        goal = self._find(goal_id)

        if goal is None:
            return None

        goal["status"] = status
        goal["updated_at"] = time.time()
        self._save()
        return goal

    def add_progress(self, goal_id: str, note: str) -> Optional[Dict[str, Any]]:
        goal = self._find(goal_id)

        if goal is None:
            return None

        goal.setdefault("progress", []).append({"note": note, "timestamp": time.time()})
        goal["updated_at"] = time.time()
        self._save()
        return goal

    def set_plan(self, goal_id: str, plan: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        goal = self._find(goal_id)
        if goal is None:
            return None
        goal["plan"] = list(plan or [])
        goal["step_index"] = 0
        goal["updated_at"] = time.time()
        self._save()
        return goal

    def advance_step(self, goal_id: str) -> Optional[Dict[str, Any]]:
        goal = self._find(goal_id)
        if goal is None:
            return None
        goal["step_index"] = int(goal.get("step_index", 0)) + 1
        goal["updated_at"] = time.time()
        self._save()
        return goal

    def remove(self, goal_id: str) -> bool:
        before = len(self.goals)
        self.goals = [g for g in self.goals if g["id"] != goal_id]

        changed = len(self.goals) != before
        if changed:
            self._save()

        return changed

    # =============================================================
    # QUERIES
    # =============================================================

    def _find(self, goal_id: str) -> Optional[Dict[str, Any]]:
        for g in self.goals:
            if g["id"] == goal_id:
                return g
        return None

    @property
    def current_goal(self) -> Optional[Dict[str, Any]]:
        """Return the highest-priority active goal for cognition context."""
        active = [g for g in self.goals if g.get("status") == "active"]
        if not active:
            return None
        return sorted(active, key=lambda g: (-g.get("priority", 0.0), g.get("created_at", 0.0)))[0]

    def pending(self) -> List[Dict[str, Any]]:
        return [g for g in self.goals if g.get("status") in ("pending", "active")]

    def next_goal(self) -> Optional[Dict[str, Any]]:
        """Highest-priority pending goal, oldest first as a tiebreaker."""

        candidates = self.pending()

        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda g: (-g["priority"], g["created_at"]),
        )[0]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "total": len(self.goals),
            "pending": len(self.pending()),
            "completed": len([g for g in self.goals if g["status"] == "completed"]),
        }
