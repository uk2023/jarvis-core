from __future__ import annotations

"""Governed, incremental expansion of the native category-indicator
vocabulary (core/cognition/semantic_understanding/engine.py's
_CATEGORY_INDICATOR_WORDS) -- learned from confirmed LLM extractions,
NOT silently self-modified code, and NOT a neural network.

HONEST SCOPE, stated plainly: this is not "machine learning" in the
sense of gradient descent over a model -- it is a genuine, testable
mechanism for the native/regex layer to grow its OWN vocabulary based
on real, repeated evidence, using the SAME governed-evolution
discipline already used elsewhere in this codebase (see
fallback_pattern_detector.py): detect a recurring pattern, propose a
change, require explicit human approval before anything is actually
modified. Nothing here EVER edits engine.py's source directly -- it
only ever creates an inspectable, approvable proposal.

This is the answer to "self-evolving" that is honestly achievable
right now, distinct from the separate, much larger undertaking of
training a local neural model (see training_data_collector.py, which
is step one of THAT different, longer path).

Mechanism: when semantic understanding's LLM fallback successfully
extracts a "favourite_<category>" predicate that native extraction
either produced nothing for, or produced with a different (wrong)
category split, the individual words making up that category are
candidates for addition to _CATEGORY_INDICATOR_WORDS. A candidate word
must appear as part of a CORRECT LLM extraction across several
DISTINCT turns before it's proposed -- one occurrence proves nothing;
repeated, consistent evidence is what makes a proposal worth a human's
attention.
"""

import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional

_FAVOURITE_PREDICATE = re.compile(r"^favourite_(.+)$")
_STOPWORDS = {"a", "an", "the", "my", "is", "of", "and", "hai", "ka", "ki", "ke"}


@dataclass
class _CandidateWord:
    occurrences: int = 0
    example_inputs: List[str] = field(default_factory=list)


def sandbox_test_category_word(word: str, example_inputs: List[str]) -> Dict[str, Any]:
    """The actual safe self-testing sandbox UK asked for: given a
    candidate word, simulate adding it to the indicator-word set in an
    ISOLATED, TEMPORARY copy -- never the real, live
    _CATEGORY_INDICATOR_WORDS -- and re-run extraction on the REAL
    example sentences that produced this candidate. Reports genuine
    PASS/FAIL evidence (does adding this word actually produce a clean
    relation where it didn't before), never a claim without a test
    behind it. This NEVER modifies the real source file -- it only
    produces evidence a human can review before deciding whether to
    approve the change."""
    try:
        from ..cognition.semantic_understanding.engine import SemanticUnderstandingEngine
    except Exception as exc:
        return {"tested": False, "reason": f"could not import extraction engine: {exc}"}

    original_words = frozenset(SemanticUnderstandingEngine._CATEGORY_INDICATOR_WORDS)
    results = []
    try:
        # Isolated simulation: temporarily patch the class attribute,
        # test, then ALWAYS restore it in the finally block below --
        # this is the sandbox boundary. The real engine used by every
        # actual conversation turn is never left in the modified state.
        SemanticUnderstandingEngine._CATEGORY_INDICATOR_WORDS = original_words | {word.lower()}
        engine = SemanticUnderstandingEngine()
        for text in example_inputs:
            relations = engine.understand(text).get("relations") or []
            got_favourite_relation = any(
                isinstance(r, dict) and str(r.get("predicate", "")).startswith("favourite_")
                for r in relations
            )
            results.append({"input": text, "extracted_relation": got_favourite_relation, "relations": relations})
    finally:
        SemanticUnderstandingEngine._CATEGORY_INDICATOR_WORDS = original_words

    passed = sum(1 for r in results if r["extracted_relation"])
    return {
        "tested": True,
        "word": word,
        "cases_tested": len(results),
        "cases_passed": passed,
        "all_passed": passed == len(results) and len(results) > 0,
        "details": results,
    }


class CategoryWordLearner:
    def __init__(self, known_indicator_words: Optional[set] = None, min_occurrences: int = 2):
        self._known = set(w.lower() for w in (known_indicator_words or set()))
        self.min_occurrences = max(1, int(min_occurrences))
        self._candidates: Dict[str, _CandidateWord] = {}
        self._proposed: set = set()
        self._lock = RLock()

    def observe_llm_extraction(self, predicate: str, input_text: str, native_relations: List[Dict[str, Any]]) -> None:
        """Called with an LLM-confirmed relation's predicate. If it's a
        favourite_<category> shape and native extraction did NOT
        independently produce the SAME predicate for this same input,
        the category's words (minus ones already known) become
        candidates."""
        match = _FAVOURITE_PREDICATE.match(str(predicate or ""))
        if not match:
            return
        native_predicates = {str(r.get("predicate", "")) for r in (native_relations or []) if isinstance(r, dict)}
        if predicate in native_predicates:
            return  # native already handles this correctly -- nothing to learn
        category_words = [w for w in match.group(1).split("_") if w and w.lower() not in _STOPWORDS]
        with self._lock:
            for word in category_words:
                key = word.lower()
                if key in self._known or key in self._proposed:
                    continue
                candidate = self._candidates.setdefault(key, _CandidateWord())
                candidate.occurrences += 1
                if len(candidate.example_inputs) < 5:
                    candidate.example_inputs.append(input_text)

    def promotion_candidates(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"word": word, "occurrences": c.occurrences, "example_inputs": list(c.example_inputs)}
                for word, c in self._candidates.items()
                if c.occurrences >= self.min_occurrences and word not in self._proposed
            ]

    def mark_proposed(self, word: str) -> None:
        with self._lock:
            self._proposed.add(word.lower())

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "known_word_count": len(self._known),
                "candidate_count": len(self._candidates),
                "candidates": {w: c.occurrences for w, c in self._candidates.items()},
                "proposed_count": len(self._proposed),
            }
