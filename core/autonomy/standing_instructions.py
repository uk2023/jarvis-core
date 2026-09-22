from __future__ import annotations

"""Standing (triggered) instructions -- native extraction + storage.

Distinct from core/cognition/user_rules.py's UserRuleStore, which
captures BEHAVIORAL constraints ("hamesha Hindi mein baat karo") that
apply to every response. This module captures TRIGGERED instructions:
"do X when Y happens", where Y is (today) a daily time-of-day trigger.
UK's concrete example (2026-09-11 discussion): "roz subah good morning
bolo" -- a daily ~08:00 trigger with a "speak good morning" action.

This is purely symbolic (regex), zero LLM cost, matching the same
"loose dependency" principle as user_rules.py: instruction capture
must not depend on the LLM whose behaviour it constrains.

Storage: the SAME SemanticMemory the rest of the memory system uses
(no new store), under the reserved subject "jarvis_standing_instruction".
predicate is a short content hash of (time, action) so each distinct
instruction gets its own row (same collision-avoidance fix applied to
self-authored rules in Brain -- see core/orchestration/brain.py).
value is a JSON-encoded {trigger_type, trigger_time, action_type,
action_text, last_fired_date}.

Scheduling: core/autonomy/idle_loop.py's step() calls due_now() once
per idle cycle and pushes anything due through Scheduler.schedule()
-- see core/autonomy/scheduler.py, whose due_tasks() consumer already
existed but previously had no producer anywhere in the codebase
(2026-09-11 roadmap Phase 3 finding). Firing is handled by Brain's
execute_autonomous_step()/_execute_standing_instruction(), which calls
mark_fired() only AFTER a real (attempted) execution -- a crash never
silently marks a reminder as done.
"""

import json
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

SUBJECT = "jarvis_standing_instruction"

_TIME_OF_DAY_DEFAULTS = {
    "subah": "08:00", "morning": "08:00",
    "dopahar": "14:00", "afternoon": "14:00",
    "shaam": "18:00", "sham": "18:00", "evening": "18:00",
    "raat": "21:00", "night": "21:00",
}

_RECURRENCE_MARKER = re.compile(r"\b(?:har\s*roz|roz|daily|every\s*day|har\s*din)\b", re.I)

_EXPLICIT_AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
_EXPLICIT_BAJE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*baje\b", re.I)
# Bare "H:MM" (colon format) is unambiguous on its own -- doesn't need
# "baje"/"pe"/"am"/"pm" after it to mean a time. Found 2026-09-11:
# "roz 6:05 pe ek quotes do" fell through to the low-confidence 09:00
# default because neither _EXPLICIT_BAJE nor the trigger-word stripper
# recognized "pe" (colloquial "at") as a valid time suffix.
_EXPLICIT_HHMM = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_TIME_WORD = re.compile(r"\b(subah|morning|dopahar|afternoon|shaam|sham|evening|raat|night)\b", re.I)

# Action extraction -- what JARVIS should actually do/say. Ordered,
# first match wins (same "one candidate, conservative" discipline as
# user_rules.py -- avoids over-triggering on casual chat that merely
# mentions "daily" in passing).
_ACTION_PATTERNS = [
    re.compile(r"(?:mujhe\s+)?(.+?)\s+bol(?:o|na|\s*do|\s*dena)\b", re.I),
    re.compile(r"remind\s+me\s+to\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"tell\s+me\s+(.+?)(?:\.|$)", re.I),
    re.compile(r"(?:mujhe\s+)?(.+?)\s+kar(?:o|na|\s*do|\s*dena)\b", re.I),
    # THE ACTUAL BUG (found 2026-09-11 from real trace-log evidence):
    # "jarvis roz 6:05 pe ek quotes do" never matched ANY pattern above
    # -- Hindi "do" (give/imperative) standing alone, not attached to
    # "bol"/"kar", was never covered. The system fell through to the
    # LLM with no real capability match, and the LLM hallucinated a
    # completely fake JSON command syntax for UK to type. This
    # standalone-"do"/"de do"/"de dena" pattern is deliberately LAST
    # (lowest priority) since it's the least specific -- a bare "do"
    # is common enough in casual sentences that it should only match
    # after the more specific bol/kar patterns above have had their shot.
    re.compile(r"(?:mujhe\s+)?(.+?)\s+de(?:\s*do|\s*dena)?\b", re.I),
    # Bare Hindi imperative "do" (give) as its own word -- distinct
    # from "de do"/"de dena" above. "ek quotes do" has no "de" stem at
    # all, just "do" alone. Lowest priority of all (English "do" is a
    # very common word), only reached after every more specific
    # pattern above has already failed.
    re.compile(r"(?:mujhe\s+)?(.+?)\s+do\b", re.I),
]

# Stripped BEFORE action extraction so the trigger/time clause itself
# ("roz subah 8 baje") never gets captured as part of the action text.
# A leading vocative ("jarvis," / "jarvis ") is stripped FIRST -- found
# 2026-09-11: "jarvis roz 6:05 pe ek quotes do" never matched at all
# because _LEADING_TRIGGER_WORDS anchors on ^, and "jarvis" coming
# before "roz" meant the anchor never fired, so nothing was stripped.
_LEADING_VOCATIVE = re.compile(r"^\s*(?:jarvis[,:]?\s+|mujhe\s+(?=.*\b(?:roz|daily|har\s*din)\b))+", re.I)
_LEADING_TRIGGER_WORDS = re.compile(
    r"^\s*(?:har\s*roz|roz|daily|every\s*day|har\s*din)\s+"
    r"(?:subah|morning|dopahar|afternoon|shaam|sham|evening|raat|night)?\s*"
    r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|baje|pe|par)?)?\s*",
    re.I,
)


