"""Dependency-light semantic parser.

The parser converts normalized natural language into a structured semantic
representation. It intentionally uses conservative heuristics and never
invents external facts. An LLM can later supply richer parsing through the
same output contract without changing downstream components.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SemanticParser:
    VERSION = "0.1.0"

    _INTENT_PATTERNS = (
        ("question", re.compile(r"^(?:what|why|how|when|where|who|which|can|could|is|are|do|does|did|kya|kyu|kaise|kab|kahan|kaun|hai|hain)\\b", re.I)),
        ("command", re.compile(r"^(?:open|start|run|stop|search|find|show|tell|remember|delete|create|execute|chala|karo|batao|dikhao|dhundo|khol)\\b", re.I)),
    )

    def parse(self, text: str, *, language: Optional[str] = None) -> Dict[str, Any]:
        text = str(text or "").strip()
        normalized = re.sub(r"\\s+", " ", text)
        intent = "statement"
        for name, pattern in self._INTENT_PATTERNS:
            if pattern.search(normalized):
                intent = name
                break
        if normalized.endswith("?"):
            intent = "question"

        entities = self._entities(normalized)
        return {
            "text": text,
            "normalized": normalized,
            "language": language or self._language(normalized),
            "intent": intent,
            "entities": entities,
            "tokens": normalized.split() if normalized else [],
        }

    @staticmethod
    def _language(text: str) -> str:
        if re.search(r"[\\u0900-\\u097F]", text):
            return "hi"
        if re.search(r"\\b(yaar|kya|kyu|kaise|mujhe|mera|meri|hai|hain|ho|karna)\\b", text, re.I):
            return "hinglish"
        return "en"

    @staticmethod
    def _entities(text: str) -> List[Dict[str, str]]:
        found: List[Dict[str, str]] = []
        for match in re.finditer(r"\\b[A-Z][a-zA-Z0-9_-]{2,}(?:\\s+[A-Z][a-zA-Z0-9_-]{2,})*\\b", text):
            value = match.group(0).strip()
            found.append({"text": value, "type": "proper_noun"})
        return found
