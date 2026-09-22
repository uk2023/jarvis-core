"""In-memory entity identity/linking store.

Persistence remains the responsibility of JARVIS memory components. This
store provides canonical identities and aliases for the current cognitive
substrate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass
class Entity:
    entity_id: str
    canonical_name: str
    entity_type: str = "unknown"
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)


class EntityStore:
    VERSION = "0.1.0"

    def __init__(self) -> None:
        self._entities: Dict[str, Entity] = {}
        self._alias_index: Dict[str, str] = {}

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"\\s+", " ", str(value).strip().lower())

    def upsert(self, name: str, entity_type: str = "unknown", aliases: Optional[Iterable[str]] = None, metadata: Optional[Dict[str, object]] = None) -> Entity:
        canonical = str(name).strip()
        key = self._key(canonical)
        entity_id = self._alias_index.get(key, f"entity:{key}")
        entity = self._entities.get(entity_id)
        if entity is None:
            entity = Entity(entity_id, canonical, entity_type, [], dict(metadata or {}))
            self._entities[entity_id] = entity
        else:
            if entity_type != "unknown":
                entity.entity_type = entity_type
            entity.metadata.update(metadata or {})
        self._alias_index[key] = entity_id
        for alias in aliases or ():
            alias_key = self._key(alias)
            if alias_key:
                self._alias_index[alias_key] = entity_id
                if alias_key != key and alias not in entity.aliases:
                    entity.aliases.append(alias)
        return entity

    def resolve(self, name: str) -> Optional[Entity]:
        entity_id = self._alias_index.get(self._key(name))
        return self._entities.get(entity_id) if entity_id else None

    def all(self) -> List[Entity]:
        return list(self._entities.values())
