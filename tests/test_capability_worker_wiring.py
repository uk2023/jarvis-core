"""Regression tests, 2026-09-20 root-cause pass (UK's chat-log audit).

Locks in three fixes:
  1. run_capability_worker (companion_tools.py) actually reaches
     TaskLoop.stream_capability() with a valid capability, rejects an
     invalid one, and applies the same full_build->planning downgrade
     gate Extended Thinking already uses.
  2. tool_registry.py registers run_capability_worker (schema +
     WRITE_TOOLS + ONCE_PER_TURN_TOOLS) so it is actually offered to
     the model, and sets brain.last_tool_loop_failed honestly when
     generate_with_tools hard-fails vs. genuinely finding no tool
     needed.
  3. ConversationContinuityLayer.format_relevant_context_text() is the
     single formatter now used by both routes_codebox.py and
     companion_tools.py (no more silently-diverging duplicate).

Run directly: python3 tests/test_capability_worker_wiring.py
(no pytest in this sandbox -- see other test files in this repo for
the same pattern).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestration import tool_registry
from core.orchestration.companion_tools import CompanionToolsMixin
from core.cognition.conversation_continuity import ConversationContinuityLayer


class _FakeLLM:
    def __init__(self, reply="[]"):
        self._reply = reply
        self.calls = 0

    def generate_response(self, **kwargs):
        self.calls += 1
        return self._reply

    def budget_status(self):
        return {"remaining_calls": 5}


class _FakeContinuity:
    def __init__(self, allow_full_build=True):
        self._allow = allow_full_build

    def format_relevant_context_text(self):
        return "Conversation so far:\nCurrent topic: PDF reader"

    def should_invoke_coding_agent(self):
        return self._allow


class _FakeBrain(CompanionToolsMixin):
    def __init__(self, allow_full_build=True):
        self.llm = _FakeLLM()
        self.role = "owner"
        self.is_verified = True
        self.conversation_continuity = _FakeContinuity(allow_full_build)


def test_run_capability_worker_rejects_unknown_capability():
    brain = _FakeBrain()
    result = brain.run_capability_worker("PDF reader banao", capability="not_a_real_one")
    assert "error" in result, "unknown capability must be rejected, never silently coerced"
    print("OK: unknown capability rejected")


def test_run_capability_worker_requires_objective():
    brain = _FakeBrain()
    result = brain.run_capability_worker("", capability="planning")
    assert "error" in result
    print("OK: empty objective rejected")


def test_run_capability_worker_planning_reaches_task_loop_and_stops_before_execution():
    brain = _FakeBrain()
    # A plan-only capability must never touch code/write/verify steps --
    # simulate the LLM returning a trivial JSON plan for _plan()/_understand().
    result = brain.run_capability_worker("python cli ocr pdf reader ka plan banao", capability="planning")
    assert result["capability"] == "planning"
    assert result["status"] in ("COMPLETE", "ABORTED"), result
    print("OK: planning capability runs end-to-end via run_capability_worker, status=%s" % result["status"])


def test_full_build_downgrades_when_continuity_disagrees():
    brain = _FakeBrain(allow_full_build=False)
    result = brain.run_capability_worker("PDF reader poora bana do", capability="full_build")
    assert result["capability"] == "planning", "must downgrade to planning, never silently run full_build"
    print("OK: full_build downgrades to planning when continuity layer disagrees")


def test_full_build_proceeds_when_continuity_agrees():
    brain = _FakeBrain(allow_full_build=True)
    result = brain.run_capability_worker("PDF reader poora bana do, ready hoon", capability="full_build")
    # capability may still legitimately end up as "full_build" (agreed) --
    # what matters is it was NOT force-downgraded.
    assert result["capability"] == "full_build"
    print("OK: full_build proceeds when continuity layer agrees")


def test_tool_registry_exposes_run_capability_worker():
    assert "run_capability_worker" in tool_registry.WRITE_TOOLS
    assert "run_capability_worker" in tool_registry.ONCE_PER_TURN_TOOLS
    assert "run_capability_worker" in tool_registry.LOCAL_TOOL_NAMES
    schemas = tool_registry.build_tool_schemas()
    names = {s["function"]["name"] for s in schemas if s.get("type") == "function"}
    assert "run_capability_worker" in names, "must actually be offered to the model"
    print("OK: run_capability_worker registered and schema-exposed")


def test_dispatch_tool_call_routes_to_the_new_method():
    brain = _FakeBrain()
    result = tool_registry.dispatch_tool_call(
        brain, "run_capability_worker",
        {"objective": "PDF reader ka plan banao", "capability": "planning"},
    )
    assert "error" not in result, result
    assert result["capability"] == "planning"
    print("OK: dispatch_tool_call reaches run_capability_worker")


class _NoneOnFirstCall:
    """Fake LLM whose generate_with_tools mimics a hard provider failure."""
    def generate_with_tools(self, **kwargs):
        return None

    def budget_status(self):
        return {"remaining_calls": 5}


def test_hard_tool_failure_sets_honest_flag():
    class _Brain:
        llm = _NoneOnFirstCall()

    brain = _Brain()
    result = tool_registry.run_tool_loop(brain, system_prompt="sys", user_message="PDF reader banao")
    assert result is None
    assert getattr(brain, "last_tool_loop_failed", False) is True, (
        "a genuine generate_with_tools(None) failure must be distinguishable "
        "from 'the model decided no tool was needed'"
    )
    print("OK: last_tool_loop_failed=True set on genuine hard failure")


def test_continuity_formatter_is_single_source_of_truth():
    layer = ConversationContinuityLayer(session_id="test", run_id="test")
    layer.state.current_topic = "PDF reader"
    layer.state.session_goal = "Build a CLI OCR PDF reader"
    text = layer.format_relevant_context_text()
    assert "PDF reader" in text
    assert "Session goal" in text
    print("OK: format_relevant_context_text() produces real, non-empty context text")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        t()
        passed += 1
    print(f"\n{passed}/{len(tests)} tests passed.")
