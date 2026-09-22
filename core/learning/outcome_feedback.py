from __future__ import annotations

"""Outcome feedback: native (zero-LLM-cost) detection of a user
correcting JARVIS's previous answer.

Part of 2026-09-11 roadmap Phase 6. Before this, semantic.reinforce()/
.weaken() only ever fired from two narrow places -- NativeReasoner's
direct-recall path (positive-only, "this fact successfully answered a
query") and Brain's idle "search_supporting_evidence" self-corroboration
check (internal consistency, not a real-world outcome). Nothing fired
on a genuine NEGATIVE outcome signal: UK telling JARVIS it was wrong.

This module only detects the correction; core/orchestration/brain.py
is responsible for deciding WHICH facts to weaken (the previous turn's
self.last_turn_fact_ids) and for actually calling weaken().
"""

import re

_CORRECTION_PATTERNS = re.compile(
    r"\b(?:galat|ghalat|wrong|incorrect|bilkul\s+galat|"
    r"sahi\s+nahi(?:\s+hai)?|not\s+correct|not\s+right|"
    r"yeh\s+galat|ye\s+galat|tumne\s+galat|galat\s+bataya|galat\s+bola)\b",
    re.I,
)

# Sentences that are ABOUT correction as a topic/meta-comment, not an
# actual live correction of JARVIS's last answer -- skip these so
# e.g. "tell me what wrong answers look like" doesn't misfire.
_SKIP_IF_CONTAINS = re.compile(r"\b(kya galat|example of wrong|wrong answer kaisa)\b", re.I)


def detect_correction(user_input: str) -> bool:
    """Pure function: does this message read as UK correcting JARVIS's
    immediately preceding answer? Deliberately conservative (a handful
    of common, unambiguous Hinglish/English correction phrases) --
    same discipline as user_rules.py's extraction, since a false
    positive here would incorrectly weaken a genuinely good fact."""
    text = (user_input or "").strip()
    if not text or _SKIP_IF_CONTAINS.search(text):
        return False
    return bool(_CORRECTION_PATTERNS.search(text))
