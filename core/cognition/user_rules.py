from __future__ import annotations

"""Native user-rule extraction.

This is the direct answer to "mere rules ko bhi woh likhe": explicit
instructions the user gives JARVIS about how to behave ("hamesha
Hindi mein baat karo", "kabhi emoji use mat karo", "yaad rakhna ki
mujhe UK bulate ho") were being said out loud in chat and then simply
lost -- nothing captured them as durable, always-applied rules. The
LLM route re-derived JARVIS's persona from a hardcoded system prompt
every single turn, with no channel for the user's own stated rules to
ever reach it.

This module is purely symbolic (regex pattern matching against
Hinglish/English imperative phrasing) -- it costs zero LLM calls,
exactly matching the "loose dependency" goal: rule capture must never
depend on the very LLM whose behaviour it's supposed to constrain.

A detected rule is stored as ordinary Knowledge (via
SemanticMemory.remember) under the reserved subject "jarvis_rule", so
it rides on the existing persistence/graph/FAISS machinery rather than
inventing a second storage system. get_active_rules() is the read
side every response-building path (see response_brief.py) calls to
fetch the current rule set for injection.
"""

import re
import time
from dataclasses import dataclass
from typing import Any, List, Optional

RULE_SUBJECT = "jarvis_rule"

# Hindi emphasis/discourse particles that commonly attach to the
# PRECEDING word and carry no referential content of their own --
# "X hi" means "only/exactly X", not "a thing called 'X hi'". This is
# the actual bug a real user hit: "mujhe UK hi bulana" ("call me just
# UK") got stored as the literal rule value "UK hi" instead of "UK",
# and every later reply then addressed them as "UK hi" -- correctly
# obeying a rule that was wrong at the moment it was captured. This
# strips trailing particles from a captured span; it does not attempt
# to model Hindi grammar generally, just this specific, common,
# value-corrupting case.
_TRAILING_PARTICLES = re.compile(r"\s+(?:hi|bhi|to|hii|bas|bs)\s*$", re.I)
_LEADING_PARTICLES = re.compile(r"^\s*(?:bas|bs)\s+", re.I)


def _clean_captured_value(text: str) -> str:
    text = text.strip(" .,!?\"'")
    text = _LEADING_PARTICLES.sub("", text)
    text = _TRAILING_PARTICLES.sub("", text).strip(" .,!?\"'")
    return text


# Each entry: (pattern, forced_polarity). forced_polarity is
# "affirmative"/"negative" when the pattern's own shape already
# determines it unambiguously, or None to fall back to scanning the
# matched text for mat/nahi/never (works for the original hamesha/
# kabhi/yaad-rakhna patterns, but NOT for the correction patterns
# below -- those legitimately contain "nahi" while asserting an
# AFFIRMATIVE final value, so text-scanning them would get polarity
# backwards).
_RULE_PATTERNS = [
    # "hamesha X karo/karna/rakho" -- affirmative standing instruction
    (re.compile(r"\bhamesha\s+(.+?)(?:\s+kar(?:o|na|na hai)|\s+rakh(?:o|na))\b", re.I), None),
    (re.compile(r"\balways\s+(.+?)(?:\.|$|,)", re.I), None),
    # "kabhi X mat/nahi karo" -- negative standing instruction
    (re.compile(r"\bkabhi\s+(?:bhi\s+)?(.+?)\s+(?:mat|nahi)\s+kar(?:o|na)\b", re.I), None),
    (re.compile(r"\bnever\s+(.+?)(?:\.|$|,)", re.I), None),
    # "yaad rakhna (ki) X" -- explicit "remember this" framing
    (re.compile(r"\byaad\s+rakh(?:na|ना)\s+(?:ki\s+)?(.+?)(?:\.|$|,)", re.I), None),
    (re.compile(r"\bremember\s+(?:that\s+)?(.+?)(?:\.|$|,)", re.I), None),
    # CORRECTION patterns -- these did not exist before, at all. A user
    # who noticed a wrong rule ("mera naam UK hi nahi, sirf UK hai" /
    # "UK hi nahi, sirf UK bolo") had NO way to fix it through
    # conversation -- the wrong value just stayed wrong forever, which
    # is exactly the bug being fixed here. These route through the
    # SAME (jarvis_rule, affirmative) predicate as "mujhe X bulao"
    # below, so SemanticMemory.remember()'s contradiction handling
    # (see Phase 2) naturally UPDATES the existing rule -- the old
    # wrong value moves to history instead of being duplicated.
    # Forced "affirmative": the captured group is the CORRECTED value
    # being asserted, even though the sentence also contains "nahi".
    # "bas"/"bs" (a very common Hindi filler for "just/only" -- "bas
    # UK bulao" = "just call [me] UK") is included alongside sirf/
    # only/onnly; a real user's actual phrasing ("nahu bas UK bulao")
    # was missing this and got the literal filler word "bas"/"bs"
    # stored as part of the value ("bs UK" instead of "UK").
    (re.compile(r"\bnahi,?\s+(?:only|onnly|sirf|bas|bs)\s+(.+?)\s+(?:hai|bolo|bulao|kaho|pukaro)\b", re.I), "affirmative"),
    (re.compile(r"\b(?:sirf|only|onnly|bas|bs)\s+(.+?)\s+(?:bolo|bulao|kaho|pukaro)\b", re.I), "affirmative"),
    # "change X from Y to Z" / "X ko Y se Z kar do" -- explicit
    # change-request phrasing, distinct from the negation-style
    # corrections above. Captures ONLY the new value (Z), which is
    # what should actually be stored.
    (re.compile(r"\bchange\s+.+?\s+from\s+.+?\s+to\s+[\"']?(.+?)[\"']?[.\s]*$", re.I), "affirmative"),
    (re.compile(r"\b(?:ise|isko|usse|usko)\s+.+?\s+se\s+(.+?)\s+kar\s*(?:do|dena)\b", re.I), "affirmative"),
    # "mujhe X bulao/pukaro" -- naming/addressing preference
    (re.compile(r"\bmujhe\s+(.+?)\s+bul(?:ao|ana)\b", re.I), None),
]

