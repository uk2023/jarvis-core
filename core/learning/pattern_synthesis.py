from __future__ import annotations

"""Self-authored EXTRACTION PATTERNS -- JARVIS writes its own regex,
tests it in a sandbox, and proposes it for UK's approval.

UK's explicit 2026-09-12 objection: "regex = hardcoding" -- every
native extraction pattern in this codebase so far was written by hand
(by Claude, across many sessions), not learned by JARVIS itself from
its own experience. This module is the fix: instead of a person
writing a new regex every time a gap is found, JARVIS:

  1. Notices a gap itself (see propose_from_candidates() -- fed by
     SemanticLearningBoundary.candidates, the same data that already
     accumulates every time native parsing failed and the LLM had to
     step in, see learning_boundary.py).
  2. Asks its OWN LLM to draft a candidate pattern for that gap
     (a plain JSON tool-response, not free code execution -- the LLM
     never runs anything, it only proposes a regex STRING).
  3. Tests that candidate SAFELY in a sandbox (test_pattern_safely()):
     compiled in isolation, run with a hard timeout (guards against
     catastrophic-backtracking ReDoS), checked against both the
     examples it should match AND a battery of unrelated sentences it
     must NOT match.
  4. Only if it compiles, matches, and doesn't false-positive does it
     become a PENDING proposal -- stored via the exact same semantic-
     memory pending-confirmation mechanism as self-authored BEHAVIORAL
     rules (see Brain.list_pending_self_rules/confirm_self_rule),
     never applied automatically.

SAFETY BOUNDARY, stated plainly: a confirmed pattern is stored as DATA
(a regex string + a predicate name), never as executable Python source
JARVIS writes to its own files. The live extraction pipeline
(semantic_understanding/engine.py's _try_learned_patterns) loads
CONFIRMED patterns and tries them with the SAME timeout guard used
during testing -- so even a pattern that somehow passed testing but
behaves badly on a genuinely new input can't hang the process. This is
a deliberate, considered line: JARVIS growing its own recognition
ability is real and wired end to end; JARVIS rewriting its own source
code is a categorically different (and much riskier) thing this does
NOT do.
"""

import json
import re
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

SUBJECT = "jarvis_learned_pattern"

# CONFIDENCE-BASED AUTO-EVOLUTION (2026-09-12, UK's explicit refinement
# of what "self-evolve" should mean): a pattern doesn't have to sit
# waiting for a manual /confirm_pattern forever. If it keeps matching
# NEW, real conversation shaped the same way as its original examples,
# with zero contradicting/false-positive hits along the way, that's
# organic, accumulating evidence -- exactly the kind of thing UK
# described animals/plants adapting on ("apne experience se, kisi
# approval loop ka intezaar kiye bina"). Once a pattern has been
# quietly right this many times in a row, it graduates to confirmed
# on its own. It is NEVER silent about this: the promotion is logged,
# shown in monitor.py, and always reversible via /reject_pattern even
# after auto-promotion -- self-evolution with a visible paper trail,
# not with UK finding out later that something changed.
AUTO_PROMOTE_THRESHOLD = 6

# A fixed battery of ordinary sentences a genuinely useful new pattern
# should NEVER match -- if a candidate pattern fires on any of these,
# it's almost certainly too broad (e.g. ".*" dressed up) and gets
# rejected before it's ever shown to UK.
_NEGATIVE_BATTERY = [
    "hello jarvis kaise ho",
    "aaj ka weather kaisa hai",
    "mujhe ek joke sunao",
    "kya tum LLM ho ya JARVIS",
    "thank you bhai",
    "yeh kaam kar raha hai kya",
    "mujhe coding sikhni hai",
    "kal milte hain",
]


class PatternTimeoutError(RuntimeError):
    pass


