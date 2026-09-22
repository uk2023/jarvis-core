from __future__ import annotations

"""Post-response reasoning: response -> reasoning -> experience -> learning.

The user specified an 11-question self-reflection cycle JARVIS should
run after every response:

    1.  What did I do, and why?
    2.  What did I expect?
    3.  What actually happened?
    4.  Why did expected and actual differ?
    5.  What new did I learn, or what got confirmed?
    6.  Which capability was needed -- did I have it or was it missing?
    7.  Which strategy worked/failed, and what's the evidence?
    8.  Should I change my strategy? Why?
    9.  How reliable is this evidence?
    10. What will I do differently next time?
    11. Is this worth adopting into future behavior?

This module answers all 11 STRUCTURALLY, from data the existing
Experience -> LearningCoordinator -> SelfEvaluator pipeline already
computed for every turn (see Brain.process_experience) -- not by
making a fresh LLM call to "reason about it". That would directly
contradict the same cost-awareness goal this whole reasoning cycle is
supposed to serve: reflecting on a turn must not cost more API calls
than the turn itself did.

build_reasoning_trace(...) is called once per experience, from
Brain.process_experience(), and its result is attached to that
result dict under "reasoning" plus appended to a bounded in-memory
log Brain keeps (self.last_reasoning_traces) -- so /runtime_inspect,
monitor.py, or a future API endpoint can show *why* JARVIS believes
what it believes about its own last few turns, not just a bare score.
"""

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReasoningTrace:
    what_and_why: str
    expected_outcome: str
    actual_outcome: str
    outcome_gap_reason: str
    new_learning: str
    capability_check: str
    strategy_evidence: str
    should_change_strategy: bool
    change_reason: str
    evidence_reliability: str
    next_time_different: str
    adopt_as_learning: bool
    mode: str = "unknown"
    llm_cost: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _mode_and_decision_summary(context: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    route = context.get("route") if isinstance(context.get("route"), dict) else {}
    mode = action.get("mode") or route.get("mode") or "unknown"
    reason = route.get("reason") or ""
    confidence = route.get("confidence")
    return {"mode": mode, "reason": reason, "confidence": confidence}


def _retry_cost_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    """Did THIS turn spend an extra ("retry") LLM call anywhere, and did
    it pay off? This is the direct answer to "JARVIS ko apne LLM-call
    kharche ki value khud pata honi chahiye" -- previously the 11-
    question reasoning cycle had no visibility into whether perception's
    or semantic understanding's reinforced-retry stage (core/contracts/
    extraction.py; blueprint_brain.py's semantic fallback) had even
    fired, so it could never reason about whether that extra cost was
    worth it. Reads the same provenance.source tags those cascades
    already stamp on their output -- no new instrumentation needed,
    just actually looking at what was already there.
    """
    perception = context.get("perception") or {}
    perception_source = str(perception.get("source", ""))
    perception_retried = perception_source == "llm_refined"
    # Whether perception's OWN attempt (retried or not) ended up
    # exhausted -- judged on perception alone, not entangled with
    # semantic understanding's separate, independent outcome.
    perception_ended_degraded = perception_source == "safe_fallback"

    semantic = perception.get("semantic_understanding") or {}
    semantic_source = str((semantic.get("provenance") or {}).get("source", ""))
    semantic_retried = semantic_source == "llm_fallback_refined"
    semantic_ended_degraded = bool((semantic.get("provenance") or {}).get("degraded", False))

    retry_used = perception_retried or semantic_retried
    # "Paid off" is judged ONLY against whichever layer(s) actually
    # spent a retry -- semantic understanding's retry succeeding is a
    # real win even if perception separately gave up on a DIFFERENT
    # attempt (or never needed a retry at all); conflating the two
    # would wrongly call a genuinely successful retry "wasted" just
    # because an unrelated layer had its own problems this turn.
    paid_off_checks = []
    if perception_retried:
        paid_off_checks.append(not perception_ended_degraded)
    if semantic_retried:
        paid_off_checks.append(not semantic_ended_degraded)
    retry_paid_off = bool(paid_off_checks) and all(paid_off_checks)
    return {
        "retry_used": retry_used,
        "retry_paid_off": retry_paid_off,
        "perception_retried": perception_retried,
        "semantic_retried": semantic_retried,
        "ended_degraded": perception_ended_degraded or semantic_ended_degraded,
    }


def build_reasoning_trace(
    experience: Dict[str, Any],
    evaluation: Optional[Dict[str, Any]],
    accepted: bool,
    recent_traces: Optional[list] = None,
) -> ReasoningTrace:
    context = experience.get("context") or {}
    action = experience.get("action") or {}
    outcome = experience.get("outcome") or {}
    evaluation = evaluation or {}

    decision = _mode_and_decision_summary(context, action)
    mode = decision["mode"]
    confidence = decision["confidence"]
    status = outcome.get("status", "unknown")
    success = bool(evaluation.get("success", status in ("completed", "planned")))
    score = evaluation.get("score")
    retry_cost = _retry_cost_summary(context)
    errors: List[str] = list(evaluation.get("errors") or [])
    strengths: List[str] = list(evaluation.get("strengths") or [])

    # 1. What did I do, and why?
    skill = action.get("skill")
    if skill:
        what_and_why = f"Used the '{skill}' native capability because the router matched it directly: {decision['reason'] or 'high-confidence capability match'}."
    elif mode == "llm":
        what_and_why = f"Routed to language generation (LLM) because: {decision['reason'] or 'no native capability could cover this turn'}."
    else:
        what_and_why = f"Took the '{mode}' route: {decision['reason'] or 'router decision'}."
    if retry_cost["retry_used"]:
        what_and_why += (
            f" This turn also spent an EXTRA LLM call on a reinforced retry "
            f"({'perception' if retry_cost['perception_retried'] else ''}"
            f"{' + ' if retry_cost['perception_retried'] and retry_cost['semantic_retried'] else ''}"
            f"{'semantic understanding' if retry_cost['semantic_retried'] else ''}) "
            f"-- {'which paid off' if retry_cost['retry_paid_off'] else 'which did NOT rescue the turn'}."
        )

    # 2. What did I expect?
    if isinstance(confidence, (int, float)):
        expected_outcome = f"Expected a {'successful' if confidence >= 0.6 else 'uncertain'} outcome (router confidence {confidence:.2f})."
    else:
        expected_outcome = "No explicit confidence was available for this route; treated the outcome as uncertain going in."

    # 3. What actually happened?
    actual_outcome = f"status={status}, success={success}" + (f", score={score:.2f}" if isinstance(score, (int, float)) else "")

    # 4. Why did expected and actual differ?
    if not isinstance(confidence, (int, float)):
        outcome_gap_reason = "No explicit confidence was set going in, so there is no expectation to compare against -- outcome stands on its own."
    else:
        expected_success = confidence >= 0.6
        if expected_success == success:
            outcome_gap_reason = "No significant gap -- outcome matched the confidence going into this turn."
        elif errors:
            outcome_gap_reason = f"Outcome diverged from expectation. Evidence: {'; '.join(errors[:3])}"
        else:
            outcome_gap_reason = "Outcome diverged from expectation, but no specific error signal was captured to explain why."

    # 5. What new did I learn, or what got confirmed?
    if accepted:
        new_learning = "A new fact was extracted and accepted into permanent knowledge from this turn."
    elif success:
        new_learning = "No new fact was stored, but the current strategy for this kind of turn was reconfirmed as working."
    else:
        new_learning = "No new fact was stored; this turn is evidence the current strategy needs attention (see strategy_evidence)."

    # 6. Which capability was needed -- had it or missing?
    if mode == "native" and status == "no_capability":
        capability_check = f"Needed native capability '{skill or '(unspecified)'}' -- MISSING. Fell back to a degraded response."
    elif mode == "native" and skill:
        capability_check = f"Needed native capability '{skill}' -- PRESENT and used directly."
    elif mode == "llm":
        capability_check = "Needed language phrasing/generation -- covered by the LLM organ (not a native gap)."
    else:
        capability_check = f"Capability requirement for mode '{mode}' was not explicitly tracked this turn."
    if retry_cost["retry_used"] and not retry_cost["retry_paid_off"]:
        capability_check += " The reinforced-retry capability was ALSO invoked and still could not recover a usable result -- native extraction has a real gap here, not just a one-off model hiccup."

    # 7. Which strategy worked/failed, and what's the evidence?
    if strengths and not errors:
        strategy_evidence = f"'{mode}' route succeeded. Evidence: {'; '.join(strengths[:3])}"
    elif errors and not strengths:
        strategy_evidence = f"'{mode}' route failed. Evidence: {'; '.join(errors[:3])}"
    elif errors and strengths:
        strategy_evidence = f"'{mode}' route had mixed evidence -- succeeded on: {'; '.join(strengths[:2])}; failed on: {'; '.join(errors[:2])}"
    else:
        strategy_evidence = f"'{mode}' route completed with no specific strength/error evidence recorded."
    if retry_cost["retry_used"]:
        strategy_evidence += (
            f" [LLM cost note: this turn's reinforced retry "
            f"{'was worth its extra call' if retry_cost['retry_paid_off'] else 'was NOT worth its extra call -- spent budget for a still-degraded result'}.]"
        )

    # 8. Should I change strategy? Why?
    should_change_strategy = (isinstance(score, (int, float)) and score < 0.5) or (retry_cost["retry_used"] and not retry_cost["retry_paid_off"])
    if isinstance(score, (int, float)) and score < 0.5:
        change_reason = f"Score {score:.2f} is below the 0.5 confidence-worth-repeating threshold; this route/strategy underperformed for this kind of input."
    elif retry_cost["retry_used"] and not retry_cost["retry_paid_off"]:
        change_reason = "The reinforced retry cost an extra LLM call and still didn't produce a usable result for this kind of input -- worth flagging as a candidate for a native resolver instead of continuing to pay for a retry that isn't paying off."
    else:
        change_reason = "Current strategy performed adequately; no change indicated by this single turn."

    # 9. How reliable is this evidence?
    # Single-turn evidence is deliberately never called "high reliability"
    # -- that would overclaim from one data point. Real reliability only
    # comes from aggregation (see LearningCoordinator.consolidate()),
    # which this module does not have visibility into per-turn.
    evidence_reliability = (
        "Low -- based on a single observed turn, not aggregated evidence across repeated turns of this kind."
    )

    # 10. What will I do differently next time?
    if should_change_strategy and "LLM call budget exceeded" in " ".join(errors):
        next_time_different = "Prefer the native direct-answer/rule-based paths more aggressively before spending LLM budget on this kind of input."
    elif should_change_strategy:
        next_time_different = f"Reconsider routing this kind of input to '{mode}' -- try an alternative route or gather more context before committing to it."
    else:
        next_time_different = "No change planned; continue routing this kind of input the same way."

    # 11. Is this worth adopting into future behavior?
    # PREVIOUSLY HARDCODED FALSE, ALWAYS -- a placeholder comment said
    # "consolidation across many traces should flip this to True" but
    # nothing ever did that consolidation or read this field anywhere.
    # This is the actual fix: recent_traces (Brain.last_reasoning_traces,
    # passed in by the caller) IS the aggregation -- if this same
    # "next_time_different" recommendation has already been flagged as
    # should_change_strategy across enough recent turns, that is real,
    # repeated evidence (not a single low-reliability data point), so
    # adoption becomes genuinely warranted.
    adopt_as_learning = False
    if should_change_strategy and recent_traces:
        matching = sum(
            1 for t in recent_traces[-20:]
            if isinstance(t, dict) and t.get("should_change_strategy") and t.get("next_time_different") == next_time_different
        )
        if matching >= 2:  # this occurrence plus >=2 prior = 3+ total
            adopt_as_learning = True

    return ReasoningTrace(
        what_and_why=what_and_why,
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome,
        outcome_gap_reason=outcome_gap_reason,
        new_learning=new_learning,
        capability_check=capability_check,
        strategy_evidence=strategy_evidence,
        should_change_strategy=should_change_strategy,
        change_reason=change_reason,
        evidence_reliability=evidence_reliability,
        next_time_different=next_time_different,
        adopt_as_learning=adopt_as_learning,
        mode=mode,
        llm_cost=retry_cost,
    )
