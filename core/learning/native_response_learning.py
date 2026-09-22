from __future__ import annotations

"""Native response learning (UK's #5): JARVIS learns to answer some of
its OWN repeated turns without an LLM call, by mining the persistent
trace log (core/runtime/trace_log.py -- UK's #4) for messages it has
already answered the same way, consistently, more than once.

SAFETY DESIGN -- read before changing min_occurrences or the intent
allowlist below:

A learned template is a FROZEN snapshot of a past response. That is
exactly right for "hello jarvis" -> a stable greeting, but exactly
WRONG for "meri girlfriend ka naam kya hai" -- if that fact ever
changes, a cached template would keep repeating the OLD answer
forever, which is a lie by construction, not a bug that shows up
loudly. So mining is restricted to a narrow, explicit allowlist of
intents that are conversationally stable and NOT personal-fact
lookups (greeting/farewell/thanks/status/identity/capabilities).
Anything else -- any fact-shaped question -- is never eligible, no
matter how many times it repeats identically. Direct fact recall
already has its own live, always-current path (NativeReasoner's
direct_recall resolver); this module does not duplicate or shortcut
that path.
"""

import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from ..runtime.trace_log import TraceLog, get_trace_log

# Conversationally stable, NOT fact-dependent. Deliberately narrow --
# see module docstring. Anything not in this set is never mined,
# fail-closed (unknown/missing intent is also excluded).
_SAFE_INTENTS = {
    "greeting", "farewell", "thanks", "status_check",
    "self_identity_query", "capabilities_query", "identity",
}


def _intent_name(perception: Any) -> Optional[str]:
    if not isinstance(perception, dict):
        return None
    basic = perception.get("basic_intent")
    if isinstance(basic, dict) and basic.get("name"):
        return str(basic["name"]).strip().lower()
    intent = perception.get("intent")
    if isinstance(intent, dict) and intent.get("name"):
        return str(intent["name"]).strip().lower()
    source = perception.get("source")
    # The Brain-level identity/self-awareness fast paths (see brain.py's
    # "0. NATIVE DIRECT-ANSWER FAST PATH") don't populate basic_intent/
    # intent at all -- they set perception["source"] to the resolver
    # name instead (e.g. "identity"). Treat that as the intent too.
    if isinstance(source, str) and source in _SAFE_INTENTS:
        return source
    return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