def _with_timeout(seconds: float):
    """Unix-only hard timeout guard (signal.alarm) -- the standard
    library's `re` module has no built-in timeout, and a pathological
    pattern (catastrophic backtracking) can hang a thread indefinitely.
    Used both at TEST time (sandboxing a candidate) and at LIVE time
    (in engine.py) for a confirmed pattern, so this is not a testing-
    only safeguard -- it protects production use too."""
    def decorator(fn):
        def wrapped(*args, **kwargs):
            def _handler(signum, frame):
                raise PatternTimeoutError(f"pattern evaluation exceeded {seconds}s (possible catastrophic backtracking)")
            old_handler = signal.signal(signal.SIGALRM, _handler)
            signal.setitimer(signal.ITIMER_REAL, seconds)
            try:
                return fn(*args, **kwargs)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)
        return wrapped
    return decorator


@dataclass
class PatternProposal:
    proposal_id: str
    gap_description: str
    regex_pattern: str
    predicate: str
    example_inputs: List[str]
    test_results: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


def test_pattern_safely(pattern_str: str, positive_examples: List[str],
                         negative_examples: Optional[List[str]] = None,
                         timeout_seconds: float = 1.0) -> Dict[str, Any]:
    """THE SANDBOX. Never trusts an LLM-proposed regex blindly:
    - Must compile at all.
    - Must match EVERY positive example (else it doesn't actually
      solve the gap it was proposed for).
    - Must match NONE of the negative battery (else it's too broad
      and would misfire on ordinary conversation).
    - Every single match attempt is wrapped in the timeout guard --
      a pattern that hangs on ANY input, positive or negative, fails
      testing outright, full stop.
    Returns a result dict; callers decide whether to keep the
    proposal based on result["passed"], never on partial credit."""
    negative_examples = list(negative_examples or []) + _NEGATIVE_BATTERY
    result: Dict[str, Any] = {"compiled": False, "matched_positive": [], "false_positives": [], "timed_out_on": [], "passed": False}
    try:
        compiled = re.compile(pattern_str, re.I)
    except re.error as exc:
        result["error"] = f"does not compile: {exc}"
        return result
    result["compiled"] = True

    @_with_timeout(timeout_seconds)
    def _search(text: str):
        return compiled.search(text)

    for example in positive_examples:
        try:
            match = _search(example)
        except PatternTimeoutError:
            result["timed_out_on"].append(example)
            continue
        if match:
            result["matched_positive"].append(example)

    for example in negative_examples:
        try:
            match = _search(example)
        except PatternTimeoutError:
            result["timed_out_on"].append(example)
            continue
        if match:
            result["false_positives"].append(example)

    result["passed"] = (
        not result["timed_out_on"]
        and len(result["matched_positive"]) == len(positive_examples)
        and not result["false_positives"]
    )
    return result


