"""Bridge semantic understanding into Cognition without bypassing Brain/Router."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .context_model import ContextModel
from .entity_store import EntityStore
from .engine import SemanticUnderstandingEngine
from .learning_boundary import SemanticLearningBoundary
from .relation_store import RelationStore
from .semantic_retriever import SemanticRetriever


class SemanticUnderstanding:
    """Neuro-symbolic understanding facade at the Cognition boundary."""

    VERSION = "0.4.0"

    def __init__(self, *, parser: Optional[SemanticUnderstandingEngine] = None,
                 entity_store: Optional[EntityStore] = None,
                 relation_store: Optional[RelationStore] = None,
                 context_model: Optional[ContextModel] = None,
                 retriever: Optional[SemanticRetriever] = None,
                 semantic_memory: Optional[Any] = None,
                 learning_boundary: Optional[SemanticLearningBoundary] = None) -> None:
        self.parser = parser or SemanticUnderstandingEngine()
        self.entity_store = entity_store or EntityStore()
        self.relation_store = relation_store or RelationStore()
        self.context_model = context_model or ContextModel()
        self.retriever = retriever or SemanticRetriever(semantic_memory=semantic_memory)
        self.learning_boundary = learning_boundary or SemanticLearningBoundary()
        # Self-authored extraction patterns (2026-09-12) -- see
        # core/learning/pattern_synthesis.py. Kept as a plain reference,
        # not copied, so a pattern UK confirms mid-session is picked up
        # by the NEXT call without needing to reconstruct anything.
        self.semantic_memory = semantic_memory

    def understand(self, text: str, *, language: Optional[str] = None,
                   context: Optional[Dict[str, Any]] = None,
                   retrieve: bool = True, retrieval_limit: int = 8) -> Dict[str, Any]:
        native_semantic = self.parser.understand(text, context=context)
        # SELF-AUTHORED PATTERNS (2026-09-12, UK's "regex = hardcoding"
        # objection): only tried when native symbolic parsing found
        # NOTHING -- if the hand-written extractors already got a
        # relation, there's nothing for a learned pattern to add, and
        # trying anyway would just risk a redundant/conflicting fact.
        if not native_semantic.get("relations"):
            try:
                from ..learning.pattern_synthesis import apply_confirmed_patterns
                learned_relations = apply_confirmed_patterns(text, self.semantic_memory)
                if learned_relations:
                    native_semantic = dict(native_semantic)
                    native_semantic["relations"] = learned_relations
            except Exception:
                pass
        # Confidence-based auto-evolution (2026-09-12) -- runs
        # regardless of whether native/learned extraction found
        # anything above, since a PENDING pattern accumulating evidence
        # is independent of what actually answered this turn.
        try:
            from ..learning.pattern_synthesis import shadow_test_pending_patterns
            auto_promotions = shadow_test_pending_patterns(text, self.semantic_memory)
            if auto_promotions:
                self._last_auto_promotions = auto_promotions
        except Exception:
            pass
        resolution = self.learning_boundary.resolve(text, native_semantic, context=context)
        learning_intake = None
        candidate = resolution.get("candidate")
        if candidate is not None and self.learning_boundary.learning is not None:
            learning_intake = self.learning_boundary.learn(candidate["id"], auto_accept=False)

        semantic = dict(resolution.get("semantic") or native_semantic)
        provenance = semantic.get("provenance") if isinstance(semantic.get("provenance"), dict) else {}
        semantic["provenance"] = {**provenance, "semantic_source": resolution.get("source", "native")}

        entities = []
        for entity in semantic.get("entities", []):
            if not isinstance(entity, dict) or not entity.get("text"):
                continue
            stored = self.entity_store.upsert(entity["text"], entity.get("type", "unknown"))
            enriched = dict(entity)
            enriched["entity_id"] = stored.entity_id
            entities.append(enriched)
        semantic["entities"] = entities
        context_state = self.context_model.update(semantic)
        evidence = (
            self.retriever.retrieve(semantic.get("normalized", text), limit=retrieval_limit)
            if retrieve else {"exact": [], "vector": [], "graph": []}
        )
        return {
            "version": self.VERSION,
            "semantic": semantic,
            "normalized": semantic.get("normalized", text),
            "entities": entities,
            "relations": list(semantic.get("relations") or []),
            "context": context_state,
            "evidence": evidence,
            "learning": {
                "source": resolution.get("source", "native"),
                "fallback_used": bool(resolution.get("fallback_used", False)),
                "candidate": resolution.get("candidate"),
                "intake": learning_intake,
            },
        }

    def learn_semantic_candidate(self, candidate_id: str, *, auto_accept: bool = False) -> Dict[str, Any]:
        return self.learning_boundary.learn(candidate_id, auto_accept=auto_accept)

    def accept_semantic_candidate(self, candidate_id: str) -> Dict[str, Any]:
        return self.learning_boundary.accept_candidate(candidate_id)

    def reject_semantic_candidate(self, candidate_id: str, reason: str = "") -> Dict[str, Any]:
        return self.learning_boundary.reject_candidate(candidate_id, reason)

    def promote_semantic_candidate(self, candidate_id: str) -> Dict[str, Any]:
        return self.learning_boundary.promote(candidate_id)

    def add_relation(self, subject: str, predicate: str, obj: Any, *,
                     confidence: float = 1.0,
                     provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Keep a transient candidate; trusted persistence belongs to learning."""
        relation = self.relation_store.add(subject, predicate, obj,
                                            confidence=confidence, provenance=provenance)
        return {"subject": relation.subject, "predicate": relation.predicate,
                "object": relation.object, "confidence": relation.confidence,
                "provenance": relation.provenance}
