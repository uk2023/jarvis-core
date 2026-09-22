"""M3.3 full semantic evolution cycle orchestration."""

from __future__ import annotations

from typing import Any, Dict, List

from .knowledge_promotion import SemanticKnowledgePromotion
from .learning_boundary import SemanticLearningBoundary


class SemanticEvolutionCycle:
    """Coordinate fallback -> learning -> acceptance -> promotion -> reuse.

    The cycle deliberately delegates trusted knowledge creation to the existing
    learning stack and delegates future matching to LearnedSemanticRegistry.
    """

    VERSION = "0.1.0"

    def __init__(self, boundary: SemanticLearningBoundary, learning_coordinator: Any):
        self.boundary = boundary
        self.promotion = SemanticKnowledgePromotion(boundary, learning_coordinator)

    def accept_and_promote(self, candidate_id: str) -> Dict[str, Any]:
        return self.promotion.accept_and_promote(candidate_id)

    def reject(self, candidate_id: str, reason: str = "") -> Dict[str, Any]:
        return self.promotion.reject(candidate_id, reason=reason)

    def reuse(self, text: str) -> Dict[str, Any] | None:
        """Return a learned-native semantic interpretation, if one exists."""
        return self.boundary.apply_learned_capability(text)

    def cycle(self, text: str, native_result: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a new input through native/learned/fallback resolution."""
        return self.boundary.resolve(text, native_result)

    def promote_ready_candidates(self, min_confidence: float = 0.75, limit: int = 10) -> Dict[str, Any]:
        """THE ACTUAL WIRING FIX (2026-09-11 roadmap Phase 5): this whole
        module -- fully written, apparently correct -- was never
        imported anywhere in the codebase, so every LLM-fallback
        semantic interpretation sat in boundary.candidates forever as
        a CANDIDATE, and JARVIS re-asked the LLM for the same kind of
        input pattern indefinitely instead of ever promoting a learned
        capability into LearnedSemanticRegistry (see
        learning_boundary.py's apply_learned_capability(), which
        already existed and is checked BEFORE the LLM fallback on
        every turn -- it just never had anything to match against).

        Called from the idle cycle (see core/organism/bootstrap.py's
        heartbeat handler, alongside the other idle-consolidation
        tasks). Deliberately promotes on confidence alone, not
        repeated evidence: unlike a self-authored BEHAVIORAL rule
        (which generalizes across situations and needs repetition to
        trust -- see Brain's adopt_as_learning), a semantic candidate
        is a single utterance's INTERPRETATION; the registry's own
        promote()->match() step (token-overlap similarity >= 0.78) is
        what re-applies it to FUTURE similar utterances, so requiring
        repeats here first would just delay a capability that's
        already safe to reuse.

        CAVEAT (documented honestly, not silently assumed away):
        boundary.candidates is an in-memory dict, not persisted to
        disk -- a candidate not yet promoted is lost on process
        restart. This call only ever sees whatever accumulated since
        the last restart; it does not recover older, already-lost
        candidates.
        """
        promoted: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        skipped_low_confidence = 0
        # Snapshot the ids first -- accept_and_promote() mutates
        # candidate.status, so iterating self.boundary.candidates
        # directly while promoting would be modifying-while-iterating.
        ready_ids = [
            cid for cid, candidate in self.boundary.candidates.items()
            if candidate.status == "CANDIDATE"
        ]
        for candidate_id in ready_ids:
            if len(promoted) + len(failed) >= max(1, limit):
                break
            candidate = self.boundary.candidates.get(candidate_id)
            if candidate is None:
                continue
            if candidate.confidence < min_confidence:
                skipped_low_confidence += 1
                continue
            try:
                result = self.accept_and_promote(candidate_id)
                promoted.append({
                    "candidate_id": candidate_id,
                    "input_text": candidate.input_text,
                    "confidence": candidate.confidence,
                })
            except Exception as exc:
                failed.append({"candidate_id": candidate_id, "error": str(exc)})
        return {
            "promoted": promoted, "failed": failed,
            "skipped_low_confidence": skipped_low_confidence,
            "remaining_candidates": sum(1 for c in self.boundary.candidates.values() if c.status == "CANDIDATE"),
        }
