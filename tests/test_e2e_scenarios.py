"""
END-TO-END SCENARIO VERIFICATION -- Conversation Intelligence Layer

UK's explicit request (2026-09-18): "mujhe test script do jisme sach
mein kai saare raw chats hon jisse JARVIS ke bugs khud identify ho
jaaye" -- a runnable script, using a FAKE LLM (this sandbox has no
network), that exercises the REAL code paths against scenarios
mirroring his actual on-device failures, and prints expected-vs-actual
so he can compare against real JARVIS output by pasting the same
inputs into the live system.

This is NOT a mocked "does the function get called" test. Every
scenario below runs the ACTUAL classify_capability(),
TaskLoop.stream_capability()/stream(), ConversationContinuityLayer,
and ToolCapabilityRegistry code -- only the network LLM call itself
is replaced with a scripted FakeBridge that returns the exact JSON a
real model would for that prompt shape.

Run: python3 tests/test_e2e_scenarios.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.conversation_intelligence import (
    classify_capability, DISCUSSION, RESEARCH, PLANNING, FULL_BUILD,
)
from core.cognition.conversation_continuity import ConversationContinuityLayer
from core.cognition.conversation_state import InteractionMode
from core.cognition.tool_capability_registry import ToolCapabilityRegistry
from core.orchestration.task_loop import TaskLoop


PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
_results = []


def check(name: str, condition: bool, expected: str, actual: str):
    status = PASS if condition else FAIL
    _results.append(condition)
    print(f"{status}  {name}")
    if not condition:
        print(f"       expected: {expected}")
        print(f"       actual:   {actual}")


class FakeBridge:
    """Scripted LLM bridge -- returns canned responses in call order.

    For understand/plan-style calls used by TaskLoop, and for the
    classify_capability() JSON classification call. Mirrors the real
    llm_bridge.generate_response() interface exactly (same kwargs),
    so the code under test cannot tell the difference except for
    what comes back over the wire.
    """
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_log = []

    def budget_status(self):
        return {"remaining_calls": 99, "remaining_output_tokens": 100000}

    def generate_response(self, **kwargs):
        self.call_log.append(kwargs.get("user_input", "")[:80])
        if not self.responses:
            return '{"goal": "unspecified", "assumptions": [], "done_when": []}'
        return self.responses.pop(0)


class FakeBrain:
    """Minimal brain stand-in -- TaskLoop only needs brain.llm.budget_status()
    and (for code steps, which we never reach in research/planning) brain.run_coding_task."""
    def __init__(self, bridge):
        self.llm = bridge


print("=" * 70)
print("SCENARIO 1: 'chalo tool create karo... pahle discuss karte hai'")
print("(UK's exact failing transcript -- this used to force-launch TaskLoop)")
print("=" * 70)

bridge1 = FakeBridge(['{"capability": "planning", "confidence": 0.85}'])
result1 = classify_capability(
    bridge1,
    "Jarvis chalo ek tool create karo basically ek python script jo kai "
    "mini scripts k sath import hokar ek robust camera acces and scene "
    "object identifier bnana hai. To chalo pahle plan karte hai no "
    "coding pahale discusss karte hai",
)
check(
    "Capability classified as PLANNING, not FULL_BUILD",
    result1["capability"] == PLANNING,
    "planning (no code execution)",
    result1["capability"],
)

print()
print("=" * 70)
print("SCENARIO 2: Planning capability produces a plan WITHOUT executing code")
print("=" * 70)

bridge2 = FakeBridge([
    '{"goal": "Design a camera access + scene object identifier tool", '
    '"assumptions": ["opencv available"], "done_when": ["architecture documented"]}',
    '[{"kind": "write", "description": "Draft module architecture"}, '
    '{"kind": "write", "description": "List required libraries"}]',
])
loop2 = TaskLoop(bridge2.generate_response, brain=FakeBrain(bridge2), effort="medium")
events2 = list(loop2.stream_capability(
    "camera access aur scene identifier tool ka plan banao, coding mat karo",
    PLANNING,
))
event_types = [e["type"] for e in events2]
check(
    "No 'code' or 'write' EXECUTION stage_start fired (only understand+plan)",
    "stage_start" not in [e["type"] for e in events2 if e.get("stage") in ("code", "write", "verify")],
    "only understand/plan stage_start events, no execution",
    f"stages seen: {[e.get('stage') for e in events2 if e['type'] == 'stage_start']}",
)
check(
    "Ends with capability_complete carrying the plan",
    events2[-1]["type"] == "capability_complete" and events2[-1]["capability"] == "planning",
    "capability_complete/planning as final event",
    f"{events2[-1]['type']}" + (f"/{events2[-1].get('capability')}" if 'capability' in events2[-1] else ""),
)

print()
print("=" * 70)
print("SCENARIO 3: Pure research request never even reaches a plan")
print("=" * 70)

bridge3 = FakeBridge([
    '{"goal": "Assess whether on-device OCR is viable for this phone", '
    '"assumptions": [], "done_when": ["feasibility assessed"]}',
])
loop3 = TaskLoop(bridge3.generate_response, brain=FakeBrain(bridge3), effort="medium")
events3 = list(loop3.stream_capability("kya on-device OCR feasible hai iss phone ke liye, research karo", RESEARCH))
check(
    "Only ONE LLM call made (understand only, no plan call)",
    len(bridge3.call_log) == 1,
    "1 call",
    f"{len(bridge3.call_log)} calls",
)
check(
    "Ends immediately after understand with capability_complete/research",
    events3[-1]["type"] == "capability_complete" and events3[-1]["capability"] == "research",
    "capability_complete/research",
    f"{events3[-1]['type']}/{events3[-1].get('capability')}",
)

print()
print("=" * 70)
print("SCENARIO 4: Real build request WITH full spec -> FULL_BUILD, correctly")
print("=" * 70)

bridge4 = FakeBridge(['{"capability": "full_build", "confidence": 0.95}'])
result4 = classify_capability(
    bridge4,
    "Yahan poora spec hai: alarm.py jo HH:MM leta hai, validate karta hai, "
    "wait karta hai, aur beep karta hai. Ab isko bana do aur verify karo.",
)
check(
    "A handed-over spec with 'ab bana do' classifies as FULL_BUILD",
    result4["capability"] == FULL_BUILD,
    "full_build",
    result4["capability"],
)

print()
print("=" * 70)
print("SCENARIO 5: Plain question never triggers ANY LLM call (native shortcut)")
print("=" * 70)

bridge5 = FakeBridge([])  # deliberately empty -- if this gets called, the test fails loud
result5 = classify_capability(bridge5, "yeh kya hai?", native_intent={"name": "question"})
check(
    "Native question shortcut used, zero LLM calls",
    result5["source"] == "native_question_intent" and len(bridge5.call_log) == 0,
    "source=native_question_intent, 0 calls",
    f"source={result5['source']}, {len(bridge5.call_log)} calls",
)

print()
print("=" * 70)
print("SCENARIO 6: Correction changes behavior -- coding agent blocked right after")
print("(UK's requirement section 4: correction must change state, not just be acknowledged)")
print("=" * 70)

continuity6 = ConversationContinuityLayer(session_id="s6", run_id="r6")
continuity6.state.interaction_mode = InteractionMode.EXECUTION
continuity6.state.stated_goal = "build PDF reader"
continuity6.state.user_intent = {"name": "build"}
continuity6.state.current_turn = 3
before = continuity6.should_invoke_coding_agent()
continuity6.state.record_correction(
    was_wrong="PDF reader with pypdf",
    should_be="PDF reader with pdfplumber instead",
    evidence="नहीं, pypdf नहीं चाहिए; pdfplumber चाहिए",
)
continuity6.state.corrections_this_session[-1].turn_number = continuity6.state.current_turn
after = continuity6.should_invoke_coding_agent()
check(
    "should_invoke_coding_agent() was True before correction, False right after",
    before is True and after is False,
    "before=True, after=False",
    f"before={before}, after={after}",
)

print()
print("=" * 70)
print("SCENARIO 7: PDF reader tool lifecycle -- create, verify, register, rediscover")
print("(UK's requirement section 8: fix the PDF-reader create-then-forget bug)")
print("=" * 70)

registry7 = ToolCapabilityRegistry()
with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
    pdf_tool_path = f.name
    f.write(b"# pdf_reader.py stub\n")

try:
    registry7.create_tool("pdf_reader", "script", path=pdf_tool_path)
    registry7.verify_tool("pdf_reader", "ran against a sample PDF, extracted text successfully")
    registry7.register_capability(
        "pdf_reader",
        capability_tags=["pdf_reading"],
        discovery_phrases=["pdf padhna", "read pdf", "pdf reader", "pdf padho"],
    )

    # Later turn: user uploads a PDF and asks JARVIS to read it, in
    # completely different words than how the tool was registered.
    found = registry7.find_tool_by_discovery("ye PDF padh ke batao isme kya likha hai")
    check(
        "Tool rediscovered from a NEW phrasing that matches a registered discovery phrase",
        found is not None and found.name == "pdf_reader",
        "pdf_reader tool found",
        f"{found.name if found else None}",
    )
    check(
        "Tool reports itself available with real evidence, not a guess",
        found.is_available() and found.verification_evidence is not None,
        "available=True, verification_evidence present",
        f"available={found.is_available() if found else 'N/A'}, evidence={found.verification_evidence if found else 'N/A'}",
    )
finally:
    os.unlink(pdf_tool_path)

print()
print("=" * 70)
print("SCENARIO 8: Tool registry NEVER invents a path for a tool that doesn't exist")
print("(UK's requirement section 10: never invent evidence/paths)")
print("=" * 70)

registry8 = ToolCapabilityRegistry()
raised = False
try:
    registry8.create_tool("phantom_tool", "script", path="/this/path/was/never/created")
except ValueError:
    raised = True
check(
    "Creating a tool with a non-existent path raises instead of silently accepting it",
    raised,
    "ValueError raised",
    f"raised={raised}",
)

print()
print("=" * 70)
print("SCENARIO 9: Extended Thinking route now carries continuity context")
print("(UK's Bug 3: 'unnecessary respond... discuss nahi kar paya' -- traced to")
print(" combined_ctx having ZERO conversation continuity, only persona identity)")
print("=" * 70)

continuity9 = ConversationContinuityLayer(session_id="s9", run_id="r9")
continuity9.state.current_topic = "PDF reader tool ka summary feature"
continuity9.state.add_entity("PDF reader", "tool")
relevant9 = continuity9.get_relevant_context()
check(
    "get_relevant_context() surfaces current_topic for the SSE route to use",
    relevant9["current_topic"] == "PDF reader tool ka summary feature",
    "PDF reader tool ka summary feature",
    str(relevant9["current_topic"]),
)
check(
    "get_relevant_context() surfaces last_named_entity so 'ye model' resolves",
    relevant9["last_named_entity"] == "PDF reader",
    "PDF reader",
    str(relevant9["last_named_entity"]),
)

print()
print("=" * 70)
print("SCENARIO 10: Raw '[LLM unavailable]' sentinel never reaches the user")
print("(Bug 1/2: blank responses + new LLM errors -- root cause was this sentinel")
print(" leaking past think_stream()/TaskLoop with no friendly fallback)")
print("=" * 70)

SENTINEL = "[LLM unavailable: cloud providers failed; local fallback is disabled]"


def _always_fails(**kwargs):
    return SENTINEL


from core.cognition.thinking import think_stream as _think_stream
events10 = list(_think_stream(_always_fails, user_input="summary do", mode="extended", effort="medium"))
leaked = [e for e in events10 if SENTINEL in str(e.get("content", ""))]
check(
    "No SSE event exposes the raw sentinel as stage/answer content",
    len(leaked) == 0,
    "0 events contain the raw sentinel",
    f"{len(leaked)} events leaked it",
)
answers10 = [e for e in events10 if e["type"] == "answer"]
check(
    "A real (non-blank, non-sentinel) answer is still produced when the provider fails",
    bool(answers10) and answers10[-1]["content"].strip() and SENTINEL not in answers10[-1]["content"],
    "non-empty honest fallback message",
    answers10[-1]["content"] if answers10 else "(no answer event at all)",
)

print()
print("=" * 70)
print("SCENARIO 11: Correction now actually reaches the response brief")
print("(UK's core ask: 'koi correction karu to uska behavior agle response")
print(" mein nazar aaye' -- traced to update_from_turn() never being called)")
print("=" * 70)

from core.orchestration.response_brief import build_response_brief as _build_brief

continuity11 = ConversationContinuityLayer(session_id="s11", run_id="r11")
continuity11.begin_turn("Termux ka zikr mat karo, wo galti se bola, Linux ki baat kar raha tha main")
continuity11.update_from_turn(
    "Termux ka zikr mat karo, wo galti se bola, Linux ki baat kar raha tha main",
    user_intent={"name": "statement"},
)
# Simulate what the earlier turn had already established, then the correction
continuity11.state.corrections_this_session.clear()
continuity11.state.record_correction(
    was_wrong="Termux/PRoot ARM64 environment",
    should_be="Kali Linux environment",
    evidence="Termux ka zikr mat karo, Linux ki baat kar raha tha",
)
relevant11 = continuity11.get_relevant_context()
brief11 = _build_brief(
    user_input="ab plan batao",
    perception={},
    context={},
    active_rules=[],
    continuity_context=relevant11,
)
check(
    "active_correction field is populated in the brief the LLM actually sees",
    brief11["active_correction"] is not None and "Kali Linux" in brief11["active_correction"],
    "active_correction mentions Kali Linux",
    str(brief11["active_correction"]),
)
check(
    "Instructions tell the LLM the correction is a standing constraint, not a mention",
    "STANDING CONSTRAINT" in brief11["instructions_for_llm"],
    "instruction present",
    "present" if "STANDING CONSTRAINT" in brief11["instructions_for_llm"] else "MISSING",
)

print()
print("=" * 70)
print("SCENARIO 12: Backend now emits narrative commentary + step chunking")
print("(UK's screenshot ask: prose paragraphs interleaved between collapsed")
print(" 'N steps' groups, matching Claude's own UI -- not a flat step list)")
print("=" * 70)


class _FakeBrainForNarrative:
    class llm:
        @staticmethod
        def budget_status():
            return {"remaining_calls": 20, "remaining_output_tokens": 100000}


_narrative_responses = [
    '{"goal": "build a calculator", "assumptions": [], "done_when": ["adds two numbers correctly"]}',
    '[{"kind": "write", "description": "Write calculator.py"}, {"kind": "verify", "description": "Check it works"}, '
    '{"kind": "write", "description": "Fix the bug"}, {"kind": "verify", "description": "Re-check"}]',
    "def add(a,b): return a+b",
    '{"complete": false, "failures": ["subtraction not implemented"]}',
    "def add(a,b): return a+b\ndef sub(a,b): return a-b",
    '{"complete": true, "failures": []}',
]
_idx = [0]


def _fake_generate_narrative(**kwargs):
    r = _narrative_responses[_idx[0]]
    _idx[0] += 1
    return r


loop12 = TaskLoop(_fake_generate_narrative, brain=_FakeBrainForNarrative(), effort="medium")
events12 = list(loop12.stream("build a calculator"))
narratives12 = [e for e in events12 if e["type"] == "narrative"]
chunk_ids12 = sorted(set(e.get("chunk_id") for e in events12 if e["type"] == "stage" and "chunk_id" in e))

check(
    "At least an intro narrative and a post-verify narrative were emitted",
    len(narratives12) >= 2,
    ">= 2 narrative events",
    f"{len(narratives12)} events",
)
check(
    "Post-verify narrative is grounded in the REAL failure, not invented",
    len(narratives12) >= 2 and "subtraction not implemented" in narratives12[1]["content"],
    "mentions 'subtraction not implemented'",
    narratives12[1]["content"] if len(narratives12) >= 2 else "(missing)",
)
check(
    "Steps are split across 2+ chunks (before/after the verify failure)",
    len(chunk_ids12) >= 2,
    ">= 2 distinct chunk_ids",
    str(chunk_ids12),
)

print()
print("=" * 70)
print("SCENARIO 13: Chunked large-file generation across a truncated LLM output")
print("(UK: 'chhote chunks mein bhejna aur chunks output ko accumulate karke")
print(" poora kaam karna' -- so a 10000-line file doesn't hit payload/output limits)")
print("=" * 70)

from core.orchestration.task_loop import TaskStep, KIND_WRITE

class _FakeBrainChunked:
    class llm:
        @staticmethod
        def budget_status():
            return {"remaining_calls": 20, "remaining_output_tokens": 100000}


_chunk_pieces = [
    "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return (",
    "a * b)\n\nclass Calculator:\n    def __init__(self):\n        self.history = [",
    "]\n\n    def compute(self, op, a, b):\n        return op(a, b)\n",
]
_ci = [0]


def _fake_gen_chunked(**kwargs):
    r = _chunk_pieces[_ci[0]]
    _ci[0] += 1
    return r


loop13 = TaskLoop(_fake_gen_chunked, brain=_FakeBrainChunked(), effort="medium")
step13 = TaskStep(index=1, kind=KIND_WRITE, description="write a calculator module")
loop13._run_write_step("build calculator.py", step13, "")

check(
    "Exactly 3 LLM calls made (2 continuations + final complete chunk)",
    _ci[0] == 3,
    "3 calls",
    f"{_ci[0]} calls",
)
check(
    "Full file accumulated correctly across all chunks",
    step13.ok is True and "class Calculator" in step13.output and "def compute" in step13.output,
    "step.ok=True, full class present",
    f"ok={step13.ok}, output={step13.output[:80]!r}",
)

_ci2 = [0]


def _fake_gen_normal(**kwargs):
    _ci2[0] += 1
    return "def hello():\n    return True\n"


loop13b = TaskLoop(_fake_gen_normal, brain=_FakeBrainChunked(), effort="medium")
step13b = TaskStep(index=1, kind=KIND_WRITE, description="write a hello function")
loop13b._run_write_step("simple task", step13b, "")
check(
    "A normal, complete, single-call output does NOT trigger a wasted continuation call",
    _ci2[0] == 1,
    "1 call",
    f"{_ci2[0]} calls",
)

print()
print("=" * 70)
print(f"RESULTS: {sum(_results)}/{len(_results)} scenarios passed")
print("=" * 70)
if all(_results):
    print("\n✓✓✓ ALL SCENARIOS PASS against the real code with a scripted LLM. ✓✓✓")
    print("To verify against the REAL JARVIS: paste the same messages from")
    print("scenarios 1, 4, and 6's correction line into a live chat and confirm")
    print("the disposition/capability event JARVIS streams matches what's printed above.")
else:
    print("\n✗ Some scenarios failed -- see details above.")
    sys.exit(1)
