"""Tests for core/cognition/correction_audit.py.

UK's explicit ask: JARVIS should audit old chat history, find
corrections it was given (even when differently worded across
sessions), and consolidate REPEATED ones into candidate learned rules
-- distinct from the existing live self-rule pipeline in brain.py,
which proposes rules from THIS turn's own self-evaluation, not from a
retroactive historical sweep.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.correction_audit import (
    find_corrections_in_history,
    consolidate_corrections,
    audit_history_for_learnable_corrections,
    CorrectionInstance,
)


def test_finds_corrections_in_realistic_history():
    turns = [
        {"user_said": "PDF reader banao", "jarvis_replied": "ok", "timestamp": 1000},
        {"user_said": "kya haal hai", "jarvis_replied": "theek hoon", "timestamp": 2000},
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 3000},
    ]
    found = find_corrections_in_history(turns)
    assert len(found) == 1
    assert found[0].was_wrong == "Termux nahi"
    assert "Kali Linux" in found[0].should_be
    assert found[0].turn_index == 2


def test_repeated_correction_consolidates_even_with_different_phrasing():
    """The core value proposition: the SAME correction, said differently
    across separate sessions, must still be recognized as one repeated
    pattern -- not two unrelated one-off corrections."""
    turns = [
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 1000},
        {"user_said": "kya haal hai", "jarvis_replied": "theek", "timestamp": 2000},
        {"user_said": "nahi Termux mat bolo, hum Kali Linux pe hai instead", "jarvis_replied": "ok", "timestamp": 3000},
        {"user_said": "not this approach, use SymPy instead", "jarvis_replied": "ok", "timestamp": 4000},
    ]
    rules = audit_history_for_learnable_corrections(turns, min_occurrences=2)
    assert len(rules) == 1, f"expected exactly 1 consolidated rule, got {len(rules)}: {[r.rule_text for r in rules]}"
    assert rules[0].occurrences == 2
    assert "Kali Linux" in rules[0].rule_text


def test_one_off_correction_not_proposed_as_a_rule():
    """A correction seen exactly once must NOT become a candidate rule
    -- that's an isolated event, not a learnable pattern."""
    turns = [
        {"user_said": "not this approach, use SymPy instead", "jarvis_replied": "ok", "timestamp": 1000},
    ]
    rules = audit_history_for_learnable_corrections(turns, min_occurrences=2)
    assert rules == []


def test_no_corrections_in_ordinary_history_returns_empty():
    turns = [
        {"user_said": "hello", "jarvis_replied": "hi", "timestamp": 1000},
        {"user_said": "how are you", "jarvis_replied": "good", "timestamp": 2000},
        {"user_said": "build a calculator", "jarvis_replied": "ok", "timestamp": 3000},
    ]
    rules = audit_history_for_learnable_corrections(turns)
    assert rules == []


def test_unrelated_corrections_stay_in_separate_groups():
    """Two genuinely DIFFERENT corrections (different topics entirely)
    must not get merged into one group just because both exist."""
    turns = [
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 1000},
        {"user_said": "nahi Termux mat bolo, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 2000},
        {"user_said": "not JSON, use YAML format instead", "jarvis_replied": "ok", "timestamp": 3000},
        {"user_said": "not JSON output, prefer YAML format instead", "jarvis_replied": "ok", "timestamp": 4000},
    ]
    rules = audit_history_for_learnable_corrections(turns, min_occurrences=2)
    assert len(rules) == 2, f"expected 2 separate rules, got {len(rules)}: {[r.rule_text for r in rules]}"
    rule_texts = " ".join(r.rule_text for r in rules)
    assert "Kali" in rule_texts and "YAML" in rule_texts


def test_consolidated_rule_uses_most_recent_phrasing():
    """If the user refined how they phrase a correction over time, the
    LATEST phrasing should govern the rule text, not the first/roughest."""
    corrections = [
        CorrectionInstance(was_wrong="X", should_be="use Kali roughly", evidence="e1", turn_index=0, timestamp=1000),
        CorrectionInstance(was_wrong="X", should_be="always use Kali Linux specifically", evidence="e2", turn_index=1, timestamp=2000),
    ]
    rules = consolidate_corrections(corrections, min_occurrences=2)
    assert len(rules) == 1
    assert "specifically" in rules[0].rule_text  # the later, more precise phrasing


if __name__ == "__main__":
    test_finds_corrections_in_realistic_history()
    test_repeated_correction_consolidates_even_with_different_phrasing()
    test_one_off_correction_not_proposed_as_a_rule()
    test_no_corrections_in_ordinary_history_returns_empty()
    test_unrelated_corrections_stay_in_separate_groups()
    test_consolidated_rule_uses_most_recent_phrasing()
    print("✓ ALL CORRECTION AUDIT TESTS PASSED")
