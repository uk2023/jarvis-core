from __future__ import annotations

"""EXTENDED THINKING -- reasoning that is visible, and that JARVIS can
switch on for itself.

UK (2026-09-13): "extended thinking jaisa feature enable karo CLI mein
bhi, frontend mein bhi, backend API ki tarah -- aur JARVIS khud kar sake
meri baat sun ke." Plus: the UI should show the thinking arriving
progressively, the way Claude and GPT do, rather than a spinner followed
by a wall of text.

Three entry points, one implementation:

  * OFF (default) -- one call, normal chat. Most turns do not benefit
    from deliberation and paying for it on every message would waste
    UK's token budget for nothing.
  * ON -- UK toggles it from the UI button or `/think on` in the CLI.
  * AUTO -- JARVIS decides per turn. This is the "khud kar sake" part:
    should_think_harder() inspects the turn's structure, the same way
    information_need.py decides where an answer lives. No LLM call is
    made to decide whether to make LLM calls, because that would cost
    the very thing it is trying to conserve.

The thinking is REAL, not decoration. Each stage is an actual model
call whose output feeds the next; the final answer is produced with the
reasoning in context. A "thinking" panel that displays invented
deliberation the model never did would be theatre, and this project has
already thrown out enough fake UI.

Streaming: think_stream() yields events as they happen so the frontend
can render each stage on arrival. Callers that just want the answer use
think_through().
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional

from ..runtime.log import log_event

MODE_OFF = "off"
MODE_ON = "on"
MODE_AUTO = "auto"

# UK's two explicit modes (2026-09-16). 'auto' is retired: it decided
# on the user's behalf how expensive a turn would be, which made cost
# unpredictable from the outside. The legacy constants above remain so
# older callers do not break, but nothing produces 'auto' any more.
MODE_NORMAL = "normal"
MODE_EXTENDED = "extended"

# Stages. Kept few on purpose: each is a model call, and a ten-stage
# pipeline would make every answer slow enough that UK stops using it.
STAGE_UNDERSTAND = "understand"
STAGE_EXPLORE = "explore"
STAGE_CRITIQUE = "critique"
STAGE_ANSWER = "answer"

# Signals that a turn genuinely warrants deliberation.
_HARD_MARKERS = (
    # 'kyunki' must match too -- \bkyun\b alone missed it, and that is
    # the single most common Hinglish marker for "explain the reason".
    r"\bwhy\b|\bkyun|\bkyu\b", r"\bcompare\b|\bvs\b|\bbehtar\b|\bbetter\b",
    # 'redesign' is design work; a left word-boundary excluded it.
    r"design\b|\barchitect", r"\bdebug\b|\bfix\b|\bbug\b|\berror\b",
    r"\btrade.?off\b|\bpros and cons\b|\bfayda.*nuksan\b",
    r"\bplan\b|\bstrategy\b|\bapproach\b", r"\bsamjhao\b|\bexplain\b",
    r"\bkaise\b|\bhow (do|should|would|can)\b", r"\bsahi hai\b|\bshould i\b",
    r"\brefactor\b|\boptimi[sz]e\b|\bimprove\b",
)

_TRIVIAL_MARKERS = (
    r"^\s*(hi|hello|hey|hmm|ok|okay|thanks|thank you|thik|theek|haan|ha|nahi|no|yes)\b",
    r"^\s*(kya haal|kaise ho|what'?s up|good (morning|night|evening))\b",
    r"^\s*/\w+",          # CLI slash command
)


@dataclass
class ThinkingStage:
    name: str
    content: str = ""
    duration_ms: float = 0.0
    ok: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {"stage": self.name, "content": self.content,
                "duration_ms": round(self.duration_ms, 1), "ok": self.ok}


@dataclass
class ThinkingResult:
    used: bool
    mode: str
    reason: str
    stages: List[ThinkingStage] = field(default_factory=list)
    answer: str = ""
    total_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {"thinking_used": self.used, "mode": self.mode, "reason": self.reason,
                "stages": [s.as_dict() for s in self.stages], "answer": self.answer,
                "total_ms": round(self.total_ms, 1)}

    @property
    def visible_thinking(self) -> str:
        return "\n\n".join(f"[{s.name}] {s.content}" for s in self.stages if s.content)


def should_think_harder(user_input: str, information_need: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Structural decision, no LLM call. This is what JARVIS uses in AUTO
    mode to switch deliberation on by itself."""
    text = (user_input or "").strip()
    lowered = text.lower()

    if not text:
        return {"think": False, "reason": "Khali message hai."}

    for pattern in _TRIVIAL_MARKERS:
        if re.search(pattern, lowered):
            return {"think": False, "reason": "Simple/conversational turn hai -- deliberation ki zaroorat nahi."}

    # An explicit ask always wins over heuristics.
    if re.search(r"\bsoch\s?kar\b|\bdhyan se\b|\bthink\b.*\bcarefully\b|\bstep by step\b|\bdetail mein\b", lowered):
        return {"think": True, "reason": "Aapne khud soch kar jawab dene ko kaha."}

    need = (information_need or {}).get("need") or (information_need or {}).get("kind")
    if need in {"world_live", "episodic", "self_state", "rules"}:
        return {"think": False, "reason": f"Yeh '{need}' se seedha aata hai -- sochne se behtar nahi hoga, lookup se hoga."}

    hits = sum(1 for p in _HARD_MARKERS if re.search(p, lowered))
    long_turn = len(text.split()) > 25

    if hits >= 2 or (hits >= 1 and long_turn):
        return {"think": True, "reason": "Multi-part reasoning wala sawaal hai."}
    if long_turn:
        return {"think": True, "reason": "Lamba, multi-part message hai -- todna padega."}
    if hits >= 1:
        return {"think": True, "reason": "Reasoning maangta hai, seedha lookup nahi."}

    return {"think": False, "reason": "Single-step turn hai."}


