"""CONVERSATION INTELLIGENCE LAYER -- phase 1.

UK's explicit architectural correction (2026-09-18, after rejecting a
keyword-list version of this same decision): a fixed set of phrases
like "pehle discuss"/"no coding" can only ever catch the exact wording
someone thought to enumerate, in the language they thought to write it
in. It is not judgment, it is string-matching wearing a judgment's
clothes -- and it silently fails the moment UK phrases the same intent
differently, or in a different language. His words: "LLM kaunsa
filter ho sakta hai -- intent se filter ho sakta hai." JARVIS's own
architecture has NOTHING hardcoded for judgment calls like this --
only deterministic NATIVE pattern-matching for things that genuinely
are deterministic (a literal "?" makes something a question), and the
LLM as JARVIS's own reasoning capability for everything that actually
requires understanding. This module is that capability, used here for
exactly one judgment call so far: does this turn want to be DISCUSSED
before any action, or is the user ready for JARVIS to act right now.

This is Phase 1 of the layer proposed in
CONVERSATION_INTELLIGENCE_LAYER_BLUEPRINT.txt section 4. Phase 2 (the
memory-routing decision: which of session/episodic/semantic memory a
turn actually needs) is NOT built yet -- see that file's section 6.
Nothing in this module should be read as claiming Phase 2 is done.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

DISCUSS_FIRST = "discuss_first"
READY_TO_ACT = "ready_to_act"


def _native_shortcut(user_input: str, native_intent: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Zero-cost pre-check for genuinely unambiguous cases ONLY --
    never a decision mechanism for the discuss-vs-act judgment itself.

    The one case that's truly deterministic, not a judgment call: a
    turn perception already classified as a plain question (native
    intent detector, engine.py's _detect_intent -- a literal '?' or a
    question-word pattern) cannot simultaneously be a "build this for
    me right now" instruction. Everything else -- including anything
    that LOOKS like a build request -- goes to the LLM classifier
    below, because telling a genuine "banao" apart from "banao, but
    let's discuss the design first" is exactly the kind of judgment a
    keyword list cannot make and an LLM call can.
    """
    intent_name = (native_intent or {}).get("name") if isinstance(native_intent, dict) else None
    if intent_name == "question":
        return {"disposition": DISCUSS_FIRST, "confidence": 0.6, "source": "native_question_intent"}
    return None


_SYSTEM_PROMPT = (
    "Classify what the user wants JARVIS to do RIGHT NOW in their "
    "message. Two possible answers only:\n"
    "  discuss_first -- the user wants to talk through the idea, "
    "clarify requirements, see a plan/blueprint, or otherwise wants "
    "JARVIS to hold off on writing/running any code until they've "
    "actually agreed on what to build. This includes messages that "
    "mention building something but explicitly ask to plan, design, "
    "or discuss BEFORE coding, in any language or phrasing.\n"
    "  ready_to_act -- the user wants JARVIS to actually carry out a "
    "task now: write code, run something, fix something, build "
    "something, or otherwise take real action, with no further "
    "discussion needed first. A message that already contains a full "
    "spec/blueprint the user is handing over counts as ready_to_act, "
    "not discuss_first -- they are not asking for a conversation "
    "about it, they already had one.\n"
    "Respond with ONLY a JSON object: "
    '{"disposition": "discuss_first" | "ready_to_act", "confidence": 0.0-1.0}'
)


