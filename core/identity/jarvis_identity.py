from __future__ import annotations

"""JARVIS Identity -- the single structured source of truth for "who am I,
who are you, what can I actually do right now".

    JARVIS IDENTITY
          |
    +-----+-----+---------+
    |           |         |
 INVARIANTS  CURRENT   HISTORY
    |         SELF        |
 name/role  capabilities  experiences
 safety     goals         adaptations
 boundaries values        learned patterns

Why this exists: cli.py used to build its own separate, hardcoded
`identity_profile` dict every time it called think_and_respond(),
completely disconnected from core/identity/identity.py -- so there
were two "who is JARVIS" answers in the codebase that could silently
drift apart, and neither was queryable as structured data the LLM
route (or a native fast path) could actually read from.

    INVARIANTS   -- set once, at construction, from Identity/Values.
                    Never mutated at runtime. This is what "I am
                    JARVIS, not a chatbot" and the safety boundaries
                    mean structurally: no code path anywhere writes to
                    this after __init__.
    CURRENT SELF -- read live, every call, from whatever organs are
                    actually attached right now (skills, goals). This
                    can genuinely change turn to turn as capabilities
                    are added/removed -- it is NOT a static snapshot.
    HISTORY      -- append-only. record_adaptation() is the only
                    mutator, called when evolution actually applies a
                    change (see core/orchestration/blueprint_brain.py),
                    so "what have I learned" is a real, growing log,
                    not a decorative field.
"""

import time
from typing import Any, Dict, List, Optional

from .identity import Identity
from .values import Values


