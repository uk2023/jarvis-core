from __future__ import annotations

"""ONE DIAL: EFFORT LEVEL DRIVES BOTH THINKING AND STEP-TURN TASKS.

UK, in order:
    1. "Claude ki tarah thinking aur step turns wala chat box mein
        feature banaya tha use integrate kar do -- extended thinking on
        hone se multi-turn step-turn sab hi honi chahiye."
    2. "Effort 5 level: low, medium, high, aggressive, deep -- 5 level
        reasoning/accuracy/step-turn-count aur speed se alag honge, top
        to low hierarchy mein jahan deep mein sab explicit tareeke se
        rahega, aur low mein sabse kam."

Both requests point at the same underlying problem: thinking.py (the
staged reasoner) and task_loop.py (the plan/act/verify agentic loop)
were two SEPARATE features a person had to pick between, and neither
had a notion of "how hard should JARVIS try". This module is the
missing layer: ONE effort setting that configures both, so turning on
"extended thinking" and getting a multi-step completed task are the
same dial, not two things to remember to enable.

THE FIVE LEVELS
================
Ordered low -> deep exactly as UK specified. Each level sets:

  thinking_stages     how many reasoning stages run before answering
                       (understand/explore/critique -- see thinking.py)
  max_task_steps       cap on task_loop.py's plan length
  verify_retries       how many times a failed verify gets one more
                        attempt before task_loop reports honestly
  step_visibility       whether individual steps are shown in full or
                        collapsed to a one-line summary (UK: "deep mein
                        sab explicit tareeke se rahega")

Deep is not simply "more of everything" turned up -- it is what the
name says: thorough verification, retries, full step visibility. Low is
a single pass with no retry and no visible step breakdown, because at
that level the cost of showing machinery outweighs what it tells UK.

WHY SPEED IS THE TRADE, NOT A SEPARATE KNOB
============================================
UK asked for levels that differ "reasoning/accuracy/step-turn-count aur
speed se". Speed here is not a setting -- it falls out of the other
three. More stages and more retries cost more LLM calls, which costs
more wall-clock time. Making speed configurable independently would let
someone ask for "deep" reasoning at "instant" speed, which is not a
real combination -- it would just silently produce shallow reasoning
labelled as deep. So speed is documented per level as an expectation,
not exposed as its own parameter.
"""

from dataclasses import dataclass
from typing import Dict, List

EFFORT_LEVELS_ORDERED = ["low", "medium", "high", "aggressive", "deep"]


@dataclass(frozen=True)
class EffortProfile:
    name: str
    label: str
    thinking_stages: int          # how many of understand/explore/critique run
    max_task_steps: int           # task_loop.py plan cap
    verify_retries: int           # task_loop.py MAX_VERIFY_RETRIES override
    step_visibility: str          # "collapsed" | "summary" | "full"
    min_budget_calls: int         # will not engage below this many remaining LLM calls
    speed_note: str               # what UK should expect, not a setting
    # LLM CALL BUDGET PER LEVEL (2026-09-16, UK's spec: "jo level maine
    # banaya hai -- low/medium/high/aggressive/deep -- usme tum decide
    # karo ki kaam bhi pura ho jaaye aur error bhi na aaye, LLM budget
    # bhi fail na ho").
    #
    # This is the number of LLM calls the TURN may spend once that
    # level is chosen. A single normal turn stays capped separately at
    # 10 (see config/cognition.json max_calls_per_turn) -- these apply
    # only to extended thinking, where one call per step is the honest
    # requirement and the old shared cap of 2 was what killed every
    # task from step 3 onward.
    #
    # CODING WORKER BUDGET -- exact levels (2026-09-17, UK's spec,
    # superseding the earlier unbounded-deep design): Low=20, Medium=35,
    # High=50, Aggressive=65, Deep=80. Deep is now a real 80-call
    # ceiling, not unbounded -- UK's later, more specific instruction
    # explicitly named 80 rather than -1, because an unbounded budget
    # made "budget fail nahi hona chahiye" impossible to guarantee: an
    # unbounded coding task could starve Standard Thinking's separate
    # 8-call budget for the rest of the process if nothing ever capped
    # it. The loop still stops earlier on its own step cap or repeated
    # verify failure when those trigger first.
    #
    # verify_retries=0 EVERYWHERE (2026-09-17, UK: "ye retry mechanism
    # hatao"). A failed verify step used to get one extra attempt at
    # the SAME step before task_loop reported honestly; UK found this
    # added a retry step that mostly just repeated the same failure
    # (see his Doc_Trace trace: RETRY re-hit the identical
    # per-level/token-budget error the WRITE step had just hit). Report
    # the failure immediately instead of spending a call trying again.
    llm_call_budget: int