def classify_task_disposition(
    llm_bridge: Any,
    user_input: str,
    native_intent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Does this turn want discussion first, or is it ready for action?

    Returns {"disposition": DISCUSS_FIRST | READY_TO_ACT, "confidence":
    float, "source": str}. "source" is always honest about how the
    answer was reached (native_question_intent / llm / degraded) --
    never silently presented as a confident LLM judgment when it
    wasn't one, per the project's no-fabricated-fallback principle.

    When the LLM truly cannot be called (budget exhausted, no bridge,
    a call error), this returns source="degraded" with disposition
    defaulting to READY_TO_ACT -- chosen deliberately, not arbitrarily:
    the old (pre-2026-09-18) behavior for ambiguous/uncertain turns
    was always to act, so a degraded classification preserves that
    prior behavior rather than introducing a NEW way for turns to
    silently stall. Callers that care whether this was a real judgment
    should check "source" == "llm", not just "disposition".
    """
    user_input = str(user_input or "")

    shortcut = _native_shortcut(user_input, native_intent)
    if shortcut is not None:
        return shortcut

    try:
        from ..orchestration.llm_bridge import can_afford_another_llm_call
    except Exception:
        try:
            from core.orchestration.llm_bridge import can_afford_another_llm_call
        except Exception:
            can_afford_another_llm_call = None  # type: ignore

    if llm_bridge is None or not hasattr(llm_bridge, "generate_response"):
        return {"disposition": READY_TO_ACT, "confidence": 0.0, "source": "degraded_no_bridge"}

    if callable(can_afford_another_llm_call) and not can_afford_another_llm_call(llm_bridge):
        return {"disposition": READY_TO_ACT, "confidence": 0.0, "source": "degraded_budget_exhausted"}

    try:
        raw = llm_bridge.generate_response(
            system_prompt=_SYSTEM_PROMPT,
            user_input=user_input,
            max_tokens=60,
            temperature=0.0,
            level="perception_and_understanding",
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
    except Exception as exc:
        return {"disposition": READY_TO_ACT, "confidence": 0.0, "source": f"degraded_call_error:{type(exc).__name__}"}

    cleaned = re.sub(r"^```(?:json)?|```$", "", str(raw or "").strip(), flags=re.MULTILINE).strip()
    try:
        from ..contracts.extraction import extract_first_json_object
    except Exception:
        from core.contracts.extraction import extract_first_json_object

    try:
        data = extract_first_json_object(cleaned)
    except Exception:
        data = None

    if not isinstance(data, dict) or data.get("disposition") not in (DISCUSS_FIRST, READY_TO_ACT):
        return {"disposition": READY_TO_ACT, "confidence": 0.0, "source": "degraded_unparseable_response"}

    confidence = data.get("confidence", 0.7)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.7

    return {"disposition": data["disposition"], "confidence": confidence, "source": "llm"}


# ---------------------------------------------------------------------
# CAPABILITY CLASSIFICATION -- 2026-09-18, UK's follow-up correction
# ---------------------------------------------------------------------
# "Extended thinking is not equal to coding agent." UK's own words: a
# user who wants deep research or a plan, and NOT code, must be able
# to get JARVIS to hire exactly the research/planning capability --
# not the full build-and-execute loop -- even with extended thinking
# on. discuss_first/ready_to_act was a binary; this is the real
# four-way distinction UK actually specified in section 7: JARVIS
# decides WHICH worker is required, not just whether to act.
#
# This is now the single authority routes_codebox.py consults before
# invoking ANY TaskLoop capability -- see think_stream_route.

DISCUSSION = "discussion"
RESEARCH = "research"
PLANNING = "planning"
FULL_BUILD = "full_build"
# INDIVIDUAL WORKERS (2026-09-19, UK: "coding agent ke parallel workers
# ko Jarvis user ki demand poori karne ke liye apne hisab se, apne
# cognition se, kisi individual worker se kaam le sakta hai... kuchh
# edit karna hai to editing worker, kuchh debug karna hai to debug and
# fix worker". Previously only full_build (the complete understand->
# plan->execute->verify loop) could touch code at all -- a narrow "fix
# this one bug" or "make this one edit" request had no way to reach a
# SINGLE targeted worker without paying for a full multi-step plan.
EDITING = "editing"
DEBUG_FIX = "debug_fix"

_VALID_CAPABILITIES = (DISCUSSION, RESEARCH, PLANNING, FULL_BUILD, EDITING, DEBUG_FIX)

_CAPABILITY_SYSTEM_PROMPT = (
    "Classify what JARVIS should actually do for this message. Six "
    "possible answers:\n"
    "  discussion -- the user wants to talk, ask a question, or get an "
    "explanation. No task, no plan, no code.\n"
    "  research -- the user wants JARVIS to think something through "
    "deeply and report findings/understanding back -- e.g. \"is this "
    "approach viable\", \"what would this involve\" -- but is NOT "
    "asking for a step-by-step plan or any code yet.\n"
    "  planning -- the user wants a concrete plan/blueprint/design "
    "produced (steps, architecture, module breakdown), explicitly "
    "WITHOUT writing or running any code yet. This includes any "
    "message that mentions building something but says to plan/"
    "design/discuss first, in any language or phrasing.\n"
    "  editing -- the user wants ONE targeted change made to existing "
    "code/text -- rename something, change one function, adjust one "
    "file -- not a new multi-step build and not a bug investigation.\n"
    "  debug_fix -- the user has a specific error, failing test, or "
    "broken behavior and wants it diagnosed and fixed -- not a new "
    "feature, not a full rebuild, just making the existing thing work.\n"
    "  full_build -- the user wants JARVIS to actually write and run "
    "code now: build something new, implement a spec they already "
    "gave, or otherwise take real multi-step action with no more "
    "planning needed first. A message handing over a complete spec "
    "counts as full_build, not planning -- they already had that "
    "conversation.\n"
    "Respond with ONLY a JSON object: "
    '{"capability": "discussion" | "research" | "planning" | "editing" | '
    '"debug_fix" | "full_build", "confidence": 0.0-1.0}'
)


def classify_capability(
    llm_bridge: Any,
    user_input: str,
    native_intent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Which ONE capability does this turn actually need?

    Returns {"capability": DISCUSSION|RESEARCH|PLANNING|FULL_BUILD,
    "confidence": float, "source": str}. Same honesty contract as
    classify_task_disposition(): "source" always says how the answer
    was reached, degraded results are never dressed up as confident
    LLM judgments, and a degraded result defaults to DISCUSSION (the
    safest default -- never silently launches a build) rather than
    FULL_BUILD, which is the opposite default from
    classify_task_disposition()'s degraded READY_TO_ACT. That
    difference is deliberate: this function's job is specifically to
    gate the coding agent, so its failure mode must fail CLOSED (no
    unauthorized code execution) rather than preserve old behavior.
    """
    user_input = str(user_input or "")

    intent_name = (native_intent or {}).get("name") if isinstance(native_intent, dict) else None
    if intent_name == "question":
        return {"capability": DISCUSSION, "confidence": 0.6, "source": "native_question_intent"}

    try:
        from ..orchestration.llm_bridge import can_afford_another_llm_call
    except Exception:
        try:
            from core.orchestration.llm_bridge import can_afford_another_llm_call
        except Exception:
            can_afford_another_llm_call = None  # type: ignore

    if llm_bridge is None or not hasattr(llm_bridge, "generate_response"):
        return {"capability": DISCUSSION, "confidence": 0.0, "source": "degraded_no_bridge"}

    if callable(can_afford_another_llm_call) and not can_afford_another_llm_call(llm_bridge):
        return {"capability": DISCUSSION, "confidence": 0.0, "source": "degraded_budget_exhausted"}

    try:
        raw = llm_bridge.generate_response(
            system_prompt=_CAPABILITY_SYSTEM_PROMPT,
            user_input=user_input,
            max_tokens=60,
            temperature=0.0,
            level="perception_and_understanding",
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
    except Exception:
        # RESILIENCE FALLBACK (2026-09-19, UK's BALANCE panel showed ALL
        # 10 Groq keys failing with 400 Bad Request simultaneously --
        # including on the plain tool-calling path this function never
        # touches, so that specific outage is very likely account/
        # model-level, not caused by response_format/reasoning_effort
        # here. Still: if EITHER of those two optional params is ever
        # the actual problem for a given account/model/moment, this
        # retry recovers instead of burning the whole degraded-to-
        # DISCUSSION path over an avoidable param mismatch. One retry
        # only -- this must never become its own multi-call cascade.
        try:
            raw = llm_bridge.generate_response(
                system_prompt=_CAPABILITY_SYSTEM_PROMPT + ' Reply with ONLY the JSON object, nothing else.',
                user_input=user_input,
                max_tokens=60,
                temperature=0.0,
                level="perception_and_understanding",
            )
        except Exception as exc:
            return {"capability": DISCUSSION, "confidence": 0.0, "source": f"degraded_call_error:{type(exc).__name__}"}

    cleaned = re.sub(r"^```(?:json)?|```$", "", str(raw or "").strip(), flags=re.MULTILINE).strip()
    try:
        from ..contracts.extraction import extract_first_json_object
    except Exception:
        from core.contracts.extraction import extract_first_json_object

    try:
        data = extract_first_json_object(cleaned)
    except Exception:
        data = None

    if not isinstance(data, dict) or data.get("capability") not in _VALID_CAPABILITIES:
        return {"capability": DISCUSSION, "confidence": 0.0, "source": "degraded_unparseable_response"}

    confidence = data.get("confidence", 0.7)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.7

    return {"capability": data["capability"], "confidence": confidence, "source": "llm"}