class JarvisIdentity:
    def __init__(self, brain: Any = None, memory: Any = None, goal_manager: Any = None):
        self._brain = brain
        self._memory = memory
        self._goal_manager = goal_manager
        self._adaptations: List[Dict[str, Any]] = []
        # GAP A + GAP B FIX (companion blueprint v2, Section 7): both of
        # these used to be purely in-process state that reset to empty/
        # "now" on every single restart -- meaning JARVIS could not
        # correctly answer "when were you made" (it answered "how long
        # has THIS process been running" instead) or "what have you
        # adapted over time" (the entire history silently vanished every
        # restart). Both are now loaded from the SAME durable SYSTEM-
        # namespace store everything else in this project uses, written
        # once and read back rather than reset each boot.
        self._created_at = self._load_or_create_birth_date()
        self._load_persisted_adaptations()
        # RUNTIME/UPTIME TRACKING (UK's explicit ask: "JARVIS ko pata ho
        # kitni der se chal raha hai", distinct from "kab paida hua").
        # THREE different numbers, all genuinely tracked:
        #   age_seconds            = time since _created_at (birth date,
        #                             already existed) -- includes time
        #                             JARVIS was OFF between sessions.
        #   session_uptime_seconds = time since THIS process started --
        #                             resets every restart, on purpose.
        #   cumulative_runtime_seconds = total time JARVIS has ever
        #                             actually been RUNNING, summed
        #                             across every past session PLUS
        #                             this one -- persisted, checkpointed
        #                             periodically (see checkpoint_runtime())
        #                             rather than only on clean shutdown,
        #                             since a killed process wouldn't get
        #                             a chance to save otherwise.
        self.session_started_at = time.time()
        self._cumulative_runtime_at_last_checkpoint = self._load_cumulative_runtime()

    def _load_cumulative_runtime(self) -> float:
        semantic = getattr(self._memory, "semantic", self._memory)
        if semantic is None or not hasattr(semantic, "find"):
            return 0.0
        try:
            for item in semantic.find(subject="jarvis_self", predicate="cumulative_runtime_seconds") or []:
                value = getattr(item, "value", None)
                if value is not None:
                    return float(value)
        except Exception:
            pass
        return 0.0

    def checkpoint_runtime(self) -> None:
        """Persist the current cumulative runtime total. Call this
        periodically (e.g. from idle_loop's own periodic review cycle)
        rather than relying only on a clean shutdown to save it -- a
        killed/crashed process on a phone is common enough that
        shutdown-only persistence would lose most of a day's uptime."""
        current_cumulative = self._cumulative_runtime_at_last_checkpoint + (time.time() - self.session_started_at)
        semantic = getattr(self._memory, "semantic", self._memory)
        if semantic is not None and hasattr(semantic, "remember"):
            try:
                semantic.remember(
                    subject="jarvis_self", predicate="cumulative_runtime_seconds", value=current_cumulative,
                    confidence=1.0, importance=0.3, source="runtime_checkpoint",
                    tags=["identity", "runtime"], namespace="SYSTEM",
                )
                self._cumulative_runtime_at_last_checkpoint = current_cumulative
                self.session_started_at = time.time()
            except Exception:
                pass

    def runtime_info(self) -> Dict[str, Any]:
        """The real, current answer to "how long have you been running"
        -- all three numbers, not conflated into one."""
        now = time.time()
        return {
            "age_seconds": round(now - self._created_at, 1),
            "session_uptime_seconds": round(now - self.session_started_at, 1),
            "cumulative_runtime_seconds": round(self._cumulative_runtime_at_last_checkpoint + (now - self.session_started_at), 1),
        }

    def _load_or_create_birth_date(self) -> float:
        """Read the one-time creation timestamp from durable memory if
        it already exists; otherwise this is genuinely the first-ever
        boot, so write it once. Falls back to time.time() (the old
        behavior) only if memory is unavailable -- never crashes
        identity construction over a missing/degraded memory organ."""
        semantic = getattr(self._memory, "semantic", self._memory)
        if semantic is None or not hasattr(semantic, "find"):
            return time.time()
        try:
            for item in semantic.find(subject="jarvis_self", predicate="created_at") or []:
                value = getattr(item, "value", None)
                if value is not None:
                    return float(value)
        except Exception:
            return time.time()
        now = time.time()
        try:
            if hasattr(semantic, "remember"):
                semantic.remember(
                    subject="jarvis_self", predicate="created_at", value=now,
                    confidence=1.0, importance=1.0, source="identity_bootstrap",
                    tags=["identity", "birth_date"], namespace="SYSTEM",
                )
        except Exception:
            pass
        return now

    def _load_persisted_adaptations(self) -> None:
        """Load any adaptations recorded in a previous process lifetime
        back into self._adaptations, so record_adaptation()'s durable
        log genuinely survives restarts instead of starting empty every
        time (the actual Gap B bug). Each adaptation is stored under
        its own unique "adaptation_<timestamp>" predicate (see
        record_adaptation()), so this reads ALL of subject="jarvis_self"
        rather than a single predicate, then filters client-side."""
        semantic = getattr(self._memory, "semantic", self._memory)
        if semantic is None or not hasattr(semantic, "find"):
            return
        try:
            for item in semantic.find(subject="jarvis_self") or []:
                predicate = str(getattr(item, "predicate", "") or "")
                if not predicate.startswith("adaptation_"):
                    continue
                value = getattr(item, "value", None)
                if isinstance(value, dict):
                    self._adaptations.append(value)
        except Exception:
            pass
        self._adaptations.sort(key=lambda a: a.get("timestamp", 0))

    def bind(self, *, brain: Any = None, memory: Any = None, goal_manager: Any = None) -> None:
        """Attach live organ references after construction (bootstrap.py
        wiring order sometimes constructs Identity before Brain exists)."""
        if brain is not None:
            self._brain = brain
        if memory is not None:
            self._memory = memory
        if goal_manager is not None:
            self._goal_manager = goal_manager

    # -----------------------------------------------------------
    # INVARIANTS -- immutable, structural, never touched after init
    # -----------------------------------------------------------
    def invariants(self) -> Dict[str, Any]:
        safety_values = [v["description"] for v in Values.CORE_VALUES if v["id"] in ("SAFETY_FIRST", "CONTROLLED_EVOLUTION")]
        return {
            "name": Identity.NAME,
            "designation": Identity.DESIGNATION,
            "creator": Identity.CREATOR,
            "role": (
                "An autonomous cognitive organism, not a chatbot or generic AI "
                "assistant. Reasoning flows through a fixed, contract-validated "
                "pipeline (perception -> semantic understanding -> cognition -> "
                "router -> brain -> experience -> learning -> self-evaluation -> "
                "evolution -> memory). The LLM is one interchangeable organ, "
                "called only when native reasoning genuinely needs language "
                "phrasing -- it is never the seat of identity, judgment, or "
                "what counts as a known fact."
            ),
            "purpose": Identity.PURPOSE,
            "safety_boundaries": safety_values,
        }

    # -----------------------------------------------------------
    # CURRENT SELF -- read live every call, genuinely mutable over time
    # -----------------------------------------------------------
    def current_self(self) -> Dict[str, Any]:
        return {
            "capabilities": self._live_capabilities(),
            "goals": self._live_goals(),
            "values": Values.get_values(),
        }

    def _live_capabilities(self) -> List[str]:
        """THE ACTUAL BUG (found 2026-09-11 from real runtime logs: UK
        asked JARVIS to create a Hinglish-only rule, JARVIS replied
        "yeh feature abhi tak implement nahi hua hai" -- a FALSE
        statement about itself. Root cause: this method only ever
        checked skill_executor.registry.skills, an entirely separate,
        unused subsystem nothing in this codebase actually registers
        anything into -- so every real capability built this session
        (rule creation, standing instructions, tool-calling, web
        search, contested-fact review) was invisible to the LLM's own
        self-knowledge. The LLM wasn't lying or hallucinating out of
        nowhere -- it was accurately reporting an EMPTY capability
        list it was actually given. Now derived from hasattr() checks
        against the real, live Brain object, so this list can never
        claim a capability that isn't actually present, and never
        misses one that is -- it degrades automatically if a method
        is ever removed, rather than needing to be hand-maintained in
        sync with brain.py."""
        capabilities: List[str] = []
        brain = self._brain
        skill_executor = getattr(brain, "skill_executor", None)
        registry = getattr(skill_executor, "registry", None)
        skills = getattr(registry, "skills", None)
        if isinstance(skills, dict) and skills:
            capabilities.extend(sorted(skills.keys()))

        # Each entry: (attribute on Brain, human-readable capability
        # description). Checked live via hasattr so this can never
        # drift out of sync with what Brain actually exposes.
        _KNOWN_CAPABILITIES = [
            ("_user_rules", "Learn behavioral rules directly from conversation "
                             "(e.g. \"hamesha Hinglish mein reply karo\") and apply them to every future response"),
            ("standing_instructions", "Create daily time-triggered standing instructions "
                                       "(e.g. \"roz subah good morning bolo\") that fire automatically"),
            ("list_pending_self_rules", "Propose its own behavioral rules from repeated experience, "
                                         "held for UK's explicit confirmation before they take effect"),
            ("list_contested_facts", "Detect when a less-trusted source conflicts with an already-"
                                      "trusted fact, and hold the conflict for UK's review instead of guessing"),
            ("save_verified_fact", "Search the web and save specific facts to long-term memory on request"),
            ("get_llm_dependency_stats", "Track and report how much of its own understanding is "
                                          "resolved natively vs. via an LLM call"),
            ("list_pending_patterns", "Propose its own extraction patterns (regex) from repeated "
                                       "experience, sandbox-test them itself, and hold them for UK's "
                                       "confirmation before they run live -- never applies one unconfirmed"),
            ("start_remote_access", "Start a public HTTPS tunnel (ngrok) on request so JARVIS is "
                                     "reachable from outside the local network"),
        ]
        for attr_name, description in _KNOWN_CAPABILITIES:
            if getattr(brain, attr_name, None) is not None:
                capabilities.append(description)

        # Tool-calling / web search: capability-gated on the LLM bridge
        # actually supporting it (offline mode genuinely can't do this).
        llm = getattr(brain, "llm", None)
        if llm is not None and hasattr(llm, "generate_with_tools"):
            capabilities.append(
                "Search the web for current information when asked (or when it doesn't already know "
                "something) and clearly say so, rather than only answering from training data"
            )
        return capabilities

    def _live_goals(self) -> List[Dict[str, Any]]:
        if self._goal_manager is None:
            return []
        try:
            return list(self._goal_manager.pending())
        except Exception:
            return []

    # -----------------------------------------------------------
    # HISTORY -- append-only; record_adaptation() is the only writer
    # -----------------------------------------------------------
    def record_adaptation(self, description: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        entry = {
            "description": description,
            "evidence": evidence or {},
            "timestamp": time.time(),
        }
        self._adaptations.append(entry)
        # THE ACTUAL GAP B FIX: persist this entry too, not just the
        # in-memory list. A UNIQUE predicate per adaptation (timestamp-
        # based) is required here -- semantic memory's remember()
        # treats (subject, predicate) as a single fact slot that gets
        # UPDATED in place (with history tracking the old value), which
        # is correct for "user.name" but wrong for a log that needs
        # every entry kept, not just the latest overwriting the rest.
        semantic = getattr(self._memory, "semantic", self._memory)
        if semantic is not None and hasattr(semantic, "remember"):
            try:
                predicate = f"adaptation_{int(entry['timestamp'] * 1000)}"
                semantic.remember(
                    subject="jarvis_self", predicate=predicate, value=entry,
                    confidence=1.0, importance=0.5, source="identity_self_record",
                    tags=["identity", "adaptation"], namespace="SYSTEM",
                )
            except Exception:
                pass

    def history(self) -> Dict[str, Any]:
        experience_count = 0
        learned_patterns_count = 0
        if self._memory is not None:
            try:
                stats = self._memory.statistics()
                runtime = stats.get("runtime", {}) if isinstance(stats, dict) else {}
                experience_count = runtime.get("episodic", 0)
                learned_patterns_count = runtime.get("semantic", 0)
            except Exception:
                pass
        return {
            "experience_count": experience_count,
            "learned_patterns_count": learned_patterns_count,
            "adaptations": list(self._adaptations[-20:]),
            "age_seconds": round(time.time() - self._created_at, 1),
        }

    # -----------------------------------------------------------
    # Composite views
    # -----------------------------------------------------------
    def full_identity(self) -> Dict[str, Any]:
        return {
            "invariants": self.invariants(),
            "current_self": self.current_self(),
            "history": self.history(),
        }

    def owner_profile(self) -> Dict[str, Any]:
        """The single person this JARVIS instance belongs to -- resolved
        from what has ACTUALLY been learned about them (their stated
        real name, their stated addressing preference), not a static
        hardcoded string compared against itself.

        THE ACTUAL BUG THIS REPLACES: describe_self_structured() used
        to compute `is_creator = speaker_name == inv["creator"]` where
        BOTH sides came from the same hardcoded "UK" (cli.py passes a
        static identity_profile={"creator": "UK", ...} on every single
        turn, and Identity.CREATOR is also the literal string "UK") --
        the comparison was tautologically True by construction, using
        zero live memory, so "who am I" answers never actually
        reflected anything JARVIS had learned about the person (their
        real name "UJJWAL", their addressing-preference rule "UK",
        or any later correction). This is a single-user system by
        design (no multi-user recognition is being attempted here) --
        the fix is simply to answer from what has genuinely been
        learned instead of a frozen placeholder that happened to match
        itself.
        """
        semantic = getattr(self._memory, "semantic", self._memory)
        real_name: Optional[str] = None
        preferred_address: Optional[str] = None
        if semantic is not None and hasattr(semantic, "find"):
            for predicate in ("full_name", "name"):
                if real_name:
                    break
                try:
                    for item in semantic.find(subject="user", predicate=predicate) or []:
                        value = str(getattr(item, "value", "") or "").strip()
                        if value:
                            real_name = value
                            break
                except Exception:
                    pass
            try:
                for item in semantic.find(subject="jarvis_rule", predicate="affirmative") or []:
                    value = str(getattr(item, "value", "") or "").strip()
                    if value:
                        preferred_address = value
                        break
            except Exception:
                pass
        return {
            "real_name": real_name,
            "preferred_address": preferred_address,
            "display_name": preferred_address or real_name or Identity.CREATOR,
            "known": bool(real_name or preferred_address),
        }

    def describe_self_structured(self, speaker_name: Optional[str] = None) -> Dict[str, Any]:
        """Compact, response-brief-ready structured answer to "who are
        you" / "who am I" questions -- used by the native identity
        fast path in response_brief.py so this is answered from real
        structured state, never from LLM guessing about its own persona."""
        inv = self.invariants()
        hist = self.history()
        owner = self.owner_profile()
        if owner["known"]:
            who_you_are = owner["display_name"]
            if owner["real_name"] and owner["preferred_address"] and owner["real_name"].strip().lower() != owner["preferred_address"].strip().lower():
                who_you_are += f" (aapka poora naam {owner['real_name']} bhi maine yaad rakha hai)"
        else:
            who_you_are = f"{inv['creator']} -- I haven't learned a name or an addressing preference from you yet"
        return {
            "i_am": inv["name"],
            "my_designation": inv["designation"],
            "my_role": inv["role"],
            "my_creator": inv["creator"],
            "my_purpose": inv.get("purpose"),
            "who_you_are": who_you_are,
            "experience_count": hist["experience_count"],
            "capability_count": len(self._live_capabilities()),
        }