def resolve_mode(mode: str, user_input: str,
                 information_need: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Turn the user's setting into a decision for THIS turn.

    Two real modes now (2026-09-16): 'normal' answers in one turn,
    'extended' thinks in stages. 'auto' is accepted for backward
    compatibility but is treated as 'normal' -- it no longer runs a
    classifier to decide on the user's behalf, because that made the
    cost of a message unpredictable to the person sending it.
    """
    mode = (mode or MODE_NORMAL).strip().lower()

    if mode in (MODE_EXTENDED, MODE_ON):
        return {"think": True, "mode": MODE_EXTENDED,
                "reason": "Extended Thinking chuni hui hai -- stages mein soch kar."}

    if mode == MODE_AUTO:
        # Legacy value from an older client. Treated as normal rather
        # than silently reviving the classifier.
        return {"think": False, "mode": MODE_NORMAL,
                "reason": "Normal mode (purana 'auto' ab normal hi hai)."}

    return {"think": False, "mode": MODE_NORMAL,
            "reason": "Normal mode -- ek turn mein jawab."}


def _call(generate: Callable, system: str, user: str, max_tokens: int) -> str:
    """Shared model call for every stage below.

    RAW SENTINEL LEAK (found 2026-09-18 from UK's on-device trace: the
    "Understanding request" panel literally displayed
    "[LLM unavailable: cloud providers failed; local fallback is
    disabled]" as if it were JARVIS's own reasoning, and the same
    sentinel reached the user as the final answer text in another
    turn). Root cause: llm_bridge.generate_response() has a NORMAL,
    non-exception return-value sentinel for "no backend usable" (see
    llm_bridge.py's LLM_UNAVAILABLE_PREFIX and brain.py's
    _record_action_response(), which already exists specifically to
    catch this for the main chat pipeline). think_stream() runs as its
    OWN separate pipeline (the Extended Thinking SSE panel) and never
    passed through that chokepoint, so nothing here ever checked for
    the sentinel -- every `except Exception` block below this function
    (there are several, one per stage) existed for exactly this kind
    of failure, but a same-value STRING return doesn't trigger them.
    Raising here, instead of just returning the sentinel string,
    routes every caller through the friendly-fallback handling that
    was already written for this -- it just never fired.
    """
    from ..orchestration.llm_bridge import LLM_UNAVAILABLE_PREFIX
    result = str(generate(
        system_prompt=system, user_input=user,
        max_tokens=max_tokens, level="extended_thinking",
    )).strip()
    if result.startswith(LLM_UNAVAILABLE_PREFIX) or result.startswith("[Model Generation Error") or result.startswith("[Brain Thinking Error:"):
        raise RuntimeError("LLM abhi available nahi hai (provider call fail hua)")
    return result


def think_stream(
    generate: Callable,
    *,
    user_input: str,
    mode: str = MODE_NORMAL,
    context: str = "",
    persona_prompt: str = "",
    information_need: Optional[Dict[str, Any]] = None,
    effort: str = "medium",
) -> Generator[Dict[str, Any], None, None]:
    """Yields events as thinking happens, so the UI can render each stage
    on arrival instead of waiting for the whole run.

    `effort` (2026-09-14, UK's 5-level spec) controls how many of the
    three stages actually run -- see effort_levels.py. "low" runs none
    (thinking is off outright regardless of mode); "medium" runs
    understand only; "high" adds explore; "aggressive"/"deep" run all
    three. This is the SAME dial that sizes task_loop.py's step count,
    so turning effort up gives more reasoning AND more thoroughly
    verified multi-step work, together, not as two settings to align.

    Event shapes:
        {"type": "decision", ...}
        {"type": "stage_start", "stage": "understand"}
        {"type": "stage", "stage": "understand", "content": "...", ...}
        {"type": "answer", "content": "..."}
        {"type": "done", "result": {...}}
    """
    from ..orchestration.effort_levels import profile_for
    effort_profile = profile_for(effort)

    started = time.time()
    decision = resolve_mode(mode, user_input, information_need)
    # Effort can force thinking off (low) even when mode says think --
    # an explicit low-effort choice should not be overridden by auto
    # mode's own judgement.
    if effort_profile.thinking_stages == 0:
        decision = {"think": False, "mode": decision["mode"],
                    "reason": f"Effort={effort_profile.label} -- thinking off by design."}
    yield {"type": "decision", **decision}

    result = ThinkingResult(used=decision["think"], mode=decision["mode"], reason=decision["reason"])

    if not decision["think"]:
        try:
            answer = _call(
                generate,
                persona_prompt or "You are JARVIS, answering UK.",
                f"{context}\n\n{user_input}" if context else user_input,
                1200,
            )
        except Exception as exc:
            answer = f"Jawab generate nahi ho paya: {exc}"
        if not (answer or "").strip():
            answer = "Mujhe is baar koi jawab nahi mila -- kripya dobara try karein ya sawaal thoda alag tarike se poochein."
        result.answer = answer
        result.total_ms = (time.time() - started) * 1000
        yield {"type": "answer", "content": answer}
        yield {"type": "done", "result": result.as_dict()}
        return

    all_stages = [
        (STAGE_UNDERSTAND,
         "You are JARVIS thinking privately before answering UK. State what is actually being asked, "
         "what is ambiguous, and what you would need to know. Be terse -- notes, not prose. "
         "Do NOT answer yet.", 400),
        (STAGE_EXPLORE,
         "Continue thinking privately. Work through the approaches or possibilities, including ones you "
         "will reject. Show the reasoning, not conclusions alone. Do NOT write the final answer yet.", 700),
        (STAGE_CRITIQUE,
         "Now criticise your own reasoning above. What is weak, unsupported, or assumed? What would make "
         "this answer wrong? If you are missing information, say so plainly rather than papering over it. "
         "Still do NOT write the final answer.", 450),
    ]
    # Effort caps how many of the three stages run -- see
    # effort_levels.py's thinking_stages field.
    stages_spec = all_stages[:max(1, effort_profile.thinking_stages)]

    running: List[str] = []
    for name, system, budget in stages_spec:
        yield {"type": "stage_start", "stage": name}
        t0 = time.time()
        stage = ThinkingStage(name=name)
        try:
            prior = "\n\n".join(running)
            stage.content = _call(
                generate, system,
                (f"UK's message: {user_input}\n\n"
                 + (f"Context:\n{context}\n\n" if context else "")
                 + (f"Your thinking so far:\n{prior}\n\n" if prior else "")
                 + "Continue."),
                budget,
            )
        except Exception as exc:
            stage.ok = False
            stage.content = f"(yeh stage fail hua: {exc})"
            log_event("thinking", f"stage {name} failed: {exc}", level="warning")
        stage.duration_ms = (time.time() - t0) * 1000
        result.stages.append(stage)
        if stage.content:
            running.append(f"[{name}] {stage.content}")
        yield {"type": "stage", **stage.as_dict()}

    yield {"type": "stage_start", "stage": STAGE_ANSWER}
    try:
        answer = _call(
            generate,
            (persona_prompt or "You are JARVIS, answering UK.")
            + "\n\nYou have thought this through privately. Now give UK the answer itself -- do not "
              "narrate your reasoning process, do not say 'I thought about it'. If your critique found "
              "a genuine gap, say so honestly in the answer rather than hiding it.",
            (f"UK's message: {user_input}\n\n"
             + (f"Context:\n{context}\n\n" if context else "")
             + f"Your private thinking:\n" + "\n\n".join(running) + "\n\nNow answer."),
            1600,
        )
    except Exception as exc:
        answer = f"Sochne ke baad jawab likhte waqt fail ho gaya: {exc}"

    # EMPTY ANSWER (2026-09-19, UK: a bare "..." bubble with nothing in
    # it, reached via Extended Thinking specifically -- see the same
    # fix in brain.py's _record_action_response() for the main chat
    # pipeline's version of this gap). _call() already raises on the
    # KNOWN "[LLM unavailable: ...]" sentinel (caught above), but a
    # genuinely empty string ("" outright, no sentinel, no exception)
    # was never checked here and reached the user as a literal blank
    # message.
    if not (answer or "").strip():
        answer = "Mujhe is baar koi jawab nahi mila -- kripya dobara try karein ya sawaal thoda alag tarike se poochein."

    result.answer = answer
    result.total_ms = (time.time() - started) * 1000
    yield {"type": "answer", "content": answer}
    yield {"type": "done", "result": result.as_dict()}


def think_through(generate: Callable, *, user_input: str, mode: str = MODE_NORMAL,
                  context: str = "", persona_prompt: str = "",
                  information_need: Optional[Dict[str, Any]] = None,
                  effort: str = "medium") -> Dict[str, Any]:
    """Non-streaming wrapper for the CLI and plain API callers."""
    final: Dict[str, Any] = {}
    for event in think_stream(generate, user_input=user_input, mode=mode, context=context,
                              persona_prompt=persona_prompt, information_need=information_need,
                              effort=effort):
        if event["type"] == "done":
            final = event["result"]
    return final
