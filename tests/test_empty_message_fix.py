"""Regression tests: a genuinely empty LLM response must NEVER reach
the user as a blank "..." message, in any of the three places a final
answer gets produced (brain.py's main chat pipeline, thinking.py's two
answer-generation paths).

UK caught this from his own screenshots/logs: bare "..." bubbles in
both normal and extended thinking. Root cause: the existing sentinel
check (for the KNOWN "[LLM unavailable: ...]" string, fixed in an
earlier pass) never checked for a genuinely EMPTY string -- which can
happen without any exception and without the sentinel prefix.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.thinking import think_stream

FRIENDLY_FALLBACK = "Mujhe is baar koi jawab nahi mila"


def _empty_gen(**kwargs):
    return ""


def _whitespace_only_gen(**kwargs):
    return "   \n  "


def test_thinking_off_fast_path_never_yields_empty_answer():
    events = list(think_stream(_empty_gen, user_input="hi", mode="normal", effort="low"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers
    assert answers[-1]["content"].strip() != ""
    assert FRIENDLY_FALLBACK in answers[-1]["content"]


def test_staged_reasoner_never_yields_empty_answer():
    events = list(think_stream(_empty_gen, user_input="hi", mode="extended", effort="medium"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers
    assert answers[-1]["content"].strip() != ""
    assert FRIENDLY_FALLBACK in answers[-1]["content"]


def test_whitespace_only_response_also_treated_as_empty():
    """Not just literally "" -- a response that's ONLY whitespace is
    functionally empty too and must get the same honest fallback."""
    events = list(think_stream(_whitespace_only_gen, user_input="hi", mode="normal", effort="low"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers
    assert FRIENDLY_FALLBACK in answers[-1]["content"]


def test_normal_non_empty_answer_passes_through_unchanged():
    """The fix must not touch a real, non-empty answer."""
    def real_gen(**kwargs):
        return "Namaste sir, yahan hoon."

    events = list(think_stream(real_gen, user_input="hi", mode="normal", effort="low"))
    answers = [e for e in events if e["type"] == "answer"]
    assert answers[-1]["content"] == "Namaste sir, yahan hoon."


def test_brain_record_action_response_has_empty_check():
    """Structural check: brain.py's _record_action_response() (the
    main chat pipeline's single chokepoint every turn passes through)
    must have the same empty-response guard, right after the existing
    sentinel-prefix check it was added alongside."""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "orchestration", "brain.py"),
        encoding="utf-8",
    ).read()
    assert "elif not response_text.strip():" in src
    assert "empty_response" in src


if __name__ == "__main__":
    test_thinking_off_fast_path_never_yields_empty_answer()
    test_staged_reasoner_never_yields_empty_answer()
    test_whitespace_only_response_also_treated_as_empty()
    test_normal_non_empty_answer_passes_through_unchanged()
    test_brain_record_action_response_has_empty_check()
    print("✓ ALL EMPTY-MESSAGE REGRESSION TESTS PASSED")