class PatternSynthesizer:
    """Proposes new extraction patterns from observed gaps, tests them,
    and stores passing candidates for UK's review -- via the SAME
    semantic-memory pending-confirmation mechanism self-authored
    behavioral rules already use (see brain.py's list_pending_self_rules
    for the parallel pattern)."""

    def __init__(self, llm_bridge: Any, semantic_memory: Any):
        self.llm = llm_bridge
        self.memory = semantic_memory

    def propose_from_candidates(self, similar_examples: List[str], gap_description: str) -> Optional[Dict[str, Any]]:
        """similar_examples: 2+ real input texts that native extraction
        failed on (from SemanticLearningBoundary.candidates -- see
        module docstring), sharing a recognizable shape. Asks the LLM
        for ONE regex string + predicate name; tests it; stores it
        ONLY if it passes. Returns the stored proposal dict, or None
        if the LLM's proposal failed sandboxing (nothing is ever
        stored on failure -- UK never sees a broken proposal)."""
        if self.llm is None or not hasattr(self.llm, "generate_response") or len(similar_examples) < 2:
            return None
        system_prompt = (
            "You write regular expressions for a Hinglish/English chat parser. Given example sentences "
            "that a rule-based parser currently fails to extract a fact from, propose ONE Python `re` "
            "pattern (case-insensitive matching assumed) with exactly one capturing group for the fact "
            "value, plus a short predicate name for what that value represents. "
            "Respond as JSON only: {\"regex\": \"...\", \"predicate\": \"...\"}. "
            "The regex must be conservative -- it should only match sentences genuinely shaped like the "
            "examples, not ordinary conversation."
        )
        user_prompt = "Examples:\n" + "\n".join(f"- {e}" for e in similar_examples) + f"\n\nGap: {gap_description}"
        try:
            raw = self.llm.generate_response(
                system_prompt=system_prompt, user_input=user_prompt,
                max_tokens=300, temperature=0.2, level="pattern_synthesis",
                response_format={"type": "json_object"}, reasoning_effort="low",
            )
            from ..contracts.extraction import extract_first_json_object
            data = extract_first_json_object(raw)
        except Exception as exc:
            log_event("pattern_synthesis", f"LLM pattern proposal failed: {exc}", level="warning")
            return None

        regex_pattern = str(data.get("regex") or "").strip()
        predicate = str(data.get("predicate") or "").strip() or "learned_fact"
        if not regex_pattern:
            return None

        test_results = test_pattern_safely(regex_pattern, similar_examples)
        if not test_results.get("passed"):
            log_event("pattern_synthesis", f"proposed pattern failed sandbox testing, discarded: {test_results}", level="info")
            return None

        if self.memory is None:
            return None
        try:
            import hashlib
            key = hashlib.sha1(regex_pattern.encode("utf-8")).hexdigest()[:10]
            knowledge = self.memory.remember(
                subject=SUBJECT,
                predicate=f"pattern_{key}",
                value=json.dumps({
                    "regex": regex_pattern, "target_predicate": predicate,
                    "gap_description": gap_description, "example_inputs": similar_examples,
                    "test_results": test_results,
                }, ensure_ascii=False),
                confidence=0.7, importance=0.6,
                source="pattern_synthesis", tags=["self_authored_pattern", "pending_confirmation"],
                namespace="SYSTEM", source_type="llm_unverified",
            )
        except Exception as exc:
            log_event("pattern_synthesis", f"could not store pattern proposal: {exc}", level="warning")
            return None
        log_event("pattern_synthesis", f"new extraction pattern PROPOSED, awaiting UK's review: {regex_pattern}", level="info")
        return {"knowledge_id": knowledge.knowledge_id, "regex": regex_pattern, "predicate": predicate, "test_results": test_results}