@dataclass
class ExtractedInstruction:
    trigger_time: str  # "HH:MM", 24-hour
    action_text: str
    confidence: float
    raw_match: str


def extract_standing_instruction(user_input: str) -> Optional[ExtractedInstruction]:
    """Pure function: text in, one candidate instruction out (or None).
    Requires BOTH a recurrence marker (roz/daily/...) AND a
    recognizable action clause -- deliberately conservative to keep
    false positives low on ordinary conversation."""
    text = (user_input or "").strip()
    if not text or not _RECURRENCE_MARKER.search(text):
        return None

    # Time resolution priority: explicit am/pm > explicit "N baje" >
    # time-of-day word default > fallback default (flagged lower
    # confidence since nothing in the message actually specified when).
    confidence = 0.75
    m = _EXPLICIT_AMPM.search(text)
    if m:
        hour = int(m.group(1)) % 12
        minute = int(m.group(2) or 0)
        if m.group(3).lower() == "pm":
            hour += 12
        trigger_time = f"{hour:02d}:{minute:02d}"
    else:
        m = _EXPLICIT_BAJE.search(text)
        if m:
            hour = int(m.group(1)) % 24
            minute = int(m.group(2) or 0)
            trigger_time = f"{hour:02d}:{minute:02d}"
        else:
            m = _EXPLICIT_HHMM.search(text)
            if m:
                hour = int(m.group(1)) % 24
                minute = int(m.group(2))
                if minute < 60:
                    trigger_time = f"{hour:02d}:{minute:02d}"
                else:
                    trigger_time = None
            else:
                trigger_time = None
            if trigger_time is None:
                m = _TIME_WORD.search(text)
                if m:
                    trigger_time = _TIME_OF_DAY_DEFAULTS.get(m.group(1).lower(), "09:00")
                else:
                    trigger_time = "09:00"
                    confidence = 0.55

    stripped = _LEADING_TRIGGER_WORDS.sub("", _LEADING_VOCATIVE.sub("", text)).strip()
    action_text = None
    for pattern in _ACTION_PATTERNS:
        match = pattern.search(stripped) or pattern.search(text)
        if match:
            candidate = match.group(1).strip(" .,!?\"'")
            if 2 <= len(candidate) <= 200:
                action_text = candidate
                break
    if not action_text:
        return None

    return ExtractedInstruction(trigger_time=trigger_time, action_text=action_text,
                                 confidence=confidence, raw_match=text)


