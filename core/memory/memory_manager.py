from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .episodic_memory import EpisodicMemory, Episode
from .semantic_memory import SemanticMemory, Knowledge

from database.sqlite_store import SQLiteStore


class MemoryManager:
    """
    Unified persistent memory coordinator of the JARVIS organism.

    Memory layers:

        EpisodicMemory
            ↓
        SemanticMemory
            ↓
        SQLiteStore
            ↓
        database/jarvis.db

    MemoryManager provides the stable interface used by:
        Brain
        Learning
        Autonomy
        Skills

    It does NOT decide what should be learned.

    ----------------------------------------------------------------
    NOTE: This file does not contain the FAISS index or the
    NetworkX graph itself — those live in semantic_memory.py
    (SemanticMemory.search / .get_graph_relations). MemoryManager
    only calls into it. If retrieval accuracy/speed needs work,
    semantic_memory.py is the file to look at.
    ----------------------------------------------------------------
    """

    VERSION = "0.2.1"

    def __init__(
        self,
        episodic: Optional[EpisodicMemory] = None,
        semantic: Optional[SemanticMemory] = None,
        event_bus=None,
        store: Optional[SQLiteStore] = None,
    ):
        # ---------------------------------------------------------
        # Memory organs
        # ---------------------------------------------------------

        self.episodic = (
            episodic
            if episodic is not None
            else EpisodicMemory()
        )

        self.semantic = (
            semantic
            if semantic is not None
            else SemanticMemory()
        )

        # ---------------------------------------------------------
        # Event system
        # ---------------------------------------------------------

        self.events = event_bus

        # ---------------------------------------------------------
        # Persistent storage
        # ---------------------------------------------------------

        self.store = (
            store
            if store is not None
            else SQLiteStore(
                "database/jarvis.db"
            )
        )

        # ---------------------------------------------------------
        # Runtime
        # ---------------------------------------------------------

        self.created_at = time.time()
        self.updated_at = self.created_at

        # ---------------------------------------------------------
        # Restore persistent memory
        # ---------------------------------------------------------

        self._restore_from_database()

    # =============================================================
    # DATABASE RESTORE
    # =============================================================

    def _restore_from_database(self) -> None:
        """
        Load persistent episodic memory from SQLite into runtime memory.

        SemanticMemory hydrates its own SQLite/FAISS/NetworkX state
        during initialization via _hydrate_stores().
        """

        try:
            episodic_data = self.store.load_episodes()

            if episodic_data:
                self.episodic.restore({
                    "episodes": episodic_data
                })

        except Exception as exc:
            try:
                from ..runtime.log import log_event
                log_event("memory_manager", f"restore error: {exc}", level="error")
            except Exception:
                pass

    # =============================================================
    # EXPERIENCE
    # =============================================================

    def remember_experience(
        self,
        event_type: str,
        context: Optional[Dict[str, Any]] = None,
        action: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Episode:
        """
        Create an episodic memory and immediately persist it.
        """

        episode = self.episodic.remember(
            event_type=event_type,
            context=context,
            action=action,
            outcome=outcome,
            importance=importance,
            confidence=confidence,
            source=source,
            tags=tags,
        )

        # ---------------------------------------------------------
        # Persistent storage
        # ---------------------------------------------------------

        self.store.save_episode(
            episode.to_dict()
        )

        self.updated_at = time.time()

        # ---------------------------------------------------------
        # Event
        # ---------------------------------------------------------

        self._emit(
            "MEMORY_CREATED",
            {
                "memory_type": "EPISODIC",
                "episode_id": episode.episode_id,
                "event_type": episode.event_type,
            },
        )

        return episode

    # =============================================================
    # KNOWLEDGE
    # =============================================================

    def remember_knowledge(
        self,
        subject: str,
        predicate: str,
        value: Any,
        confidence: float = 0.5,
        importance: float = 0.5,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source_type: Optional[str] = None,
    ) -> Knowledge:
        """
        Create/update semantic knowledge and persist it.
        """

        knowledge = self.semantic.remember(
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=confidence,
            importance=importance,
            source=source,
            tags=tags,
            source_type=source_type,
        )

        # ---------------------------------------------------------
        # Persistent storage
        # ---------------------------------------------------------
        # SemanticMemory.remember() already persists the knowledge
        # together with its FAISS ID. Do NOT write the same record
        # through SQLiteStore, which owns only episodic persistence.

        self.updated_at = time.time()

        # ---------------------------------------------------------
        # Event
        # ---------------------------------------------------------

        self._emit(
            "KNOWLEDGE_UPDATED",
            {
                "memory_type": "SEMANTIC",
                "knowledge_id": knowledge.knowledge_id,
                "subject": knowledge.subject,
                "predicate": knowledge.predicate,
            },
        )

        return knowledge

    # =============================================================
    # RECENT EXPERIENCE
    # =============================================================

    def recent_experiences(
        self,
        limit: int = 20,
    ) -> List[Episode]:

        return self.episodic.recent(
            limit=limit
        )

    # =============================================================
    # IMPORTANT EXPERIENCE
    # =============================================================

    def important_experiences(
        self,
        threshold: float = 0.7,
        limit: int = 20,
    ) -> List[Episode]:

        return self.episodic.important(
            threshold=threshold,
            limit=limit,
        )

    # =============================================================
    # EXPERIENCE SEARCH
    # =============================================================

    def find_experiences(
        self,
        event_type: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 20,
    ) -> List[Episode]:

        if event_type:

            return self.episodic.find_by_event(
                event_type=event_type,
                limit=limit,
            )

        if tag:

            return self.episodic.find_by_tag(
                tag=tag,
                limit=limit,
            )

        return self.episodic.recent(
            limit=limit
        )

    # =============================================================
    # KNOWLEDGE LOOKUP
    # =============================================================

    def get_knowledge(
        self,
        subject: str,
        predicate: Optional[str] = None,
        value: Any = None,
    ) -> List[Knowledge]:

        return self.semantic.find(
            subject=subject,
            predicate=predicate,
            value=value,
        )

    # =============================================================
    # SUBJECT KNOWLEDGE
    # =============================================================

    def knowledge_about(
        self,
        subject: str,
        limit: int = 50,
    ) -> List[Knowledge]:

        return self.semantic.find(
            subject=subject,
        )[:limit]

    # =============================================================
    # GRAPH RELATIONS LOOKUP (fsaai integration)
    # =============================================================

    def get_graph_relations(
        self,
        subject: str,
    ) -> List[Dict[str, Any]]:
        """
        Semantic memory ke NetworkX graph se connections nikalne ke lie.
        """
        if hasattr(self.semantic, "get_graph_relations"):
            return self.semantic.get_graph_relations(subject)
        return []

    # =============================================================
    # KNOWLEDGE SEARCH
    # =============================================================

    def search_knowledge(
        self,
        query: str,
        limit: int = 20,
    ) -> List[Knowledge]:

        return self.semantic.hybrid_search(
            query=query,
            limit=limit,
        )

    def list_all_knowledge(self, limit: int = 500) -> List[Knowledge]:
        """All stored facts, newest-updated first (see
        SemanticMemory.list_all). Used by the web dashboard's memory
        browser, which needs the full set, not a search result subset."""
        return self.semantic.list_all(limit=limit)

    def forget_knowledge(self, knowledge_id: str) -> bool:
        return self.semantic.forget(knowledge_id)

    # =============================================================
    # TAG SEARCH
    # =============================================================

    def search_memory_by_tag(
        self,
        tag: str,
        limit: int = 20,
    ) -> Dict[str, List[Any]]:

        return {
            "episodes": self.episodic.find_by_tag(
                tag=tag,
                limit=limit,
            ),

            "knowledge": self.semantic.find_by_tag(
                tag=tag,
                limit=limit,
            ),
        }

    # =============================================================
    # CONTEXT
    # =============================================================

    def build_context(
        self,
        query: Optional[str] = None,
        subject: Optional[str] = None,
        recent_limit: int = 5,
        knowledge_limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Build memory context for Brain (recent episodes, FAISS/semantic
        search results, and graph relations).

        FIX (vs previous version): graph_relations used to only get
        populated when an explicit `subject` was passed. Brain's
        think_and_respond() always calls this with `query`, never
        `subject`, so graph_relations was silently empty 100% of the
        time in normal chat use — the knowledge graph edges were being
        built (per the DEV TRACE data) but never actually surfaced
        back to the LLM as context. Now, for the query path, we pull
        graph relations for every distinct subject found in the
        semantic search results too.
        """

        # SAME-RUN RECAP ONLY (2026-09-18) -- see EpisodicMemory.recent()'s
        # docstring. "recent_experiences" feeds response_brief.py's
        # recap/has_real_conversation_memory, which is what stops the
        # LLM from treating an unrelated OLD session's episodes as if
        # they were said earlier in THIS conversation.
        recent = self.episodic.recent(
            limit=recent_limit,
            same_run_only=True,
        )

        context: Dict[str, Any] = {
            "recent_experiences": [
                episode.to_dict()
                for episode in recent
            ],
            "relevant_knowledge": [],
            "graph_relations": [],
        }

        graph_relations: List[Dict[str, Any]] = []

        if subject:
            knowledge = self.semantic.find(
                subject=subject,
            )[:knowledge_limit]
            graph_relations.extend(self.get_graph_relations(subject))

        elif query:
            # FIX: was calling self.semantic.search() — plain SQL LIKE
            # text matching that never touched FAISS at all. Now uses
            # hybrid_search(), which queries the FAISS vector index
            # first (meaning-based) and only falls back to lexical
            # matching to fill remaining slots. This is what actually
            # makes retrieval "smart" instead of exact-keyword-only.
            knowledge = self.semantic.hybrid_search(
                query=query,
                limit=knowledge_limit,
            )
            # Pull graph relations for every distinct subject that
            # came back from the search, deduped, so free-text query
            # context (the normal chat path) also gets graph edges.
            seen_subjects = set()
            for item in knowledge:
                item_subject = getattr(item, "subject", None)
                if item_subject and item_subject not in seen_subjects:
                    seen_subjects.add(item_subject)
                    graph_relations.extend(
                        self.get_graph_relations(item_subject)
                    )
        else:
            knowledge = []

        context["relevant_knowledge"] = [
            item.to_dict()
            for item in knowledge
        ]
        context["graph_relations"] = graph_relations

        return context

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:

        database_stats = {}

        try:
            database_stats = self.store.statistics()

        except Exception as exc:

            database_stats = {
                "error": str(exc)
            }

        return {
            "version": self.VERSION,

            "runtime": {
                "episodic": self.episodic.count,
                "semantic": self.semantic.count,
            },

            "persistent": database_stats,

            "updated_at": self.updated_at,
        }

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(
        self,
        episode_limit: Optional[int] = None,
        knowledge_limit: Optional[int] = None,
    ) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "created_at": self.created_at,
            "updated_at": self.updated_at,

            "episodic": self.episodic.snapshot(
                limit=episode_limit,
            ),

            "semantic": self.semantic.snapshot(
                limit=knowledge_limit,
            ),

            "database": self.store.statistics(),
        }

    # =============================================================
    # RESTORE SNAPSHOT
    # =============================================================

    def restore(
        self,
        snapshot: Dict[str, Any],
    ) -> None:

        if not isinstance(snapshot, dict):
            return

        episodic_snapshot = snapshot.get(
            "episodic"
        )

        semantic_snapshot = snapshot.get(
            "semantic"
        )

        if isinstance(
            episodic_snapshot,
            dict,
        ):

            self.episodic.restore(
                episodic_snapshot
            )

        if isinstance(
            semantic_snapshot,
            dict,
        ):

            self.semantic.restore(
                semantic_snapshot
            )

        self.updated_at = time.time()

    # =============================================================
    # CLEAR
    # =============================================================

    def clear_all(self) -> None:
        """
        Clear runtime AND persistent memory.
        """

        # Clear episodic runtime memory.
        self.episodic.clear()

        # SemanticMemory owns its own SQLite + FAISS + NetworkX state.
        # It already clears the persistent knowledge table.
        self.semantic.clear()

        # Clear episodic records from the shared SQLite database.
        for episode in self.store.load_episodes():
            self.store.delete_episode(
                episode["episode_id"]
            )

        self.updated_at = time.time()

        self._emit(
            "MEMORY_CLEARED",
            {
                "timestamp": self.updated_at,
            },
        )

    def close(self) -> None:
        """
        Safely close persistent storage.
        """

        if self.store is not None:

            self.store.close()

        # Was missing: semantic memory holds its own SQLite connection
        # (now a single persistent one, see semantic_memory.py's
        # _get_db_connection() fix) and it never got a shutdown signal
        # at all, so its WAL was never checkpointed on exit either.
        if self.semantic is not None and hasattr(self.semantic, "close"):
            try:
                self.semantic.close()
            except Exception:
                pass

    # =============================================================
    # EVENT BUS
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:

        if self.events is None:
            return

        safe_emit = getattr(
            self.events,
            "safe_emit",
            None,
        )

        if callable(safe_emit):

            safe_emit(
                event_name,
                payload,
                source="memory_manager",
            )
