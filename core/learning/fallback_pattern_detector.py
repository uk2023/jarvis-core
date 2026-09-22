from __future__ import annotations

"""Evolution of LLM fallbacks (blueprint section 48) -- the feedback
loop that gives "reduced LLM dependency" an actual mechanism instead
of being an aspiration.

    Pattern P
        -> LLM used N times
        -> all N successful
        -> same coverage gap detected each time
        -> candidate native resolver proposed
        -> [validation / approval -- already governed by the existing
            ControlledEvolutionEngine, untouched by this module]
        -> route P becomes native

Honest scope: this module handles detection and PROPOSAL only. It
never writes code, never registers a resolver, never auto-applies
anything -- Rule 19 ("Evolution Proposal != Automatic Code
Execution") already governs that, via the existing
ControlledEvolutionEngine.propose()/approve()/apply() pipeline, which
this module calls into rather than duplicating.

The "pattern" tracked here is deliberately narrow and concrete: a
recall-miss coverage gap (see response_brief.detect_recall_miss) --
"the user asked a 'what is my X' question, the phrasing was exactly
what native recall handles, but X's predicate word wasn't in the
known map, so the LLM had to answer it". This is a real, measurable,
narrow slice of "recurring LLM fallback pattern" -- not a claim to
detect every possible pattern class the blueprint's prose describes.
"""

import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional


@dataclass
class PatternStats:
    occurrences: int = 0
    successes: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    example_inputs: List[str] = field(default_factory=list)

    def success_rate(self) -> float:
        return round(self.successes / self.occurrences, 4) if self.occurrences else 0.0


class FallbackPatternDetector:
    """Tracks recall-miss coverage gaps across turns and reports which
    ones have crossed the reliability threshold for a governed
    evolution proposal."""

    def __init__(self, min_occurrences: int = 3, min_success_rate: float = 0.8):
        self.min_occurrences = max(1, int(min_occurrences))
        self.min_success_rate = max(0.0, min(1.0, float(min_success_rate)))
        self._patterns: Dict[str, PatternStats] = {}
        self._proposed: set = set()  # pattern keys already proposed -- never re-propose the same gap
        self._lock = RLock()

    def record(self, pattern_key: str, success: bool, user_input: str) -> None:
        if not pattern_key:
            return
        with self._lock:
            stats = self._patterns.setdefault(pattern_key, PatternStats())
            stats.occurrences += 1
            if success:
                stats.successes += 1
            stats.last_seen = time.time()
            if len(stats.example_inputs) < 5:
                stats.example_inputs.append(user_input)

    def promotion_candidates(self) -> List[Dict[str, Any]]:
        """Patterns that have crossed the threshold AND have not already
        been proposed. Calling this does not mark them as proposed --
        the caller does that explicitly via mark_proposed() once a real
        proposal has actually been created, so a failed propose() call
        can be retried on the next check."""
        with self._lock:
            candidates = []
            for key, stats in self._patterns.items():
                if key in self._proposed:
                    continue
                if stats.occurrences >= self.min_occurrences and stats.success_rate() >= self.min_success_rate:
                    candidates.append({
                        "pattern_key": key,
                        "occurrences": stats.occurrences,
                        "successes": stats.successes,
                        "success_rate": stats.success_rate(),
                        "example_inputs": list(stats.example_inputs),
                    })
            return candidates

    def mark_proposed(self, pattern_key: str) -> None:
        with self._lock:
            self._proposed.add(pattern_key)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                key: {"occurrences": s.occurrences, "successes": s.successes, "success_rate": s.success_rate()}
                for key, s in self._patterns.items()
            }