def _parse_value(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


class StandingInstructionStore:
    """Thin persistence + retrieval wrapper around SemanticMemory for
    the reserved `jarvis_standing_instruction` subject. Brain calls
    capture_from_message() every turn; idle_loop calls due_now() on
    each idle cycle to find instructions that should fire now."""

    def __init__(self, semantic_memory: Any):
        self.memory = semantic_memory

    def capture_from_message(self, user_input: str) -> Optional[ExtractedInstruction]:
        if self.memory is None:
            return None
        candidate = extract_standing_instruction(user_input)
        if candidate is None:
            return None
        # GENERALIZATION (2026-09-11 roadmap Phase 8): same semantic-
        # similarity dedup as UserRuleStore -- "roz subah good morning
        # bolo" vs "har din subah namaste bol dena" should reinforce
        # one instruction, not accumulate near-duplicates.
        matched_id = self._find_similar_existing(candidate.action_text)
        if matched_id is not None:
            try:
                self.memory.reinforce(matched_id, confidence_delta=0.05)
            except Exception:
                pass
            return candidate
        key = hashlib.sha1(
            f"{candidate.trigger_time}:{candidate.action_text}".lower().encode("utf-8")
        ).hexdigest()[:10]
        try:
            self.memory.remember(
                subject=SUBJECT,
                predicate=f"daily_{key}",
                value=json.dumps({
                    "trigger_type": "time_daily",
                    "trigger_time": candidate.trigger_time,
                    "action_type": "speak",
                    "action_text": candidate.action_text,
                    "last_fired_date": None,
                }, ensure_ascii=False),
                confidence=candidate.confidence,
                importance=0.85,
                source="user_stated_instruction",
                tags=["standing_instruction", "time_daily"],
                namespace="SYSTEM",
                # UK said this directly -- same trust level as an
                # explicit behavioral rule (see user_rules.py).
                source_type="user_stated",
            )
        except Exception:
            return None
        return candidate

    def _find_similar_existing(self, action_text: str, threshold: float = 0.80) -> Optional[str]:
        """Returns the knowledge_id of an existing standing instruction
        whose action_text embedding cosine-similarity to the new one
        is >= threshold, or None. Same pattern as UserRuleStore's
        _find_similar_existing() -- degrades silently, pure
        optimization."""
        embedder = getattr(self.memory, "embedder", None)
        if embedder is None:
            return None
        try:
            existing = self.list_active()
        except Exception:
            return None
        if not existing:
            return None
        try:
            import numpy as np
            new_vec = embedder.encode(action_text)
            best_id, best_score = None, 0.0
            for item in existing:
                other_text = str(item.get("action_text") or "")
                if not other_text:
                    continue
                other_vec = embedder.encode(other_text)
                denom = (np.linalg.norm(new_vec) * np.linalg.norm(other_vec))
                score = float(np.dot(new_vec, other_vec) / denom) if denom > 0 else 0.0
                if score >= threshold and score > best_score:
                    best_id, best_score = item.get("knowledge_id"), score
            return best_id
        except Exception:
            return None

    def list_active(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.memory is None:
            return []
        try:
            items = self.memory.find(subject=SUBJECT) or []
        except Exception:
            return []
        items = sorted(items, key=lambda k: getattr(k, "updated_at", 0), reverse=True)[:limit]
        out = []
        for item in items:
            data = _parse_value(item.value)
            out.append({
                "knowledge_id": item.knowledge_id,
                "trigger_time": data.get("trigger_time"),
                "action_text": data.get("action_text"),
                "last_fired_date": data.get("last_fired_date"),
                "confidence": item.confidence,
                "source_type": getattr(item, "source_type", "unknown"),
            })
        return out

    def due_now(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Instructions whose trigger_time has passed today and that
        have not already fired today. Read-only / idempotent -- does
        NOT mutate anything itself. Caller is responsible for calling
        mark_fired() only after actually attempting the action, so a
        failed execution can legitimately retry on the next idle tick
        rather than being silently marked done here."""
        now = now or datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        now_hm = now.strftime("%H:%M")
        due = []
        for item in self.list_active():
            trigger_time = item.get("trigger_time")
            if not trigger_time:
                continue
            if item.get("last_fired_date") == today_str:
                continue
            if now_hm >= trigger_time:
                due.append(item)
        return due

    def mark_fired(self, knowledge_id: str, when: Optional[datetime] = None) -> None:
        if self.memory is None or not knowledge_id:
            return
        when = when or datetime.now()
        try:
            item = self.memory.get(knowledge_id)
            if item is None:
                return
            data = _parse_value(item.value)
            data["last_fired_date"] = when.strftime("%Y-%m-%d")
            self.memory.remember(
                subject=item.subject, predicate=item.predicate,
                value=json.dumps(data, ensure_ascii=False),
                confidence=item.confidence, importance=item.importance,
                source=item.source, namespace=item.namespace,
                source_type=getattr(item, "source_type", "user_stated"),
            )
        except Exception:
            pass

    def remove(self, knowledge_id: str) -> bool:
        if self.memory is None or not hasattr(self.memory, "forget"):
            return False
        try:
            return bool(self.memory.forget(knowledge_id))
        except Exception:
            return False
