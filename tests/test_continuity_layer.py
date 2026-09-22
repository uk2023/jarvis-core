"""Comprehensive tests for Conversation Intelligence & Continuity Layer.

UK requirements (sections 2, 3, 4, 5, 8): JARVIS must maintain coherent
conversational state, apply corrections, track mode, manage tool lifecycle,
and make decisions about coding-agent invocation.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.conversation_state import (
    ConversationState, InteractionMode, Decision,
)
from core.cognition.conversation_continuity import ConversationContinuityLayer
from core.cognition.tool_capability_registry import (
    ToolCapabilityRegistry, ToolStatus, initialize_registry,
)


def test_conversation_state_tracks_entities():
    """Test that ConversationState properly tracks entities mentioned."""
    state = ConversationState(session_id="test1", run_id="run1", start_time=time.time())
    
    # Add an entity
    entity = state.add_entity("PDF reader", "tool", {"type": "python_script"})
    assert entity.name == "PDF reader"
    assert entity.type == "tool"
    assert "PDF reader".lower() in state.entities
    assert state.last_named_entity == "PDF reader"


def test_conversation_state_resolves_pronouns():
    """Test pronoun resolution."""
    state = ConversationState(session_id="test2", run_id="run1", start_time=time.time())
    
    state.add_entity("PDF reader", "tool")
    state.reference_entity("this", "PDF reader")
    state.reference_entity("it", "PDF reader")
    
    assert state.resolve_pronoun("this") == "PDF reader"
    assert state.resolve_pronoun("it") == "PDF reader"


def test_conversation_state_records_decisions():
    """Test decision recording."""
    state = ConversationState(session_id="test3", run_id="run1", start_time=time.time())
    
    decision = state.record_decision(
        "Create PDF reader tool",
        evidence="user said: बना दो PDF reader",
    )
    assert decision.what == "Create PDF reader tool"
    assert len(state.decisions_this_session) == 1


def test_conversation_state_records_corrections():
    """Test that corrections are recorded and can influence behavior."""
    state = ConversationState(session_id="test4", run_id="run1", start_time=time.time())
    
    correction = state.record_correction(
        was_wrong="नहीं, मुझे X चाहिए",
        should_be="Y चाहिए",
        evidence="user said: नहीं, मुझे Y चाहिए",
    )
    assert correction.what_was_wrong == "नहीं, मुझे X चाहिए"
    assert len(state.corrections_this_session) == 1


def test_conversation_continuity_detects_discussion_mode():
    """Test that DISCUSSION mode is detected correctly."""
    continuity = ConversationContinuityLayer(
        session_id="test5",
        run_id="run1",
    )
    
    # Hindi discussion marker
    mode = continuity.detect_interaction_mode("पहले discuss करते हैं")
    assert mode == InteractionMode.DISCUSSION
    
    # English discussion marker
    mode = continuity.detect_interaction_mode("Let's talk about this first")
    assert mode == InteractionMode.DISCUSSION


def test_conversation_continuity_detects_planning_mode():
    """Test that PLANNING mode is detected correctly."""
    continuity = ConversationContinuityLayer(
        session_id="test6",
        run_id="run1",
    )
    
    # Hindi planning marker
    mode = continuity.detect_interaction_mode("पहले blueprint design करते हैं")
    assert mode == InteractionMode.PLANNING
    
    # English planning marker
    mode = continuity.detect_interaction_mode("Let's design this first, before coding")
    assert mode == InteractionMode.PLANNING


def test_conversation_continuity_detects_execution_mode():
    """Test that EXECUTION mode is detected correctly."""
    continuity = ConversationContinuityLayer(
        session_id="test7",
        run_id="run1",
    )
    
    # Hindi execution marker
    mode = continuity.detect_interaction_mode("PDF reader बना दो")
    assert mode == InteractionMode.EXECUTION
    
    # English execution marker
    mode = continuity.detect_interaction_mode("Build the tool now")
    assert mode == InteractionMode.EXECUTION


def test_conversation_continuity_detects_correction():
    """Test correction detection."""
    continuity = ConversationContinuityLayer(
        session_id="test8",
        run_id="run1",
    )
    
    correction = continuity.detect_correction(
        "नहीं, मुझे X नहीं चाहिए; Y चाहिए"
    )
    assert correction is not None
    was_wrong, should_be = correction
    assert "X" in was_wrong
    assert "Y" in should_be


def test_conversation_continuity_maintains_turn_history():
    """Test that turn history is maintained."""
    continuity = ConversationContinuityLayer(
        session_id="test9",
        run_id="run1",
    )
    
    continuity.begin_turn("user input 1")
    continuity.end_turn("user input 1", "JARVIS response 1")
    
    continuity.begin_turn("user input 2")
    continuity.end_turn("user input 2", "JARVIS response 2")
    
    assert continuity.state.current_turn == 2
    assert len(continuity._turn_history) == 2
    assert continuity.state.previous_turn_input == "user input 2"


def test_tool_registry_never_hallucinates_paths():
    """Test that tool registry never invents paths -- it verifies they exist."""
    registry = ToolCapabilityRegistry()
    
    # Try to create a tool with a non-existent path
    try:
        registry.create_tool(
            "fake_tool",
            "script",
            path="/absolutely/fake/path/that/does/not/exist",
        )
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "does not exist" in str(e)


def test_tool_registry_lifecycle():
    """Test the full tool lifecycle: CREATE → VERIFY → REGISTER → AVAILABLE."""
    registry = ToolCapabilityRegistry()
    
    # Create a real temp file to use as tool path
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
        temp_path = f.name
    
    try:
        # CREATE
        tool = registry.create_tool("test_tool", "script", path=temp_path)
        assert tool.status == ToolStatus.CREATED
        
        # VERIFY
        registry.verify_tool("test_tool", "Unit test passed")
        assert tool.status == ToolStatus.VERIFIED
        assert tool.verified_at is not None
        
        # REGISTER as a capability
        registry.register_capability(
            "test_tool",
            capability_tags=["testing"],
            discovery_phrases=["test tool", "testing"],
        )
        assert tool.status == ToolStatus.AVAILABLE
        assert "testing" in tool.capability_tags
        
        # DISCOVER
        found = registry.find_tool_for_capability("testing")
        assert found is not None
        assert found.name == "test_tool"
        
        # LOOKUP by user phrasing
        found2 = registry.find_tool_by_discovery("can you use the test tool?")
        assert found2 is not None
    finally:
        os.unlink(temp_path)


def test_tool_registry_error_tracking():
    """Test that errors are tracked with evidence."""
    registry = ToolCapabilityRegistry()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
        temp_path = f.name
    
    try:
        tool = registry.create_tool("broken_tool", "script", path=temp_path)
        registry.verify_tool("broken_tool", "Basic sanity check passed")
        
        # Record an error
        tool.record_error("IndentationError at line 42")
        assert tool.status == ToolStatus.BROKEN
        assert tool.last_error == "IndentationError at line 42"
        assert any("IndentationError" in err for err in tool.errors)
    finally:
        os.unlink(temp_path)


def test_tool_registry_availability_check():
    """Test is_available() respects both status and path existence."""
    registry = ToolCapabilityRegistry()
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
        temp_path = f.name
    
    try:
        tool = registry.create_tool("avail_tool", "script", path=temp_path)
        
        # Not available until verified + registered
        assert not tool.is_available()
        
        registry.verify_tool("avail_tool", "test")
        registry.register_capability(
            "avail_tool",
            capability_tags=["avail"],
            discovery_phrases=[],
        )
        
        # Now it should be available
        assert tool.is_available()
        
        # Delete the file and check again
        os.unlink(temp_path)
        assert not tool.is_available()
    except:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def test_coding_agent_not_invoked_in_discussion_mode():
    """Test that coding agent is NOT auto-invoked in discussion mode."""
    continuity = ConversationContinuityLayer(
        session_id="test10",
        run_id="run1",
    )
    
    # Set mode to discussion
    continuity.state.interaction_mode = InteractionMode.DISCUSSION
    
    # Even if there's a stated goal, don't invoke coding in discussion mode
    continuity.state.stated_goal = "Build a PDF reader"
    
    assert not continuity.should_invoke_coding_agent()


def test_coding_agent_invoked_in_execution_mode():
    """Test that coding agent CAN be invoked in execution mode (with clear task)."""
    continuity = ConversationContinuityLayer(
        session_id="test11",
        run_id="run1",
    )
    
    # Set mode to execution
    continuity.state.interaction_mode = InteractionMode.EXECUTION
    continuity.state.stated_goal = "Build a PDF reader"
    continuity.state.user_intent = {"name": "build"}
    
    assert continuity.should_invoke_coding_agent()


def test_coding_agent_not_invoked_right_after_correction():
    """Test that coding agent is NOT invoked immediately after user correction."""
    continuity = ConversationContinuityLayer(
        session_id="test12",
        run_id="run1",
    )
    
    continuity.state.interaction_mode = InteractionMode.EXECUTION
    continuity.state.current_turn = 5
    
    # User just made a correction
    continuity.state.record_correction(
        was_wrong="approach A",
        should_be="approach B",
        evidence="user said: no use approach B",
    )
    continuity.state.corrections_this_session[-1].turn_number = 5  # This turn
    
    # Don't immediately code after a correction
    assert not continuity.should_invoke_coding_agent()


def test_update_from_turn_actually_sets_stated_goal_and_user_intent():
    """REGRESSION TEST for a real bug found 2026-09-19: update_from_turn()
    never assigned state.stated_goal/state.user_intent anywhere in the
    codebase (confirmed by grep), so should_invoke_coding_agent()'s
    EXECUTION-mode branch -- which requires one of them truthy -- was
    PERMANENTLY unreachable in real usage. Since routes_codebox.py wired
    this as the second gate on FULL_BUILD, every full_build classification
    was silently downgraded to "planning" the whole time. This test calls
    update_from_turn() itself (not manual state pokes) and asserts the
    full real path actually reaches an invokable state."""
    continuity = ConversationContinuityLayer(session_id="regress1", run_id="run1")
    continuity.begin_turn("PDF reader bana do abhi")
    continuity.update_from_turn(
        "PDF reader bana do abhi",
        user_intent={"name": "command", "confidence": 0.9},
    )

    assert continuity.state.interaction_mode == InteractionMode.EXECUTION
    assert continuity.state.user_intent == {"name": "command", "confidence": 0.9}
    assert continuity.state.stated_goal == "PDF reader bana do abhi"
    # The actual end-to-end assertion: the real gate, driven by the real
    # update_from_turn() call, now returns True -- not just when a test
    # manually sets internal fields.
    assert continuity.should_invoke_coding_agent() is True


def test_update_from_turn_does_not_set_stated_goal_in_discussion_mode():
    """A discussion-mode turn must NOT get treated as a stated build goal
    -- only EXECUTION-mode turns set stated_goal."""
    continuity = ConversationContinuityLayer(session_id="regress2", run_id="run1")
    continuity.begin_turn("PDF reader ke baare mein discuss karna hai")
    continuity.update_from_turn(
        "PDF reader ke baare mein discuss karna hai",
        user_intent={"name": "question"},
    )
    assert continuity.state.interaction_mode == InteractionMode.DISCUSSION
    assert continuity.state.stated_goal is None
    assert continuity.should_invoke_coding_agent() is False


if __name__ == "__main__":
    test_conversation_state_tracks_entities()
    test_conversation_state_resolves_pronouns()
    test_conversation_state_records_decisions()
    test_conversation_state_records_corrections()
    test_conversation_continuity_detects_discussion_mode()
    test_conversation_continuity_detects_planning_mode()
    test_conversation_continuity_detects_execution_mode()
    test_conversation_continuity_detects_correction()
    test_conversation_continuity_maintains_turn_history()
    test_tool_registry_never_hallucinates_paths()
    test_tool_registry_lifecycle()
    test_tool_registry_error_tracking()
    test_tool_registry_availability_check()
    test_coding_agent_not_invoked_in_discussion_mode()
    test_coding_agent_invoked_in_execution_mode()
    test_coding_agent_not_invoked_right_after_correction()
    test_update_from_turn_actually_sets_stated_goal_and_user_intent()
    test_update_from_turn_does_not_set_stated_goal_in_discussion_mode()
    print("✓ ALL CONTINUITY LAYER TESTS PASSED")
