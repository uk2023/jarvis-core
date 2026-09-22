"""Controlled self-evolution boundary for Semantic Understanding."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

LLMFallback = Callable[[Dict[str, Any]], Mapping[str, Any]]


def _tokens(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[\w]+", str(text or "").lower()) if len(w) > 1)


@dataclass
class SemanticLearningCandidate:
    candidate_id: str
    input_text: str
    semantic: Dict[str, Any]
    source: str
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    status: str = "CANDIDATE"
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.candidate_id,
            "type": "SEMANTIC_LEARNING_CANDIDATE",
            "input_text": self.input_text,
            "semantic": dict(self.semantic),
            "source": self.source,
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
            "status": self.status,
            "created_at": self.created_at,
        }


class LearnedSemanticRegistry:
    """Promoted semantic capabilities matched from learned data, not regex rules."""

    VERSION = "0.2.0"

    def __init__(self, *, minimum_similarity: float = 0.78) -> None:
        self.minimum_similarity = max(0.0, min(1.0, float(minimum_similarity)))
        self._entries: List[Dict[str, Any]] = []

    @staticmethod
    def _similarity(left: Iterable[str], right: Iterable[str]) -> float:
        a, b = set(left), set(right)
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def promote(self, candidate: SemanticLearningCandidate | Mapping[str, Any]) -> Dict[str, Any]:
        data = candidate.as_dict() if isinstance(candidate, SemanticLearningCandidate) else dict(candidate)
        if data.get("status") != "ACCEPTED":
            raise ValueError("Only an ACCEPTED candidate may be promoted")
        semantic = data.get("semantic")
        if not isinstance(semantic, dict):
            raise ValueError("candidate semantic payload must be an object")
        entry = {
            "id": data.get("id") or f"learned:{uuid.uuid4().hex}",
            "signature": sorted(_tokens(data.get("input_text", ""))),
            "semantic": semantic,
            "confidence": float(data.get("confidence", 0.0)),
            "source": data.get("source", "unknown"),
            "created_at": data.get("created_at", time.time()),
        }
        self._entries = [e for e in self._entries if e["id"] != entry["id"]]
        self._entries.append(entry)
        return dict(entry)

    def match(self, text: str) -> Optional[Dict[str, Any]]:
        query = _tokens(text)
        best, best_score = None, 0.0
        for entry in self._entries:
            score = self._similarity(query, entry.get("signature", []))
            if score >= self.minimum_similarity and score > best_score:
                best, best_score = dict(entry), score
                best["similarity"] = score
        return best

    def entries(self) -> List[Dict[str, Any]]:
        return [dict(entry) for entry in self._entries]


class SemanticLearningBoundary:
    """Gate unknown semantic cases through fallback, evaluation and promotion."""

    VERSION = "0.2.1"

    def __init__(self, *, llm_fallback: Optional[LLMFallback] = None,
                 learning_coordinator: Optional[Any] = None,
                 registry: Optional[LearnedSemanticRegistry] = None,
                 native_confidence_threshold: float = 0.72) -> None:
        self.llm_fallback = llm_fallback
        self.learning = learning_coordinator
        self.registry = registry or LearnedSemanticRegistry()
        self.native_confidence_threshold = max(0.0, min(1.0, float(native_confidence_threshold)))
        self.candidates: Dict[str, SemanticLearningCandidate] = {}
        # M8 (2026-09-11, "JARVIS should observe where it's using the
        # LLM and try to replicate that natively over time"): a
        # SAFE, measurable first slice of that ask -- not a new
        # autonomous-replacement subsystem (too risky to build
        # without dedicated design/testing), but visibility into
        # whether native/learned resolution is ACTUALLY displacing
        # LLM fallback over the life of the process. Every resolve()
        # call below increments exactly one bucket; stats() reports
        # the ratio. Resets on restart (in-memory only, same as
        # `candidates` above) -- this is session-scoped telemetry,
        # not a persisted metric.
        self._resolution_counts: Dict[str, int] = {"native": 0, "learned_native": 0, "llm_fallback": 0}

    def stats(self) -> Dict[str, Any]:
        """M8 telemetry: how much of semantic understanding is
        currently being resolved WITHOUT an LLM call, and whether the
        learned-native path (candidates promoted via
        evolution_cycle.py, see core/organism/bootstrap.py's idle
        heartbeat) is actually taking real share away from llm_fallback
        over time -- the concrete, measurable form of "replicate what
        the LLM does, natively, with accuracy" for this subsystem."""
        counts = dict(self._resolution_counts)
        total = sum(counts.values())
        native_coverage = (counts["native"] + counts["learned_native"]) / total if total else None
        return {
            "counts": counts, "total_resolutions": total,
            "native_coverage_rate": round(native_coverage, 4) if native_coverage is not None else None,
            "learned_registry_size": len(self.registry.entries()),
            "pending_candidates": sum(1 for c in self.candidates.values() if c.status == "CANDIDATE"),
        }

    @staticmethod
    def _confidence(result: Mapping[str, Any]) -> float:
        try:
            return max(0.0, min(1.0, float(result.get("confidence", 0.0))))
        except (TypeError, ValueError):
            return 0.0

    def needs_fallback(self, result: Mapping[str, Any]) -> bool:
        """Fallback at or below the native confidence boundary -- UNLESS
        native extraction ALREADY produced at least one relation, in
        which case that's real, direct evidence the native path
        succeeded at THIS turn's actual purpose (extracting a fact),
        regardless of the separate, generic intent-classification
        confidence number.

        THE ACTUAL SYSTEMIC BUG THIS FIXES: the generic "statement"
        intent's classification confidence is hardcoded to EXACTLY
        0.72 -- the SAME value as native_confidence_threshold's
        default. With the previous `<=` comparison alone, EVERY
        statement-intent turn (an extremely common case -- most
        factual statements get this generic intent) triggered LLM
        fallback EVEN WHEN native relation-extraction had ALREADY
        succeeded, purely because 0.72 <= 0.72. If the LLM fallback
        then failed for any real reason (network issue, malformed
        JSON, budget exhausted -- all observed failure modes), the
        perfectly good native extraction was thrown away and replaced
        with a confidence=0.0 degraded stub -- a real, reproduced case:
        "mera favourite color dark black hai" natively extracts
        correctly, but the old code discarded it and stored nothing.
        This was a large share of the "kabhi knowledge store hota hai
        kabhi nahi" intermittent behavior -- not randomness, a
        deterministic conflation of two different confidence numbers
        (intent classification vs. relation extraction) into one
        threshold check.
        """
        unknowns = result.get("unknowns")
        if unknowns:
            return True
        if result.get("relations"):
            return False  # native already succeeded at the thing that actually matters
        return self._confidence(result) <= self.native_confidence_threshold

    @staticmethod
    def _is_greeting(text: str) -> bool:
        return bool(re.fullmatch(
            r"(?:hi|hello|hey|namaste|hola)(?:\s+(?:jarvis|there))?[.!?]*",
            str(text or "").strip().lower(),
        ))

    def apply_learned_capability(self, text: str) -> Optional[Dict[str, Any]]:
        match = self.registry.match(text)
        if match is None:
            return None
        semantic = dict(match.get("semantic") or {})
        provenance = semantic.get("provenance") if isinstance(semantic.get("provenance"), dict) else {}
        semantic["provenance"] = {
            **provenance,
            "source": "learned_native",
            "registry_version": self.registry.VERSION,
            "similarity": match.get("similarity", 0.0),
            "learned_from": match.get("source"),
        }
        return semantic

    def resolve(self, text: str, native_result: Mapping[str, Any], *,
                context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        # Greetings are deterministic and must never spend an LLM call merely
        # to classify a greeting. This also prevents malformed fallback JSON
        # from blocking the first user turn.
        if self._is_greeting(text):
            semantic = dict(native_result)
            semantic["intent"] = {
                "name": "greeting",
                "confidence": 0.99,
                "source": "symbolic_parser",
            }
            semantic["confidence"] = max(0.99, self._confidence(semantic))
            semantic["unknowns"] = []
            self._resolution_counts["native"] += 1
            return {"semantic": semantic, "source": "native", "fallback_used": False, "candidate": None}

        # Existing native understanding remains authoritative when confident.
        if not self.needs_fallback(native_result):
            self._resolution_counts["native"] += 1
            return {"semantic": dict(native_result), "source": "native", "fallback_used": False, "candidate": None}

        # Learned capability is preferred to asking the LLM again.
        learned = self.apply_learned_capability(text)
        if learned is not None:
            self._resolution_counts["learned_native"] += 1
            return {"semantic": learned, "source": "learned_native", "fallback_used": False, "candidate": None}

        if self.llm_fallback is None:
            self._resolution_counts["native"] += 1
            return {"semantic": dict(native_result), "source": "native", "fallback_used": False, "candidate": None}

        request = {
            "text": str(text),
            "native_semantic": dict(native_result),
            "context": dict(context or {}),
            "instruction": "Return only structured semantic meaning; do not invent external facts.",
        }
        raw = self.llm_fallback(request)
        if not isinstance(raw, Mapping):
            raise TypeError("LLM fallback must return a structured mapping")
        semantic = dict(raw.get("semantic", raw))
        if not semantic:
            raise ValueError("LLM fallback returned an empty semantic result")
        candidate = SemanticLearningCandidate(
            candidate_id=f"semantic:{uuid.uuid4().hex}",
            input_text=str(text), semantic=semantic, source="llm_fallback",
            confidence=self._confidence(semantic),
            evidence={"native": dict(native_result), "fallback_request": request},
        )
        self.candidates[candidate.candidate_id] = candidate
        self._resolution_counts["llm_fallback"] += 1
        return {"semantic": semantic, "source": "llm_fallback", "fallback_used": True,
                "candidate": candidate.as_dict()}

    def learn(self, candidate_id: str, *, auto_accept: bool = False) -> Dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if self.learning is None:
            return {"candidate": candidate.as_dict(), "learning": {"success": True, "accepted": False}}
        experience = {
            "event_type": "SEMANTIC_FALLBACK_INTERPRETATION",
            "context": {"semantic": candidate.semantic, "source": candidate.source},
            "action": {"subject": "semantic_understanding", "predicate": "interpreted"},
            "outcome": {"success": True, "score": candidate.confidence,
                        "subject": "semantic_understanding", "predicate": "interprets",
                        "value": candidate.semantic},
            "semantic_candidate": candidate.as_dict(),
        }
        return {"candidate": candidate.as_dict(),
                "learning": self.learning.learn(experience, auto_accept=auto_accept)}

    def accept_candidate(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if candidate.status != "CANDIDATE":
            raise ValueError("Only a CANDIDATE may be accepted")
        candidate.status = "ACCEPTED"
        return candidate.as_dict()

    def reject_candidate(self, candidate_id: str, reason: str = "") -> Dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if candidate.status != "CANDIDATE":
            raise ValueError("Only a CANDIDATE may be rejected")
        candidate.status = "REJECTED"
        payload = candidate.as_dict()
        payload["rejection_reason"] = str(reason)
        return payload

    def promote(self, candidate_id: str) -> Dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"Unknown semantic learning candidate: {candidate_id}")
        if candidate.status != "ACCEPTED":
            raise ValueError("Candidate must be explicitly accepted before promotion")
        return self.registry.promote(candidate)