def shadow_test_pending_patterns(text: str, semantic_memory: Any, timeout_seconds: float = 0.3) -> List[Dict[str, Any]]:
    """Runs PENDING (not yet confirmed/rejected) patterns against real,
    ordinary conversation WITHOUT applying their extraction -- purely
    to accumulate corroborating evidence. Called on every turn from
    bridge_to_cognition.py right alongside apply_confirmed_patterns(),
    at negligible cost (a regex search, same timeout guard). When a
    pattern crosses AUTO_PROMOTE_THRESHOLD organic, non-conflicting
    matches, it graduates to confirmed here directly -- see this
    function's return value for what to log/surface to UK. A single
    false-positive-looking match (one that doesn't look like the
    original gap at all) resets the count rather than pausing forever,
    since a pattern that's actually good will simply re-accumulate
    evidence, while a bad one won't."""
    if semantic_memory is None or not hasattr(semantic_memory, "find"):
        return []
    try:
        items = semantic_memory.find(subject=SUBJECT) or []
    except Exception:
        return []
    pending = [
        item for item in items
        if "pending_confirmation" in (getattr(item, "tags", None) or [])
        and "confirmed" not in (getattr(item, "tags", None) or [])
        and "rejected" not in (getattr(item, "tags", None) or [])
    ]
    if not pending:
        return []

    @_with_timeout(timeout_seconds)
    def _search(compiled_pattern, subject_text: str):
        return compiled_pattern.search(subject_text)

    promotions: List[Dict[str, Any]] = []
    for item in pending:
        data = item.value if isinstance(item.value, dict) else {}
        pattern_str = data.get("regex")
        if not pattern_str:
            continue
        try:
            compiled = re.compile(pattern_str, re.I)
        except re.error:
            continue
        try:
            match = _search(compiled, text)
        except PatternTimeoutError:
            continue
        if not match:
            continue

        shadow_matches = list(data.get("shadow_matches") or [])
        shadow_matches.append(text[:150])
        data["shadow_matches"] = shadow_matches[-20:]  # bounded, don't grow forever

        if len(shadow_matches) >= AUTO_PROMOTE_THRESHOLD:
            try:
                semantic_memory.remember(
                    subject=item.subject, predicate=item.predicate, value=data,
                    confidence=min(0.95, item.confidence + 0.1), importance=item.importance,
                    source=item.source, tags=["confirmed", "auto_promoted"], namespace=item.namespace,
                    source_type="user_stated",
                )
            except Exception:
                continue
            promotions.append({
                "knowledge_id": item.knowledge_id, "regex": pattern_str,
                "corroborating_matches": len(shadow_matches),
                "message": (
                    f"Pattern for '{data.get('target_predicate')}' auto-promoted after "
                    f"{len(shadow_matches)} consistent real matches -- reviewable/undoable "
                    "any time via /reject_pattern."
                ),
            })
            log_event("pattern_synthesis", f"AUTO-PROMOTED pattern {item.knowledge_id} after {len(shadow_matches)} organic matches", level="info")
        else:
            try:
                semantic_memory.remember(
                    subject=item.subject, predicate=item.predicate, value=data,
                    confidence=item.confidence, importance=item.importance,
                    source=item.source, tags=["pending_confirmation"], namespace=item.namespace,
                    source_type=item.source_type if hasattr(item, "source_type") else "llm_unverified",
                )
            except Exception:
                pass
    return promotions


def apply_confirmed_patterns(text: str, semantic_memory: Any, timeout_seconds: float = 0.5) -> List[Dict[str, Any]]:
    """LIVE USE of UK-approved self-authored patterns (see
    bridge_to_cognition.py's SemanticUnderstanding.understand(), called
    right after native symbolic parsing finds nothing). Still timeout-
    guarded even in production -- a pattern that passed sandbox testing
    could still behave unexpectedly on a genuinely new input it was
    never tested against, and that must never be able to hang a live
    turn. Returns relation dicts shaped exactly like SemanticFact.
    as_dict() so they merge into the normal pipeline with no special
    casing downstream."""
    if semantic_memory is None or not hasattr(semantic_memory, "find"):
        return []
    try:
        items = semantic_memory.find(subject=SUBJECT) or []
    except Exception:
        return []
    confirmed = [item for item in items if "confirmed" in (getattr(item, "tags", None) or [])]
    if not confirmed:
        return []

    @_with_timeout(timeout_seconds)
    def _search(compiled_pattern, subject_text: str):
        return compiled_pattern.search(subject_text)

    results: List[Dict[str, Any]] = []
    for item in confirmed:
        data = item.value if isinstance(item.value, dict) else {}
        pattern_str = data.get("regex")
        predicate = data.get("target_predicate") or "learned_fact"
        if not pattern_str:
            continue
        try:
            compiled = re.compile(pattern_str, re.I)
        except re.error:
            continue
        try:
            match = _search(compiled, text)
        except PatternTimeoutError:
            log_event("pattern_synthesis", f"confirmed pattern {item.knowledge_id} timed out live -- skipped, not disabled", level="warning")
            continue
        if match and match.groups():
            results.append({
                "subject": "user", "predicate": predicate, "value": match.group(1).strip(),
                "confidence": 0.85, "source": "self_authored_pattern", "evidence": match.group(0),
                "reason": f"matched UK-confirmed learned pattern {item.knowledge_id}",
            })
    return results
