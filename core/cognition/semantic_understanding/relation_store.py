"""Conservative symbolic relation store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Relation:
    subject: str
    predicate: str
    object: Any
    confidence: float = 1.0
    provenance: Dict[str, Any] = field(default_factory=dict)


class RelationStore:
    VERSION = "0.1.0"

    def __init__(self) -> None:
        self._relations: List[Relation] = []

    def add(self, subject: str, predicate: str, obj: Any, *, confidence: float = 1.0, provenance: Optional[Dict[str, Any]] = None) -> Relation:
        relation = Relation(str(subject).strip(), str(predicate).strip(), obj, max(0.0, min(1.0, float(confidence))), dict(provenance or {}))
        if relation not in self._relations:
            self._relations.append(relation)
        return relation

    def query(self, subject: Optional[str] = None, predicate: Optional[str] = None, obj: Any = None) -> List[Relation]:
        return [r for r in self._relations if
                (subject is None or r.subject.lower() == str(subject).lower()) and
                (predicate is None or r.predicate.lower() == str(predicate).lower()) and
                (obj is None or r.object == obj)]

    def all(self) -> List[Relation]:
        return list(self._relations)
