"""Tests for core/learning/improvement_requests.py's over-broad pattern
fix (2026-09-19) -- and the downstream get_self_authored_rules() fix
in response_brief.py.

Root cause chain confirmed from UK's own runtime trace logs:
1. is_improvement_request() had a pattern matching "main chahta hoon
   ki" ("I want that...") -- the single most generic way to phrase ANY
   request in Hindi, with zero specificity to "improve JARVIS itself".
2. It fired on an ordinary coding-project request, writing a
   jarvis_self/improvement_request fact.
3. That ONE fact then appeared in the semantic_evidence of every
   SUBSEQUENT turn for the rest of the session (confirmed in the raw
   trace), regardless of topic, confusing every later reply.
4. Separately, brain.py's routing self-evaluation auto-adopted a
   "Reconsider routing this kind of input to 'llm' -- gather more
   context before committing" self-rule from evidence gathered DURING
   this buggy period -- and get_self_authored_rules() was surfacing
   THAT routing-strategy meta-note to the response-generating LLM call
   as if it were a behavioral rule to follow, which the model read as
   an instruction to hedge -- on every single later turn.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.learning.improvement_requests import is_improvement_request
from core.orchestration.response_brief import get_self_authored_rules


def test_uk_real_message_no_longer_misclassified():
    message = (
        "filhal Mujhe bus yah tool Banakar de do main Yahi intran Hai Mera Ki Main "
        "Chahta Hun Ki Tum Mere Liye property join Karke website Karke library select "
        "karo Ek Bar perfect design bnao architecture ki Kaise Ham mis call ko receive "
        "kar sakte hain vahan per project manage karo aur jo bhi change vagaira karne "
        "Rahenge next Ham baat karenge"
    )
    assert is_improvement_request(message) is False


def test_normal_project_requests_not_misclassified():
    for text in (
        "mujhe ye PDF reader tool chahiye jo CLI based ho",
        "main chahta hoon ki tum website banao",
        "mujhe is project ke liye ek blueprint chahiye",
    ):
        assert is_improvement_request(text) is False, text


def test_genuine_improvement_requests_still_recognized():
    for text in (
        "yeh ek bug hai isko fix karo",
        "mujhe ye feature chahiye ki tum multi-language support karo",
        "yeh improvement chahiye",
        "isse fix karo",
        "mujhe ye capability chahiye ki tum web search kar sako",
    ):
        assert is_improvement_request(text) is True, text


class _FakeItem:
    def __init__(self, predicate, tags, value, updated_at=0):
        self.predicate = predicate
        self.tags = tags
        self.value = value
        self.updated_at = updated_at


class _FakeSemantic:
    def __init__(self, items):
        self._items = items

    def find(self, subject=None):
        return self._items


class _FakeMemory:
    def __init__(self, items):
        self.semantic = _FakeSemantic(items)


def test_routing_strategy_meta_rule_filtered_from_active_rules():
    """UK's exact real captured data: a routing-strategy self-note that
    was being surfaced to the response LLM as if it were a behavioral
    rule, causing systemic hedging."""
    items = [
        _FakeItem(
            "learned_behavior_llm_23feb732d6",
            ["self_authored", "confirmed", "auto_adopted"],
            "Reconsider routing this kind of input to 'llm' -- try an "
            "alternative route or gather more context before committing to it.",
        ),
    ]
    rules = get_self_authored_rules(_FakeMemory(items))
    assert rules == []


def test_genuine_behavioral_rule_still_surfaces():
    items = [
        _FakeItem(
            "learned_behavior_llm_23feb732d6",
            ["self_authored", "confirmed", "auto_adopted"],
            "Reconsider routing this kind of input to 'llm' -- gather more context.",
        ),
        _FakeItem(
            "user_correction_kali_linux_abc123",
            ["self_authored", "confirmed"],
            "Always use Kali Linux, never Termux, for this project.",
        ),
    ]
    rules = get_self_authored_rules(_FakeMemory(items))
    assert len(rules) == 1
    assert "Kali Linux" in rules[0]


def test_unconfirmed_rules_never_surface_regardless():
    """Sanity check the existing "only confirmed" behavior is preserved
    alongside the new routing-strategy filter."""
    items = [
        _FakeItem("some_predicate_abc", ["self_authored", "pending_confirmation"], "Not yet confirmed."),
    ]
    rules = get_self_authored_rules(_FakeMemory(items))
    assert rules == []


if __name__ == "__main__":
    test_uk_real_message_no_longer_misclassified()
    test_normal_project_requests_not_misclassified()
    test_genuine_improvement_requests_still_recognized()
    test_routing_strategy_meta_rule_filtered_from_active_rules()
    test_genuine_behavioral_rule_still_surfaces()
    test_unconfirmed_rules_never_surface_regardless()
    print("✓ ALL IMPROVEMENT-REQUEST MISCLASSIFICATION FIX TESTS PASSED")
