from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..cognition.semantic_understanding.engine import SemanticUnderstandingEngine


class MemoryConsolidator:
    """
    Converts important/repeated episodic experiences into
    semantic knowledge.

    This is NOT the learning engine.

    Responsibilities:
        - inspect episodic memories
        - identify consolidation candidates
        - create semantic knowledge
        - avoid uncontrolled duplication
        - emit consolidation events

    REWRITTEN (2026-09-07): the original version of this class only
    understood a fully-structured episode.context/action/outcome with
    a literal "subject"/"entity"/"topic"/"name" key -- a shape that
    NO real chat turn actually produces. Every chat turn logged by
    Brain._enqueue_learning() stores context={"user_input":...,
    "perception":..., "semantic":..., "cognition":...} and
    outcome={"response":...}. None of those top-level keys are
    "subject" -- so `_extract_subject` always returned None and
    `consolidated` was always 0, silently, forever. Combined with an
    importance_threshold of 0.70 while real chat turns are logged at
    importance=0.6, the OLD `_is_candidate` filter also rejected every
    normal chat episode before extraction was even attempted. This is
    exactly why idle-time "learning" was invisible in monitor.py: the
    wiring in bootstrap.py was calling a function that could never
    succeed on real data.

    This version instead does what UK actually asked for: during idle,
    look at recent USER_CHAT episodes whose live turn did NOT already
    extract a relation (usually because the LLM per-turn call budget
    was already spent -- see config/cognition.json's budget model and
    the "wo hamirpur, UP me rahti h" case), and run the SAME
    deterministic native SemanticUnderstandingEngine.understand() on
    the raw user_input again -- now with no latency/budget pressure.
    Anything it finds is promoted into semantic memory. The raw
    episodic record itself is NEVER modified or deleted; only a
    "consolidated" tag is appended so the same episode isn't
    rescanned every idle tick. Episodic memory stays the full,
    untouched conversation history; semantic memory only grows with
    facts that were actually, verifiably extracted from it.
    """

    VERSION = "0.2.0"

    def __init__(
        self,
        memory_manager,
        event_bus=None,
        importance_threshold: float = 0.0,
        confidence_threshold: float = 0.55,
        min_repetitions: int = 2,
        semantic_engine: Optional[SemanticUnderstandingEngine] = None,
    ):
        self.memory = memory_manager
        self.events = event_bus

        # importance_threshold is kept (for status()/back-compat) but
        # is no longer used to gate USER_CHAT candidates -- see
        # _is_candidate below for why that filter never matched real
        # chat data.
        self.importance_threshold = importance_threshold
        self.confidence_threshold = confidence_threshold
        self.min_repetitions = min_repetitions

        # A dedicated engine instance, NOT the one the live chat turn
        # uses -- idle consolidation runs on the heartbeat thread while
        # chat runs on the main/request thread, and SemanticUnderstanding
        # Engine keeps small mutable cross-turn state (_last_entities,
        # _recent_turns). Sharing one instance across threads would
        # risk one turn's pronoun-resolution state leaking into the
        # other's. A second, separate instance costs nothing and stays
        # thread-safe by construction.
        self._engine = semantic_engine or SemanticUnderstandingEngine()

        self.last_run_at: Optional[float] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self.run_count = 0

    # =============================================================
    # CONSOLIDATE
    # =============================================================

    def consolidate(
        self,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Inspect recent USER_CHAT episodes and attempt to promote any
        fact the live turn missed into semantic knowledge.
        """

        started_at = time.time()

        episodes = self.memory.find_experiences(event_type="USER_CHAT", limit=limit)

        candidates = [episode for episode in episodes if self._is_candidate(episode)]

        consolidated: List[Dict[str, Any]] = []
        examined_texts: List[str] = []

        for episode in candidates:
            promoted = self._consolidate_episode(episode)
            if promoted:
                consolidated.extend(promoted)
            # Mark processed either way (even a genuine "nothing here"
            # result should not be re-scanned every idle tick forever).
            tags = getattr(episode, "tags", None)
            if isinstance(tags, list) and "consolidated" not in tags:
                tags.append("consolidated")
            examined_texts.append(self._episode_text_preview(episode))

        self.run_count += 1
        self.last_run_at = time.time()

        result = {
            "success": True,
            "examined": len(episodes),
            "candidates": len(candidates),
            "consolidated": len(consolidated),
            "items": consolidated,
            "examined_preview": examined_texts[:5],
            "duration": time.time() - started_at,
            "timestamp": self.last_run_at,
        }

        self.last_result = result

        self._emit(
            "MEMORY_CONSOLIDATION_COMPLETED",
            result,
        )

        return result

    # =============================================================
    # CANDIDATE CHECK
    # =============================================================

    def _is_candidate(
        self,
        episode,
    ) -> bool:
        """
        A USER_CHAT episode is worth re-examining during idle if:
          - it hasn't already been consolidated this run/session, AND
          - the live turn's own semantic-understanding pass did NOT
            already extract a relation from it (if it did, that fact
            is already in semantic memory -- nothing to redo), AND
          - there's actual user text to analyze.
        """

        if getattr(episode, "event_type", "") != "USER_CHAT":
            return False

        tags = getattr(episode, "tags", None) or []
        if "consolidated" in tags:
            return False

        context = getattr(episode, "context", None)
        if not isinstance(context, dict):
            return False

        semantic = context.get("semantic")
        existing_relations = semantic.get("relations") if isinstance(semantic, dict) else None
        if existing_relations:
            # Already captured live this turn -- nothing new to do,
            # but still worth tagging so it's skipped next time.
            return True

        user_text = str(context.get("user_input") or "").strip()
        return bool(user_text)

    # =============================================================
    # EPISODE -> KNOWLEDGE
    # =============================================================

    def _consolidate_episode(
        self,
        episode,
    ) -> List[Dict[str, Any]]:
        """
        Re-run native extraction on one episode's raw user_input.
        Returns a list of {episode_id, knowledge_id, subject,
        predicate, value} dicts for whatever got promoted (may be
        empty -- most re-examined episodes genuinely have no
        extractable fact, e.g. a greeting or a question).
        """

        context = getattr(episode, "context", None) or {}
        semantic = context.get("semantic") if isinstance(context, dict) else None
        if isinstance(semantic, dict) and semantic.get("relations"):
            return []  # already handled live; _is_candidate kept this only to tag it

        user_text = str(context.get("user_input") or "").strip()
        if not user_text:
            return []

        try:
            result = self._engine.understand(user_text)
        except Exception as exc:
            self._emit("IDLE_CONSOLIDATION_EXTRACTION_FAILED", {"episode_id": episode.episode_id, "error": str(exc)})
            return []

        relations = result.get("relations") or []
        promoted: List[Dict[str, Any]] = []

        for relation in relations:
            if not isinstance(relation, dict):
                continue
            subject = str(relation.get("subject") or "").strip()
            predicate = str(relation.get("predicate") or "").strip()
            value = relation.get("value")
            confidence = float(relation.get("confidence", 0.6) or 0.0)

            if not subject or not predicate or value in (None, ""):
                continue
            if confidence < self.confidence_threshold:
                continue

            knowledge = self.memory.remember_knowledge(
                subject=subject,
                predicate=predicate,
                value=value,
                confidence=confidence,
                importance=0.6,
                source="idle_consolidation",
                tags=["idle_consolidated"],
            )

            item = {
                "episode_id": episode.episode_id,
                "knowledge_id": knowledge.knowledge_id,
                "subject": subject,
                "predicate": predicate,
                "value": value,
            }
            promoted.append(item)

            self._emit("MEMORY_CONSOLIDATED", item)

        return promoted

    @staticmethod
    def _episode_text_preview(episode, limit: int = 60) -> str:
        context = getattr(episode, "context", None) or {}
        text = str(context.get("user_input") or "") if isinstance(context, dict) else ""
        text = text.strip()
        return (text[:limit] + "…") if len(text) > limit else text

    # =============================================================
    # CONSOLIDATE SINGLE EPISODE
    # =============================================================

    def consolidate_episode(
        self,
        episode_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Manually consolidate one known episode (used by CLI/tools).
        """

        episodes = self.memory.find_experiences(limit=1000)

        for episode in episodes:

            if episode.episode_id == episode_id:

                if not self._is_candidate(episode):
                    return []

                return self._consolidate_episode(episode)

        return []

    # =============================================================
    # STATUS
    # =============================================================

    def status(self) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
            "last_result": self.last_result,
            "importance_threshold": self.importance_threshold,
            "confidence_threshold": self.confidence_threshold,
            "min_repetitions": self.min_repetitions,
        }

    # monitor.py / runtime_monitor.py's generic RuntimeMonitor._stats()
    # helper looks for a `.statistics()` method on every organ it's
    # handed -- alias it to status() rather than duplicating the dict,
    # so this organ shows up in the live snapshot the same way every
    # other organ does.
    statistics = status

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
                source="memory_consolidator",
            )
