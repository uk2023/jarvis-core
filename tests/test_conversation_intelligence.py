"""Regression tests for core/cognition/conversation_intelligence.py.

UK's explicit correction (2026-09-18): a keyword-list version of the
discuss-vs-act decision was rejected as a brittle, single-language
"temporary patch". This locks in that the replacement is genuinely
LLM-judgment-based (not a keyword table in disguise), degrades
honestly when the LLM can't be reached, and never crashes on a bad
response.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.conversation_intelligence import (
    classify_task_disposition,
    DISCUSS_FIRST,
    READY_TO_ACT,
)


class _FakeBridge:
    def __init__(self, response=None, remaining_calls=5, raise_on_call=None):
        self._response = response
        self._remaining_calls = remaining_calls
        self._raise_on_call = raise_on_call

    def budget_status(self):
        return {"remaining_calls": self._remaining_calls}

    def generate_response(self, **kwargs):
        if self._raise_on_call:
            raise self._raise_on_call
        return self._response


def test_question_intent_is_a_zero_cost_native_shortcut():
    bridge = _FakeBridge(raise_on_call=AssertionError("must not call LLM for a plain question"))
    result = classify_task_disposition(bridge, "yeh kya hai?", native_intent={"name": "question"})
    assert result["disposition"] == DISCUSS_FIRST
    assert result["source"] == "native_question_intent"


def test_no_bridge_degrades_honestly_not_silently():
    result = classify_task_disposition(None, "PDF reader bana do")
    assert result["source"] == "degraded_no_bridge"
    assert result["disposition"] == READY_TO_ACT


def test_budget_exhausted_skips_the_call_entirely():
    bridge = _FakeBridge(remaining_calls=0, raise_on_call=AssertionError("must not call when budget exhausted"))
    result = classify_task_disposition(bridge, "PDF reader bana do")
    assert result["source"] == "degraded_budget_exhausted"


def test_real_llm_judgment_discuss_first_any_phrasing():
    # The exact point: this phrasing is NOT in any keyword list, it's
    # the LLM's own judgment call, exercised the same as any phrasing.
    bridge = _FakeBridge(response='{"disposition": "discuss_first", "confidence": 0.85}')
    result = classify_task_disposition(bridge, "I have an idea for a tool but let's talk it through first")
    assert result == {"disposition": "discuss_first", "confidence": 0.85, "source": "llm"}


def test_real_llm_judgment_ready_to_act():
    bridge = _FakeBridge(response='{"disposition": "ready_to_act", "confidence": 0.95}')
    result = classify_task_disposition(bridge, "here's the full spec, build it now")
    assert result["disposition"] == READY_TO_ACT
    assert result["source"] == "llm"


def test_malformed_llm_response_degrades_without_crashing():
    bridge = _FakeBridge(response="not json at all")
    result = classify_task_disposition(bridge, "x")
    assert result["source"] == "degraded_unparseable_response"
    assert result["disposition"] == READY_TO_ACT


def test_llm_exception_degrades_without_crashing():
    bridge = _FakeBridge(raise_on_call=RuntimeError("provider down"))
    result = classify_task_disposition(bridge, "x")
    assert result["source"].startswith("degraded_call_error")


if __name__ == "__main__":
    test_question_intent_is_a_zero_cost_native_shortcut()
    test_no_bridge_degrades_honestly_not_silently()
    test_budget_exhausted_skips_the_call_entirely()
    test_real_llm_judgment_discuss_first_any_phrasing()
    test_real_llm_judgment_ready_to_act()
    test_malformed_llm_response_degrades_without_crashing()
    test_llm_exception_degrades_without_crashing()
    print("all conversation_intelligence tests passed")
