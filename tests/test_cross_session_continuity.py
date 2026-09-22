"""Tests for cross-session continuity (2026-09-19).

UK's explicit ask: "continuity aur coherent nature stops jab restart
karta hoon" -- a brand-new ConversationState is correct for a genuinely
new conversation, but a process restart mid-task must not read as a
new conversation. bootstrap_from_history() reconstructs enough
continuity from REAL persisted episodic history (which survives
restarts) to feel coherent, without inventing anything.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.conversation_continuity import ConversationContinuityLayer
from core.orchestration.response_brief import build_response_brief


def test_bootstrap_seeds_prior_session_context_verbatim():
    """The real prior turns must reach the state VERBATIM -- not a
    derived/summarized version that could misrepresent them."""
    turns = [
        {"user_said": "PDF reader banao python based ocr cli", "jarvis_replied": "ok banata hoon", "timestamp": 1000},
        {"user_said": "pytesseract use karo", "jarvis_replied": "theek hai", "timestamp": 1010},
    ]
    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.bootstrap_from_history(turns)

    assert c.state.prior_session_context is not None
    assert "PDF reader banao python based ocr cli" in c.state.prior_session_context
    assert "pytesseract use karo" in c.state.prior_session_context


def test_bootstrap_seeds_session_goal_from_recent_execution_turn():
    """Uses the EXISTING hardened detect_interaction_mode() -- not a
    new heuristic -- to seed session_goal from the most recent
    EXECUTION-mode message in the prior history."""
    turns = [
        {"user_said": "kya haal hai", "jarvis_replied": "theek hoon", "timestamp": 1000},
        {"user_said": "OCR CLI tool banao abhi", "jarvis_replied": "ok", "timestamp": 2000},
    ]
    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.bootstrap_from_history(turns)

    assert c.state.session_goal is not None
    assert "OCR CLI tool banao" in c.state.session_goal


def test_bootstrap_does_not_overwrite_a_real_in_session_goal():
    """set_session_goal() only sets once -- if a REAL turn in THIS
    session already established a goal, bootstrap must not have
    already been allowed to silently override it. (Bootstrap runs at
    startup, before any real turn -- this locks in the ordering
    guarantee.)"""
    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.bootstrap_from_history([
        {"user_said": "old task from before restart, banao ye", "jarvis_replied": "ok", "timestamp": 1000},
    ])
    bootstrapped_goal = c.state.session_goal
    assert bootstrapped_goal is not None

    # A genuinely new turn in THIS session must NOT override it (matches
    # existing set_session_goal() semantics -- set once per session).
    c.begin_turn("naya tool banao")
    c.update_from_turn("naya tool banao", user_intent={"name": "command"})
    assert c.state.session_goal == bootstrapped_goal


def test_no_history_leaves_state_cleanly_blank():
    """A genuinely first-ever session (no prior history at all) must
    not fabricate anything -- prior_session_context/session_goal stay
    None, exactly like a normal fresh ConversationState."""
    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.bootstrap_from_history([])
    assert c.state.prior_session_context is None
    assert c.state.session_goal is None


def test_bootstrapped_context_reaches_the_response_brief():
    """End-to-end: bootstrap -> get_relevant_context -> build_response_brief,
    confirming the reconstructed continuity actually reaches what the
    LLM sees, not just internal state."""
    turns = [
        {"user_said": "PDF reader banao python based ocr cli", "jarvis_replied": "ok banata hoon", "timestamp": 1000},
        {"user_said": "pytesseract use karo", "jarvis_replied": "theek hai", "timestamp": 1010},
    ]
    c = ConversationContinuityLayer(session_id="s", run_id="r")
    c.bootstrap_from_history(turns)
    c.begin_turn("Continue")

    relevant = c.get_relevant_context()
    brief = build_response_brief(
        user_input="Continue", perception={}, context={}, active_rules=[],
        continuity_context=relevant,
    )
    assert brief["session_goal"] is not None
    assert brief["prior_session_context"] is not None
    assert brief["has_real_conversation_memory"] is True
    assert "prior_session_context" in brief["instructions_for_llm"]


if __name__ == "__main__":
    test_bootstrap_seeds_prior_session_context_verbatim()
    test_bootstrap_seeds_session_goal_from_recent_execution_turn()
    test_bootstrap_does_not_overwrite_a_real_in_session_goal()
    test_no_history_leaves_state_cleanly_blank()
    test_bootstrapped_context_reaches_the_response_brief()
    print("✓ ALL CROSS-SESSION CONTINUITY TESTS PASSED")