EFFORT_PROFILES: Dict[str, EffortProfile] = {
    # STEP-COUNT HIERARCHY (2026-09-14, UK's explicit numbers): "low
    # wala bhi turns le sakta hai but uski step limited hongi, like
    # under 20; medium 20-40; phir similarly top-level ka 80-100 turns
    # step count ke hisab se." This is a much larger scale than the
    # original 2-8 range -- these are step/turn counts for a genuinely
    # long-running multi-step task (build a project, not answer a
    # question), and the per-step budget check in task_loop.stream()
    # (_remaining_calls() checked before EVERY step) is what actually
    # stops a "deep" task from running away and eating a turn's whole
    # LLM budget -- the cap here is a ceiling, not a promise that every
    # run reaches it.
    "low": EffortProfile(
        name="low", label="Low",
        thinking_stages=0, max_task_steps=18, verify_retries=0,
        step_visibility="collapsed", min_budget_calls=1,
        speed_note="Sabse tez -- turns le sakta hai (18 tak), verify retry nahi, steps chhupe rehte hain. Coding Worker Budget: 20 calls.",
        llm_call_budget=20,
    ),
    "medium": EffortProfile(
        name="medium", label="Medium",
        thinking_stages=1, max_task_steps=35, verify_retries=0,
        step_visibility="summary", min_budget_calls=2,
        speed_note="20-40 step tak, thodi soch (samajhna). Default. Coding Worker Budget: 35 calls.",
        llm_call_budget=35,
    ),
    "high": EffortProfile(
        name="high", label="High",
        thinking_stages=2, max_task_steps=55, verify_retries=0,
        step_visibility="summary", min_budget_calls=3,
        speed_note="Samajhna + options explore, 55 step tak. Coding Worker Budget: 50 calls.",
        llm_call_budget=50,
    ),
    "aggressive": EffortProfile(
        name="aggressive", label="Aggressive",
        thinking_stages=3, max_task_steps=80, verify_retries=0,
        step_visibility="full", min_budget_calls=4,
        speed_note="Poora thinking cycle, 80 step tak, steps poore dikhte hain. Coding Worker Budget: 65 calls.",
        llm_call_budget=65,
    ),
    "deep": EffortProfile(
        name="deep", label="Deep",
        thinking_stages=3, max_task_steps=100, verify_retries=0,
        step_visibility="full", min_budget_calls=5,
        speed_note="Sabse dheema -- poora thinking, 100 step tak, sab explicit tareeke se dikhta hai. Coding Worker Budget: 80 calls.",
        llm_call_budget=80,
    ),
}


def profile_for(level: str) -> EffortProfile:
    return EFFORT_PROFILES.get((level or "medium").strip().lower(), EFFORT_PROFILES["medium"])


def list_profiles() -> List[Dict]:
    """For the frontend menu -- ordered low to deep, as UK specified."""
    return [
        {
            "name": EFFORT_PROFILES[n].name,
            "label": EFFORT_PROFILES[n].label,
            "thinking_stages": EFFORT_PROFILES[n].thinking_stages,
            "max_task_steps": EFFORT_PROFILES[n].max_task_steps,
            "verify_retries": EFFORT_PROFILES[n].verify_retries,
            "step_visibility": EFFORT_PROFILES[n].step_visibility,
            "speed_note": EFFORT_PROFILES[n].speed_note,
        }
        for n in EFFORT_LEVELS_ORDERED
    ]


def clamp_to_budget(level: str, remaining_calls: int) -> str:
    """If the chosen level costs more than the turn has left, step down
    to the highest level that fits -- rather than starting 'deep' and
    running out of budget mid-task, which is exactly the failure mode
    ("Thought for 26.7s" then a crash) this project has already hit
    once. Never silently upgrades; only ever steps down.
    """
    order = EFFORT_LEVELS_ORDERED
    current = order.index(profile_for(level).name)
    for i in range(current, -1, -1):
        candidate = EFFORT_PROFILES[order[i]]
        if remaining_calls >= candidate.min_budget_calls:
            return candidate.name
    return "low"
