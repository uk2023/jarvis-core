"""Regression tests: raw "[LLM unavailable: ...]" sentinel must NEVER
reach the user directly, in either think_stream() (Extended Thinking
staged reasoner) or TaskLoop (the coding-agent/capability loop).

UK caught this on-device (2026-09-18 chat log): the "Understanding
request" step literally displayed
"[LLM unavailable: cloud providers failed; local fallback is
disabled]" as if it were JARVIS's own reasoning, and the same text
reached him as a final answer in another turn. Root cause:
llm_bridge.generate_response() returns this as a normal STRING (not an
exception) when no backend is usable; brain.py's main chat pipeline
already had a safety net for this (_record_action_response), but
think_stream() and TaskLoop run as separate pipelines that never
passed through it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.thinking import think_stream
from core.orchestration.task_loop import TaskLoop, TaskStep, KIND_WRITE, KIND_VERIFY

SENTINEL = "[LLM unavailable: cloud providers failed; local fallback is disabled]"


class _FakeBrainLLM:
    @staticmethod
    def budget_status():
        return {"remaining_calls": 10, "remaining_output_tokens": 50000}


class _FakeBrain:
    llm = _FakeBrainLLM()


def _always_fails(**kwargs):
    return SENTINEL


def test_think_stream_never_leaks_sentinel_as_stage_content():
    events = list(think_stream(_always_fails, user_input="ye model kis liye hai?", mode="extended", effort="medium"))
    for e in events:
        content = str(e.get("content", ""))
        assert SENTINEL not in content, f"sentinel leaked in event: {e}"


def test_think_stream_never_leaks_sentinel_as_final_answer():
    events = list(think_stream(_always_fails, user_input="summary do", mode="extended", effort="medium"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers, "expected at least one answer event"
    assert SENTINEL not in answers[-1]["content"]
    # Must be an honest, non-empty message -- not silently blank either.
    assert answers[-1]["content"].strip() != ""


def test_think_stream_off_mode_also_never_leaks_sentinel():
    """The thinking-off fast path (effort='low') has its own separate
    _call() invocation -- must be covered too, not just the staged path."""
    events = list(think_stream(_always_fails, user_input="hi", mode="normal", effort="low"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers
    assert SENTINEL not in answers[-1]["content"]


def test_taskloop_write_step_marked_failed_not_falsely_successful():
    """The most dangerous form of this bug: bool(sentinel_string) is
    True, so a failed step was being reported as successfully done."""
    loop = TaskLoop(_always_fails, brain=_FakeBrain(), effort="medium")
    step = TaskStep(index=1, kind=KIND_WRITE, description="write something")
    loop._run_write_step("some task", step, "")
    assert step.ok is False
    assert SENTINEL not in step.output


def test_taskloop_verify_step_marked_failed_not_falsely_successful():
    loop = TaskLoop(_always_fails, brain=_FakeBrain(), effort="medium")
    step = TaskStep(index=1, kind=KIND_VERIFY, description="verify something")
    loop._run_verify_step({"done_when": ["x"]}, step, "some context")
    assert step.ok is False
    assert SENTINEL not in step.output


def test_taskloop_understand_degrades_to_task_text_not_sentinel():
    """_understand() already had its own fallback (JSON parse failure
    -> fall back to the task itself); confirm the sentinel doesn't leak
    through that path either now that _call() raises on it."""
    loop = TaskLoop(_always_fails, brain=_FakeBrain(), effort="medium")
    understanding = loop._understand("build a PDF reader")
    assert SENTINEL not in str(understanding)
    assert understanding.get("goal") == "build a PDF reader"


if __name__ == "__main__":
    test_think_stream_never_leaks_sentinel_as_stage_content()
    test_think_stream_never_leaks_sentinel_as_final_answer()
    test_think_stream_off_mode_also_never_leaks_sentinel()
    test_taskloop_write_step_marked_failed_not_falsely_successful()
    test_taskloop_verify_step_marked_failed_not_falsely_successful()
    test_taskloop_understand_degrades_to_task_text_not_sentinel()
    print("✓ ALL SENTINEL-LEAK REGRESSION TESTS PASSED")
