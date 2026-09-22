from __future__ import annotations

"""LLM Dependency Metrics (blueprint section 43).

The blueprint's own framing: "JARVIS is becoming smarter" is not an
engineering proof. This module is what makes the claim measurable --
counting what actually happened, turn by turn, rather than describing
an aspiration.

Honest scope: this implements the metrics that are directly countable
from data Brain already has at its one canonical learning chokepoint
(_record_action_response) -- total interactions, per-route outcome
counts, llm_fallback_rate, and contradiction_rate (now measurable
thanks to SemanticMemory's history tracking). It does NOT implement
semantic_resolution_accuracy or retrieval_success as named in the
blueprint's full list -- those need a ground-truth judgment of
"was the answer actually correct", which nothing in this pipeline
currently produces automatically; recording them here would mean
inventing numbers, not measuring anything real.
"""

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Optional


@dataclass
class DependencyMetrics:
    total_interactions: int = 0
    native_success: int = 0
    native_failure: int = 0
    hybrid_success: int = 0
    hybrid_failure: int = 0
    goal_count: int = 0
    clarify_count: int = 0
    llm_fallback_count: int = 0
    llm_success: int = 0
    llm_failure: int = 0
    native_direct_recall_count: int = 0
    identity_answer_count: int = 0
    graph_multi_hop_count: int = 0
    slm_assisted_recall_count: int = 0
    # Aggregate LLM cost-awareness (the direct answer to "JARVIS ko apne
    # LLM-call kharche ki value khud pata honi chahiye"): how often a
    # reinforced retry (perception's or semantic understanding's, see
    # core/contracts/extraction.py / blueprint_brain.py) actually got
    # spent, and how often that extra call paid off vs was wasted.
    llm_retry_used_count: int = 0
    llm_retry_paid_off_count: int = 0
    started_at: float = field(default_factory=time.time)
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def record_retry_cost(self, retry_used: bool, retry_paid_off: bool) -> None:
        with self._lock:
            if retry_used:
                self.llm_retry_used_count += 1
                if retry_paid_off:
                    self.llm_retry_paid_off_count += 1

    def retry_value_rate(self) -> Optional[float]:
        """Share of spent retries that actually paid off. None (not
        0.0) when no retry has ever been spent yet -- an honest
        "not enough data" signal rather than a fake zero."""
        if not self.llm_retry_used_count:
            return None
        return round(self.llm_retry_paid_off_count / self.llm_retry_used_count, 4)

    def record_turn(self, mode: str, status: str, answered_by: Optional[str] = None) -> None:
        with self._lock:
            self.total_interactions += 1
            success = status in ("completed", "planned")
            if answered_by == "native_direct_recall":
                self.native_direct_recall_count += 1
                return
            if answered_by == "identity":
                self.identity_answer_count += 1
                return
            if answered_by == "graph_multi_hop":
                self.graph_multi_hop_count += 1
                return
            if answered_by == "slm_assisted_recall":
                self.slm_assisted_recall_count += 1
                return
            if mode == "native":
                self.native_success += 1 if success else 0
                self.native_failure += 0 if success else 1
            elif mode == "hybrid":
                self.hybrid_success += 1 if success else 0
                self.hybrid_failure += 0 if success else 1
            elif mode == "goal":
                self.goal_count += 1
            elif mode == "clarify":
                self.clarify_count += 1
            elif mode == "llm":
                self.llm_fallback_count += 1
                self.llm_success += 1 if success else 0
                self.llm_failure += 0 if success else 1

    def llm_fallback_rate(self) -> float:
        # Direct-recall/identity answers are turns that needed ZERO
        # LLM calls end-to-end -- they belong in the denominator (they
        # are real interactions) but obviously not in the numerator.
        denom = self.total_interactions
        return round(self.llm_fallback_count / denom, 4) if denom else 0.0

    def native_resolution_rate(self) -> float:
        """Share of interactions resolved WITHOUT any LLM call at all --
        native route, direct recall, or identity fast path combined.
        This is the single number that should trend upward if the
        cascade/fast-path work is actually reducing LLM dependency."""
        denom = self.total_interactions
        if not denom:
            return 0.0
        no_llm = (
            self.native_success + self.native_failure
            + self.native_direct_recall_count + self.identity_answer_count
            + self.graph_multi_hop_count + self.slm_assisted_recall_count
        )
        return round(no_llm / denom, 4)

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_interactions": self.total_interactions,
                "native_success": self.native_success, "native_failure": self.native_failure,
                "hybrid_success": self.hybrid_success, "hybrid_failure": self.hybrid_failure,
                "goal_count": self.goal_count, "clarify_count": self.clarify_count,
                "llm_fallback_count": self.llm_fallback_count,
                "llm_success": self.llm_success, "llm_failure": self.llm_failure,
                "native_direct_recall_count": self.native_direct_recall_count,
                "identity_answer_count": self.identity_answer_count,
                "graph_multi_hop_count": self.graph_multi_hop_count,
                "slm_assisted_recall_count": self.slm_assisted_recall_count,
                "llm_fallback_rate": self.llm_fallback_rate(),
                "native_resolution_rate": self.native_resolution_rate(),
                "llm_retry_used_count": self.llm_retry_used_count,
                "llm_retry_paid_off_count": self.llm_retry_paid_off_count,
                "retry_value_rate": self.retry_value_rate(),
                "uptime_seconds": round(time.time() - self.started_at, 1),
            }


def contradiction_rate(memory: Any) -> Optional[float]:
    """Fraction of stored facts that have at least one contradiction in
    their history (see SemanticMemory.remember()'s history tracking).
    Returns None (not 0.0) when it genuinely cannot be computed, so a
    caller can distinguish "measured zero contradictions" from
    "couldn't measure this at all" -- an honest missing-data signal.
    """
    semantic = getattr(memory, "semantic", None)
    if semantic is None:
        return None
    try:
        all_facts = semantic.list_all(limit=100000) if hasattr(semantic, "list_all") else None
    except Exception:
        all_facts = None
    if not all_facts:
        return None
    total = len(all_facts)
    if total == 0:
        return None
    contradicted = sum(1 for item in all_facts if getattr(item, "history", None))
    return round(contradicted / total, 4)