# Sentences that are just meta-commentary about rules, not new ones --
# skip these so e.g. JARVIS repeating a rule back doesn't re-store it.
_SKIP_IF_CONTAINS = re.compile(r"\b(kya rule|which rule|list rules|show rules|my rules)\b", re.I)


@dataclass
class ExtractedRule:
    text: str
    polarity: str  # "affirmative" | "negative"
    raw_match: str
    confidence: float


def extract_rules(user_input: str) -> List[ExtractedRule]:
    """Pure function: text in, candidate rules out. No I/O, no LLM."""
    text = (user_input or "").strip()
    if not text or _SKIP_IF_CONTAINS.search(text):
        return []

    found: List[ExtractedRule] = []
    for pattern, forced_polarity in _RULE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        body = _clean_captured_value(match.group(1))
        if len(body) < 2 or len(body) > 200:
            continue
        if forced_polarity is not None:
            polarity = forced_polarity
        else:
            polarity = "negative" if re.search(r"\b(mat|nahi|never)\b", match.group(0), re.I) else "affirmative"
        found.append(ExtractedRule(text=body, polarity=polarity, raw_match=match.group(0), confidence=0.85))
        break  # one rule per message keeps this conservative -- avoid over-triggering on casual chat
    return found


class UserRuleStore:
    """Thin persistence + retrieval wrapper around SemanticMemory for
    the reserved `jarvis_rule` subject. Brain owns one instance and
    calls capture_from_message() every turn (cheap regex check) plus
    get_active_rules() whenever it builds a response brief."""

    def __init__(self, semantic_memory: Any):
        self.memory = semantic_memory

    def capture_from_message(self, user_input: str) -> List[ExtractedRule]:
        if self.memory is None:
            return []
        candidates = extract_rules(user_input)
        stored: List[ExtractedRule] = []
        for rule in candidates:
            try:
                # GENERALIZATION (2026-09-11 roadmap Phase 8): before
                # creating a brand-new rule row, check whether an
                # EXISTING rule of the same polarity is semantically
                # near-identical (e.g. "polite raho" vs "respectful
                # baat karo") -- textually different but the same
                # underlying instruction. Reuses the SAME embedder +
                # cosine-similarity approach SemanticMemory.remember()
                # already uses for multi-value predicate dedup (Bug
                # #10), rather than inventing a second mechanism.
                # Without this, restating a rule in different words
                # kept accumulating near-duplicate rows forever instead
                # of reinforcing one.
                matched_id = self._find_similar_existing(rule.text, rule.polarity)
                if matched_id is not None:
                    self.memory.reinforce(matched_id, confidence_delta=0.05)
                    stored.append(rule)
                    continue
                self.memory.remember(
                    subject=RULE_SUBJECT,
                    predicate=rule.polarity,
                    value=rule.text,
                    confidence=rule.confidence,
                    importance=0.9,  # rules should survive pruning ahead of casual chat facts
                    source="user_stated_rule",
                    tags=["rule", rule.polarity],
                    # UK stated this directly -- highest natural trust
                    # for a rule short of him explicitly confirming a
                    # JARVIS-proposed one (see Brain.confirm_self_rule).
                    source_type="user_stated",
                )
                stored.append(rule)
            except Exception:
                continue
        return stored

    def _find_similar_existing(self, text: str, polarity: str, threshold: float = 0.80) -> Optional[str]:
        """Returns the knowledge_id of an existing SAME-polarity rule
        whose embedding cosine-similarity to `text` is >= threshold,
        or None. Degrades silently (returns None, falls through to
        normal create-a-new-row behavior) if the embedder or existing
        rules aren't available -- this is a pure optimization, never
        a hard requirement."""
        embedder = getattr(self.memory, "embedder", None)
        if embedder is None:
            return None
        try:
            existing = self.memory.find(subject=RULE_SUBJECT, predicate=polarity) or []
        except Exception:
            return None
        if not existing:
            return None
        try:
            import numpy as np
            new_vec = embedder.encode(text)
            best_id, best_score = None, 0.0
            for item in existing:
                other_text = str(getattr(item, "value", "") or "")
                if not other_text:
                    continue
                other_vec = embedder.encode(other_text)
                denom = (np.linalg.norm(new_vec) * np.linalg.norm(other_vec))
                score = float(np.dot(new_vec, other_vec) / denom) if denom > 0 else 0.0
                if score >= threshold and score > best_score:
                    best_id, best_score = getattr(item, "knowledge_id", None), score
            return best_id
        except Exception:
            return None

    def get_active_rules(self, limit: int = 20) -> List[str]:
        """Formatted, ready-to-inject rule strings, newest first."""
        if self.memory is None:
            return []
        try:
            items = self.memory.find(subject=RULE_SUBJECT)
        except Exception:
            return []
        items = sorted(items, key=lambda k: getattr(k, "updated_at", 0), reverse=True)[:limit]
        formatted = []
        for item in items:
            polarity = getattr(item, "predicate", "affirmative")
            verb = "Always" if polarity == "affirmative" else "Never"
            formatted.append(f"{verb} {item.value}")
        return formatted
