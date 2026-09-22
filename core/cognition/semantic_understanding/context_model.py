"""Small contextual/temporal model for semantic understanding."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class ContextModel:
    VERSION = "0.1.0"

    def __init__(self, max_turns: int = 8) -> None:
        self.max_turns = max(1, int(max_turns))
        self._turns: Deque[Dict[str, Any]] = deque(maxlen=self.max_turns)
        self.state: Dict[str, Any] = {}

    def update(self, semantic: Dict[str, Any], *, source: str = "perception") -> Dict[str, Any]:
        turn = {"timestamp": time.time(), "source": source, "semantic": dict(semantic)}
        self._turns.append(turn)
        self.state["last_intent"] = semantic.get("intent")
        self.state["last_language"] = semantic.get("language")
        self.state["last_entities"] = semantic.get("entities", [])
        return self.snapshot()

    def recent(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        items = list(self._turns)
        return items[-limit:] if limit else items

    def snapshot(self) -> Dict[str, Any]:
        return {"state": dict(self.state), "recent_turns": self.recent()}
