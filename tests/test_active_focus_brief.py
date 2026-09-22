"""Regression test for the active_focus wiring fix (2026-09-18).

Root cause this locks in: SemanticUnderstandingEngine._resolve_references()
already correctly resolves Hinglish/English pronouns ("ye/wo/isse/usse")
to the most-recently-mentioned entity and reports it as a
"resolved_reference" inference on perception["semantic_understanding"]
["inferences"] -- but build_response_brief() never read that field, so
the LLM never saw it and had to re-guess the referent from raw recap
text. This test fails loudly again if that wire is ever silently
dropped (the exact "built but never wired" failure mode UK keeps
hitting).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration.response_brief import build_response_brief


def _perception_with_resolved_reference(mention: str, entity_text: str) -> dict:
    return {
        "intent": {"name": "command", "confidence": 0.9},
        "language": "hinglish",
        "semantic_understanding": {
            "inferences": [
                {
                    "type": "resolved_reference",
                    "mention": mention,
                    "entity": {"text": entity_text},
                    "confidence": 0.86,
                }
            ]
        },
    }


def test_active_focus_present_when_reference_resolved():
    perception = _perception_with_resolved_reference("ise", "calculator")
    brief = build_response_brief(
        user_input="ab ise fix karo",
        perception=perception,
        context={},
        active_rules=[],
    )
    assert brief["active_focus"] == ["'ise' abhi refers to: calculator"]
    assert "active_focus" in brief["instructions_for_llm"]


def test_active_focus_empty_when_no_semantic_understanding():
    brief = build_response_brief(
        user_input="hi",
        perception={"intent": {}},
        context={},
        active_rules=[],
    )
    assert brief["active_focus"] == []


def test_active_focus_ignores_unresolved_reference():
    perception = {
        "semantic_understanding": {
            "inferences": [
                {"type": "resolved_reference", "mention": "ise", "entity": None, "confidence": 0.0}
            ]
        }
    }
    brief = build_response_brief(
        user_input="ise dekho",
        perception=perception,
        context={},
        active_rules=[],
    )
    assert brief["active_focus"] == []


def test_active_focus_multiple_resolved_references():
    perception = {
        "semantic_understanding": {
            "inferences": [
                {"type": "resolved_reference", "mention": "ise", "entity": {"text": "calculator"}, "confidence": 0.86},
                {"type": "current_learning_target", "subject": "user", "value": "python"},
                {"type": "resolved_reference", "mention": "usse", "entity": {"text": "PDF reader"}, "confidence": 0.7},
            ]
        }
    }
    brief = build_response_brief(
        user_input="ise aur usse dono dekho",
        perception=perception,
        context={},
        active_rules=[],
    )
    assert brief["active_focus"] == [
        "'ise' abhi refers to: calculator",
        "'usse' abhi refers to: PDF reader",
    ]


def test_conversation_focus_present_from_last_event():
    perception = {
        "semantic_context_snapshot": {
            "last_events": [{"event_type": "learning_started", "object": "Python"}],
            "recent_turns": [],
        }
    }
    brief = build_response_brief(user_input="ok", perception=perception, context={}, active_rules=[])
    assert brief["conversation_focus"] == ["current task in progress: learning started -- Python"]
    assert "conversation_focus" in brief["instructions_for_llm"]


def test_conversation_focus_lists_recent_topics_dedup_and_ordered():
    perception = {
        "semantic_context_snapshot": {
            "last_events": [],
            "recent_turns": [
                {"entities": [{"text": "PDF reader"}]},
                {"entities": [{"text": "calculator"}]},
                {"entities": [{"text": "PDF reader"}]},  # repeat -- must not duplicate
            ],
        }
    }
    brief = build_response_brief(user_input="ok", perception=perception, context={}, active_rules=[])
    assert brief["conversation_focus"] == [
        "things mentioned in the last few turns (most recent last): PDF reader, calculator"
    ]


def test_conversation_focus_empty_when_snapshot_missing():
    brief = build_response_brief(user_input="hi", perception={}, context={}, active_rules=[])
    assert brief["conversation_focus"] == []


def test_has_real_conversation_memory_false_on_fresh_session():
    brief = build_response_brief(user_input="hi", perception={}, context={}, active_rules=[])
    assert brief["has_real_conversation_memory"] is False
    assert "SESSION MEMORY RULE" in brief["instructions_for_llm"]


def test_has_real_conversation_memory_true_when_any_field_populated():
    perception = _perception_with_resolved_reference("ise", "calculator")
    brief = build_response_brief(user_input="x", perception=perception, context={}, active_rules=[])
    assert brief["has_real_conversation_memory"] is True

    context_with_recap = {"recent_experiences": [{"context": {"user_input": "camera tool banao"}, "outcome": {"response": "chalo plan karte hain"}}]}
    brief2 = build_response_brief(user_input="x", perception={}, context=context_with_recap, active_rules=[])
    assert brief2["has_real_conversation_memory"] is True


def test_grounding_context_is_separate_field_never_mixed_into_user_message():
    brief = build_response_brief(
        user_input="ye kya hai",
        perception={},
        context={},
        active_rules=[],
        grounding_context="TaskLoop already installed the package and verified it.",
    )
    assert brief["extended_thinking_grounding"] == "TaskLoop already installed the package and verified it."
    assert brief["user_message"] == "ye kya hai"  # never polluted
    assert "extended_thinking_grounding" in brief["instructions_for_llm"]


def test_grounding_context_defaults_to_empty_string():
    brief = build_response_brief(user_input="hi", perception={}, context={}, active_rules=[])
    assert brief["extended_thinking_grounding"] == ""


if __name__ == "__main__":
    test_active_focus_present_when_reference_resolved()
    test_active_focus_empty_when_no_semantic_understanding()
    test_active_focus_ignores_unresolved_reference()
    test_active_focus_multiple_resolved_references()
    test_conversation_focus_present_from_last_event()
    test_conversation_focus_lists_recent_topics_dedup_and_ordered()
    test_conversation_focus_empty_when_snapshot_missing()
    test_has_real_conversation_memory_false_on_fresh_session()
    test_has_real_conversation_memory_true_when_any_field_populated()
    test_grounding_context_is_separate_field_never_mixed_into_user_message()
    test_grounding_context_defaults_to_empty_string()
    print("all response_brief tests passed")
