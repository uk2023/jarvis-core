"""CHAT HISTORY AUDIT FOR SELF-TRAINING (2026-09-19).

UK's explicit ask: "JARVIS ko audit aur reverify karo purani chats,
consolidate kare ki usne kya galat response diya, user ne kya
correction diya tha, uska behavioral goal mein apnaaye."

IMPORTANT: this does NOT duplicate the self-rule pipeline that already
exists (brain.py's reasoning_trace.adopt_as_learning ->
semantic.remember(subject="jarvis_self_rule", ...) -> pending_
confirmation -> shadow-evidence auto-adopt -> confirm_self_rule()).
That pipeline is LIVE, in-the-moment: it proposes a rule from THIS
turn's own self-evaluation, then re-proposes and auto-adopts only after
several genuinely SEPARATE live reasoning cycles independently reach
the same conclusion.

This module is the RETROACTIVE half UK asked for: a backward sweep over
PAST conversation history (potentially spanning many old sessions) that
finds corrections the live pipeline never got a chance to see (because
they happened in a turn that never went through self-evaluation, or in
a session before this pipeline existed), and CONSOLIDATES repeated
instances of the same correction into one candidate rule. It is a pure,
standalone module -- no semantic-memory coupling here -- so it's fully
testable without a running Brain; a thin wrapper on Brain (see
brain.py's audit_and_learn_from_history()) feeds it real history and
writes results into the EXISTING jarvis_self_rule schema, always as
pending_confirmation, NEVER auto-adopted (audit-derived rules did not
go through the live pipeline's independent-reproposal evidence, so they
don't earn that pipeline's auto-adopt trust level).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .conversation_continuity import ConversationContinuityLayer


@dataclass
class CorrectionInstance:
    """One correction found in one historical turn."""
    was_wrong: str
    should_be: str
    evidence: str  # the user's actual message
    turn_index: int
    timestamp: Optional[float] = None


@dataclass
class ConsolidatedRule:
    """Several similar corrections, consolidated into one candidate
    behavioral rule -- the thing that actually gets proposed for
    confirmation, not the raw correction text itself."""
    rule_text: str
    occurrences: int
    first_seen: Optional[float]
    last_seen: Optional[float]
    example_evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_text": self.rule_text,
            "occurrences": self.occurrences,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "example_evidence": self.example_evidence,
        }


def find_corrections_in_history(turns: List[Dict[str, Any]]) -> List[CorrectionInstance]:
    """Scan real historical turns for corrections, using the SAME
    hardened detect_correction() logic ConversationContinuityLayer uses
    live -- one detector, one set of accuracy fixes, applied
    consistently whether reasoning about the current turn or auditing
    history, not two independently-maintained pattern sets that could
    drift apart.

    `turns` is a list of {"user_said": str, "jarvis_replied": str,
    "timestamp": float} dicts -- the exact shape Brain.
    get_conversation_history() already returns, so a real Brain's
    history needs no reshaping to call this.
    """
    detector = ConversationContinuityLayer(session_id="audit", run_id="audit")
    found: List[CorrectionInstance] = []
    for i, turn in enumerate(turns):
        user_said = turn.get("user_said") or ""
        if not user_said:
            continue
        correction = detector.detect_correction(user_said)
        if correction:
            was_wrong, should_be = correction
            found.append(CorrectionInstance(
                was_wrong=was_wrong,
                should_be=should_be,
                evidence=user_said,
                turn_index=i,
                timestamp=turn.get("timestamp"),
            ))
    return found


def _significant_tokens(text: str) -> set:
    """Words worth matching on for grouping -- longer than 3 chars,
    common stopwords removed. Deliberately permissive (any shared
    significant token links two corrections) rather than requiring the
    whole phrase to match, since real correction phrasing genuinely
    varies turn to turn ("Kali Linux use karo" vs "hum Kali Linux pe
    hai" are the same correction, worded differently) -- see
    consolidate_corrections()'s docstring for why exact-string grouping
    was tried first and found to under-group real data.
    """
    stop = {"the", "a", "an", "is", "are", "to", "hai", "ka", "ki", "ke",
            "ko", "mein", "me", "use", "karo", "hum", "pe", "not", "instead"}
    return {w for w in text.lower().split() if len(w) > 3 and w not in stop}


def consolidate_corrections(
    corrections: List[CorrectionInstance],
    min_occurrences: int = 2,
) -> List[ConsolidatedRule]:
    """Group corrections that say essentially the same thing, and turn
    each group with enough repetition into ONE candidate rule.

    GROUPING (2026-09-19, hardened after this function's own test
    exposed the gap): an earlier version grouped by exact match on the
    normalized `should_be` string, which under-grouped real data --
    "Kali Linux use karo" and "hum Kali Linux pe hai" are the SAME
    correction (both saying "use Kali Linux") but share no identical
    normalized string, so they landed in separate groups of one and
    neither reached min_occurrences. Fixed with connected-component
    clustering on SHARED SIGNIFICANT TOKENS instead: any two
    corrections whose should_be text shares at least one meaningful
    word (see _significant_tokens) are linked into the same group,
    transitively. Still not a semantic similarity engine (no
    embeddings, no LLM call) -- two corrections with the same intent
    but zero shared vocabulary ("use Kali" vs "avoid Termux entirely")
    would still land in separate groups -- but meaningfully better than
    exact-string matching for the common case of the same correction
    phrased slightly differently across sessions.

    A correction seen only ONCE across all of history is NOT proposed
    as a rule here -- min_occurrences defaults to 2 deliberately: one
    correction is an isolated event, a REPEATED correction across
    separate turns/sessions is the actual behavioral pattern UK
    described wanting JARVIS to learn from.
    """
    if not corrections:
        return []

    # Union-find over correction indices, linked by shared tokens.
    parent = list(range(len(corrections)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    token_sets = [_significant_tokens(c.should_be) for c in corrections]
    for i in range(len(corrections)):
        for j in range(i + 1, len(corrections)):
            if token_sets[i] & token_sets[j]:
                union(i, j)

    groups: Dict[int, List[CorrectionInstance]] = {}
    for idx, c in enumerate(corrections):
        groups.setdefault(find(idx), []).append(c)

    rules: List[ConsolidatedRule] = []
    for instances in groups.values():
        if len(instances) < min_occurrences:
            continue
        instances_sorted = sorted(instances, key=lambda c: c.turn_index)
        # rule_text uses the MOST RECENT phrasing of "should_be" -- if
        # the user has refined how they phrase the correction over
        # time, the latest phrasing is the one that should govern
        # going forward, not the first (possibly rougher) one.
        latest = instances_sorted[-1]
        rules.append(ConsolidatedRule(
            rule_text=f"Not \"{instances_sorted[0].was_wrong}\" -- always \"{latest.should_be}\"",
            occurrences=len(instances),
            first_seen=instances_sorted[0].timestamp,
            last_seen=latest.timestamp,
            example_evidence=[i.evidence for i in instances_sorted[:3]],
        ))

    # Most-repeated first -- the strongest, most-evidenced pattern is
    # the one worth UK's attention first when reviewing pending rules.
    rules.sort(key=lambda r: r.occurrences, reverse=True)
    return rules


def audit_history_for_learnable_corrections(
    turns: List[Dict[str, Any]],
    min_occurrences: int = 2,
) -> List[ConsolidatedRule]:
    """The single entry point: raw history in, consolidated candidate
    rules out. Pure function -- no I/O, no semantic memory, fully
    testable with synthetic turn data."""
    corrections = find_corrections_in_history(turns)
    return consolidate_corrections(corrections, min_occurrences=min_occurrences)
