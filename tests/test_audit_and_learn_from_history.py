"""Tests for Brain.audit_and_learn_from_history() (2026-09-19).

Uses a minimal fake Brain (bypassing __init__ entirely -- Brain has
heavy runtime dependencies) with only the two things this method
actually touches: get_conversation_history() and memory.semantic.
Verifies the real method logic: repeated corrections get proposed as
pending_confirmation (never auto-adopted), and a previously-rejected
rule is never re-proposed.
"""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration.brain import Brain


class _FakeSemantic:
    def __init__(self):
        self.stored = {}
        self._id_counter = 0

    def find(self, subject=None, predicate=None):
        return [v for k, v in self.stored.items() if k[0] == subject and (predicate is None or k[1] == predicate)]

    def remember(self, subject, predicate, value, confidence, importance, source, tags, namespace, source_type):
        self._id_counter += 1

        class Row:
            pass

        row = Row()
        row.subject = subject
        row.predicate = predicate
        row.value = value
        row.tags = tags
        row.confidence = confidence
        row.source = source
        row.knowledge_id = f"kid_{self._id_counter}"
        self.stored[(subject, predicate)] = row
        return row


class _FakeMemory:
    def __init__(self):
        self.semantic = _FakeSemantic()


def _make_brain(turns, seed_rejected=None):
    brain = Brain.__new__(Brain)
    brain.memory = _FakeMemory()
    if seed_rejected:
        for rule_text in seed_rejected:
            rule_key = hashlib.sha1(rule_text.strip().lower().encode("utf-8")).hexdigest()[:10]
            predicate = f"learned_behavior_audit_{rule_key}"

            class Row:
                pass

            row = Row()
            row.subject = "jarvis_self_rule"
            row.predicate = predicate
            row.tags = ["rejected"]
            brain.memory.semantic.stored[("jarvis_self_rule", predicate)] = row

    def fake_history(n=500, hours_ago=None):
        return {"available": True, "turns": turns}

    brain.get_conversation_history = fake_history
    return brain


def test_repeated_correction_gets_proposed_as_pending_never_auto_adopted():
    turns = [
        {"user_said": "PDF reader banao", "jarvis_replied": "ok", "timestamp": 1000},
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 1010},
        {"user_said": "kya haal hai", "jarvis_replied": "theek", "timestamp": 2000},
        {"user_said": "nahi Termux mat bolo, hum Kali Linux pe hai instead", "jarvis_replied": "ok", "timestamp": 3010},
    ]
    brain = _make_brain(turns)
    result = brain.audit_and_learn_from_history()

    assert result["audited"] is True
    assert result["rules_proposed"] == 1
    assert result["proposed"][0]["occurrences"] == 2
    assert "Kali Linux" in result["proposed"][0]["rule"]

    stored = brain.memory.semantic.find(subject="jarvis_self_rule")
    assert len(stored) == 1
    assert "pending_confirmation" in stored[0].tags
    assert "from_audit" in stored[0].tags
    assert "confirmed" not in stored[0].tags
    assert "auto_adopted" not in stored[0].tags


def test_one_off_correction_proposes_nothing():
    turns = [
        {"user_said": "not this approach, use SymPy instead", "jarvis_replied": "ok", "timestamp": 1000},
    ]
    brain = _make_brain(turns)
    result = brain.audit_and_learn_from_history()
    assert result["rules_proposed"] == 0
    assert brain.memory.semantic.find(subject="jarvis_self_rule") == []


def test_previously_rejected_rule_never_reproposed():
    rule_text = 'Not "Termux nahi" -- always "hum Kali Linux pe hai"'
    turns = [
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 1010},
        {"user_said": "nahi Termux mat bolo, hum Kali Linux pe hai instead", "jarvis_replied": "ok", "timestamp": 3010},
    ]
    brain = _make_brain(turns, seed_rejected=[rule_text])
    result = brain.audit_and_learn_from_history()

    assert result["rules_proposed"] == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["status"] == "previously_rejected_by_uk"


def test_no_available_history_returns_honest_unavailable_status():
    brain = Brain.__new__(Brain)
    brain.memory = _FakeMemory()
    brain.get_conversation_history = lambda n=500, hours_ago=None: {"available": False, "turns": []}
    result = brain.audit_and_learn_from_history()
    assert result["audited"] is False
    assert result["rules_proposed"] == 0


def test_no_semantic_memory_fails_honestly_not_silently():
    turns = [
        {"user_said": "Termux nahi, Kali Linux use karo instead", "jarvis_replied": "ok", "timestamp": 1010},
        {"user_said": "nahi Termux mat bolo, hum Kali Linux pe hai instead", "jarvis_replied": "ok", "timestamp": 3010},
    ]
    brain = Brain.__new__(Brain)

    class _NoSemanticMemory:
        semantic = None

    brain.memory = _NoSemanticMemory()
    brain.get_conversation_history = lambda n=500, hours_ago=None: {"available": True, "turns": turns}
    result = brain.audit_and_learn_from_history()
    assert result["audited"] is True
    assert result["rules_found"] == 1  # the audit itself still worked
    assert result["rules_proposed"] == 0  # but nothing could be persisted
    assert "not available" in result["reason"]


if __name__ == "__main__":
    test_repeated_correction_gets_proposed_as_pending_never_auto_adopted()
    test_one_off_correction_proposes_nothing()
    test_previously_rejected_rule_never_reproposed()
    test_no_available_history_returns_honest_unavailable_status()
    test_no_semantic_memory_fails_honestly_not_silently()
    print("✓ ALL audit_and_learn_from_history TESTS PASSED")
