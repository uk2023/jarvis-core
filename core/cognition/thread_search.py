"""THREAD-WIDE CONTEXTUAL SEARCH (2026-09-19).

UK's explicit architecture: a user will NEVER give JARVIS a precise
time interval ("is 2-hour window"). They'll just reference something
naturally -- "hum log pehle jo decide kiye the", "jo humne discuss kiya
tha" -- with no timestamp at all. The Conversation Intelligence Layer's
job is to SCAN the entire chat thread (this session's persisted
history, however long -- UK's own words: "chahe das saal pehle bhi
likha ho, JARVIS ko turant catch karna chahiye") and find the relevant
part itself, injecting ONLY that particular context -- never the whole
thread's payload into an LLM call (UK explicit: "main nahi keh raha ki
tum poora payload utha ke LLM ko de do").

An explicit time hint from the user ("2 ghante pehle", "kal subah") is
an ACCELERATION, not a requirement -- narrows the scan when given,
never blocks it when absent.

This module is pure and native (no LLM call, no I/O) so it's fast
enough to run on every turn without adding latency UK would notice --
"latency ekdum perfect honi chahiye". The actual chat history is
fetched by the caller (backend layer, which owns the persisted
chat_messages table) and passed in already-loaded.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Backward-reference markers (2026-09-19) -- native, zero-cost signal
# that the CURRENT message is pointing at something from earlier in
# this thread, in ANY of the ways UK actually writes it (English,
# Devanagari, and the romanized Hindi that's this project's most
# common real input -- see conversation_continuity.py's own hardening
# for why romanized markers matter as much as Devanagari ones).
_BACKWARD_REFERENCE_MARKERS = (
    # English
    "earlier", "before", "we discussed", "we decided", "we talked",
    "you said", "you told me", "last time", "previously", "we said",
    # Devanagari
    "पहले", "हमने कहा", "हमने बोला", "डिसाइड किया", "तय किया",
    # Romanized Hindi
    "pehle", "pahle", "humne kaha", "humne bola", "hum log", "hamne",
    "decide kiya", "decide kiye", "tay kiya", "usne kaha", "usne bola",
    "purani baat", "purana", "wo wala", "us waqt", "uss time",
)

# Very common/low-signal words -- excluded from relevance scoring so
# they don't dominate matches (every message has "the"/"hai"/"kya").
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in",
    "on", "at", "for", "and", "or", "but", "not", "this", "that",
    "hai", "hain", "tha", "the", "ka", "ki", "ke", "ko", "mein", "me",
    "se", "ne", "to", "bhi", "hi", "kya", "kyun", "kyu", "aur", "ya",
    "jarvis", "sir", "please", "kripya",
}


def has_backward_reference(user_input: str) -> bool:
    """Does this message read as pointing at something earlier in the
    thread, with no explicit time given? Deliberately conservative in
    the OTHER direction from most of this project's detectors: a false
    positive here just means an extra (cheap, native, fast) thread scan
    runs and finds nothing useful, which costs a few milliseconds; a
    false negative means a real reference goes unanswered, which is
    the exact failure UK is describing. Errs toward triggering.
    """
    lowered = (user_input or "").lower()
    return any(m in lowered for m in _BACKWARD_REFERENCE_MARKERS)


def extract_time_hint_hours(user_input: str) -> Optional[float]:
    """If the user DID give a rough time interval, extract it as hours
    -- used to narrow the scan (acceleration), never required. Only
    handles the common, unambiguous patterns; anything else falls
    through to a full scan, which is always correct, just not
    accelerated.
    """
    text = (user_input or "").lower()

    # "N ghante/hour(s) pehle/ago"
    m = re.search(r"(\d+)\s*(?:ghante|ghanta|hour|hours|hrs?)\s*(?:pehle|pahle|ago)?", text)
    if m:
        return float(m.group(1))

    # "N din/day(s) pehle/ago"
    m = re.search(r"(\d+)\s*(?:din|day|days)\s*(?:pehle|pahle|ago)?", text)
    if m:
        return float(m.group(1)) * 24

    # Common relative-day words
    if "kal" in text or "yesterday" in text:
        return 24.0
    if "parso" in text:
        return 48.0

    return None


def _significant_tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-zA-Z\u0900-\u097F]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


@dataclass
class ThreadMatch:
    sender: str
    text: str
    timestamp: Optional[float]
    score: int


def search_thread_for_reference(
    query_text: str,
    thread_messages: List[Dict[str, Any]],
    max_results: int = 3,
    time_hint_hours: Optional[float] = None,
    now: Optional[float] = None,
) -> List[ThreadMatch]:
    """The core scan. `thread_messages` is the FULL persisted history
    for THIS ONE chat thread (session_id-scoped, fetched by the
    caller) -- {"sender": "user"|"jarvis", "text": str, "timestamp":
    float} per message, any length, any age. Never mutated, never
    re-fetched here.

    Single pass, O(messages) -- precomputes the query's significant
    tokens ONCE, then scores each message by token overlap. No
    embeddings, no LLM call: this is the zero-cost-when-possible
    native layer this project already uses elsewhere (see
    correction_audit.py's token-overlap clustering for the same
    pattern), chosen specifically so a thread scan never becomes the
    latency UK is worried about.
    """
    if not thread_messages:
        return []

    query_tokens = _significant_tokens(query_text)
    if not query_tokens:
        return []

    candidates = thread_messages
    used_narrowed_window = False
    if time_hint_hours is not None:
        # ACCELERATION, never a requirement (2026-09-19). Narrow to the
        # hinted window first -- but if scoring THAT window yields
        # nothing relevant (the hint was wrong, or approximate, or
        # some unrelated message just happens to sit in that window),
        # fall back to the full thread below rather than reporting
        # nothing found. A wrong hint must never be allowed to mask a
        # real answer sitting outside it.
        reference_now = now if now is not None else time.time()
        cutoff_start = reference_now - (time_hint_hours + 1) * 3600
        cutoff_end = reference_now - max(0.0, time_hint_hours - 1) * 3600
        narrowed = [
            m for m in thread_messages
            if m.get("timestamp") and cutoff_start <= m["timestamp"] <= cutoff_end
        ]
        if narrowed:
            candidates = narrowed
            used_narrowed_window = True

    scored: List[ThreadMatch] = []
    for msg in candidates:
        text = msg.get("text") or ""
        if not text:
            continue
        msg_tokens = _significant_tokens(text)
        overlap = len(query_tokens & msg_tokens)
        if overlap > 0:
            scored.append(ThreadMatch(
                sender=msg.get("sender", "unknown"),
                text=text,
                timestamp=msg.get("timestamp"),
                score=overlap,
            ))

    if not scored and used_narrowed_window:
        # The hint pointed at the wrong window -- fall back to
        # scanning everything rather than reporting nothing found.
        for msg in thread_messages:
            text = msg.get("text") or ""
            if not text:
                continue
            msg_tokens = _significant_tokens(text)
            overlap = len(query_tokens & msg_tokens)
            if overlap > 0:
                scored.append(ThreadMatch(
                    sender=msg.get("sender", "unknown"),
                    text=text,
                    timestamp=msg.get("timestamp"),
                    score=overlap,
                ))

    scored.sort(key=lambda m: (m.score, m.timestamp or 0), reverse=True)
    return scored[:max_results]


def format_thread_matches(matches: List[ThreadMatch]) -> str:
    """Human/LLM-readable rendering of what the scan found -- this is
    the ONLY thing that reaches the response brief, never the raw
    thread_messages list (UK's explicit "poora payload mat do LLM ko").
    """
    if not matches:
        return ""
    lines = []
    for m in sorted(matches, key=lambda x: x.timestamp or 0):
        who = "UK" if m.sender == "user" else "JARVIS"
        lines.append(f"{who}: {m.text}")
    return "\n".join(lines)