class NativeResponseLearner:
    """Mines the trace log for safe, repeated, consistently-grounded
    turns and promotes them into an exact-match native response cache.
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        trace_log: Optional[TraceLog] = None,
        storage_path: Optional[str] = None,
        event_bus: Any = None,
        min_occurrences: int = 3,
        procedural_memory: Any = None,
    ):
        self.trace_log = trace_log or get_trace_log()
        self.events = event_bus
        self.min_occurrences = max(2, int(min_occurrences))

        # UK's #2 recall/learning/memory proposal: storage is now
        # delegated to the formal ProceduralMemory organ (declarative
        # memory = semantic_memory.py, episodic = episodic_memory.py,
        # procedural = this) instead of a private dict + private JSON
        # file this class used to own directly. `storage_path`, if
        # given, is forwarded so existing callers/tests that pass one
        # keep working unchanged.
        if procedural_memory is not None:
            self.procedural_memory = procedural_memory
        else:
            from ..memory.procedural_memory import ProceduralMemory
            self.procedural_memory = ProceduralMemory(storage_path=storage_path)

        self._lock = threading.RLock()
        self.proposals: Dict[str, Dict[str, Any]] = {}

        self.last_mine_at: Optional[float] = None
        self.last_mine_result: Optional[Dict[str, Any]] = None
        self.run_count = 0

    # =============================================================
    # MINE + AUTO-APPROVE (idle-time entry point)
    # =============================================================

    def mine_candidates(self, lookback_files: int = 7) -> List[Dict[str, Any]]:
        """Group trace-log entries by NORMALIZED INPUT (not exact
        response text -- see fix note below). A candidate is ONLY
        eligible if every occurrence: has a safe/stable intent, was
        status=="completed", and was NOT flagged by the grounding
        check (stayed_within_brief is not False -- None is tolerated
        for pre-fix entries, but an explicit False fails the whole
        group, not just that entry).

        FIX (real production bug, found via UK's actual overnight
        logs): the original version grouped by (normalized_input,
        EXACT response text), which meant "hello jarvis" answered as
        "Hello UK, kya chal raha hai?" one time and "Hello UK, kaise
        ho?" another time counted as TWO DIFFERENT groups, each with
        only 1 occurrence -- never reaching min_occurrences, so
        candidates_found stayed at 0 forever even after a full day of
        genuinely repeated greetings. LLM phrasing naturally varies
        turn to turn even for the same safe/stable-intent input; that
        variation is NOT the kind of staleness risk the module
        docstring warns about (that risk is specifically about FACTS
        changing, not about greeting wording varying). Now groups by
        input only, and picks the most frequent exact response text
        within that group as the template (ties broken by most
        recent) -- still 100% exact-match at LOOKUP time, just not
        requiring exact-match at MINING time."""
        groups: Dict[str, Dict[str, Any]] = {}
        for entry in self.trace_log.iter_all(limit_files=lookback_files):
            user_input = entry.get("user_input")
            response = entry.get("response")
            if not user_input or not response:
                continue
            if entry.get("status") != "completed":
                continue
            if entry.get("stayed_within_brief") is False:
                continue
            intent = _intent_name(entry.get("perception"))
            if intent not in _SAFE_INTENTS:
                continue
            norm_input = _normalize(user_input)
            if self.procedural_memory.has(norm_input):
                continue  # already learned
            bucket = groups.setdefault(norm_input, {"responses": {}, "intent": intent, "last_seen": 0.0})
            response_text = str(response).strip()
            bucket["responses"][response_text] = bucket["responses"].get(response_text, 0) + 1
            bucket["last_seen"] = max(bucket["last_seen"], float(entry.get("timestamp", 0.0)))

        candidates = []
        for norm_input, bucket in groups.items():
            total_occurrences = sum(bucket["responses"].values())
            if total_occurrences < self.min_occurrences:
                continue
            # Most frequent exact phrasing wins (majority vote) --
            # still only ever serves a response that was ACTUALLY
            # given before, never a synthesized blend.
            best_response = max(bucket["responses"].items(), key=lambda pair: pair[1])[0]
            candidates.append({
                "pattern": norm_input,
                "response": best_response,
                "occurrences": total_occurrences,
                "intent": bucket["intent"],
                "last_seen": bucket["last_seen"],
            })
        return candidates

    def run_idle_cycle(self, lookback_files: int = 7) -> Dict[str, Any]:
        """Mine + auto-approve. Auto-approval is safe here BECAUSE
        mine_candidates() already enforces every safety condition
        (safe intent, completed, not flagged, repeated >= threshold)
        -- there is no weaker/stronger manual step to add on top."""
        with self._lock:
            candidates = self.mine_candidates(lookback_files=lookback_files)
            approved = []
            for candidate in candidates:
                proposal_id = uuid.uuid4().hex[:8]
                proposal = {
                    "id": proposal_id,
                    "status": "APPROVED",
                    "created_at": time.time(),
                    **candidate,
                }
                self.proposals[proposal_id] = proposal
                self.procedural_memory.learn(
                    trigger=candidate["pattern"],
                    action=candidate["response"],
                    kind="response_template",
                    metadata={
                        "intent": candidate["intent"],
                        "occurrences_at_approval": candidate["occurrences"],
                        "source_proposal": proposal_id,
                    },
                )
                approved.append(candidate["pattern"])
                self._emit("NATIVE_RESPONSE_TEMPLATE_APPROVED", proposal)

            self.run_count += 1
            self.last_mine_at = time.time()
            self.last_mine_result = {
                "candidates_found": len(candidates),
                "approved": len(approved),
                "patterns": approved,
                "timestamp": self.last_mine_at,
            }
            return self.last_mine_result

    # =============================================================
    # LOOKUP (called from NativeReasoner -- zero LLM cost)
    # =============================================================

    def match(self, user_input: str) -> Optional[str]:
        key = _normalize(user_input)
        action = self.procedural_memory.recall(key)
        return action if isinstance(action, str) else None

    # =============================================================
    # STATUS
    # =============================================================

    def status(self) -> Dict[str, Any]:
        proc_status = self.procedural_memory.status()
        return {
            "version": self.VERSION,
            "template_count": proc_status.get("by_kind", {}).get("response_template", 0),
            "run_count": self.run_count,
            "last_mine_at": self.last_mine_at,
            "last_mine_result": self.last_mine_result,
            "total_hits": proc_status.get("total_hits", 0),
            "min_occurrences": self.min_occurrences,
        }

    statistics = status

    def _emit(self, event_name: str, payload: Any) -> None:
        if self.events is None:
            return
        safe_emit = getattr(self.events, "safe_emit", None)
        if callable(safe_emit):
            safe_emit(event_name, payload, source="native_response_learning")
