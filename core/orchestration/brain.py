from __future__ import annotations

import json
import os
import re
import time
import hashlib
from .cognitive_router import CognitiveRouter
from .companion_tools import CompanionToolsMixin
from .perception import PerceptionEngine, LLMPerceptionProvider
from .response_brief import build_response_brief, try_direct_recall_answer, try_identity_answer, check_response_grounding, check_action_claim_grounding, get_self_authored_rules
from ..cognition.user_rules import UserRuleStore
from ..autonomy.standing_instructions import StandingInstructionStore
from ..learning.outcome_feedback import detect_correction
from ..learning.pattern_synthesis import PatternSynthesizer

# Tools whose results are REAL data read out of JARVIS's own stores --
# a reply backed by one of these is grounded by definition, so the
# grounding-checker's hedge must never override it (see the
# auto-correction block in think_and_respond).
READ_ONLY_DATA_TOOLS = {    "list_pending_self_rules", "explain_self_rule", "list_standing_instructions",
    "list_contested_facts", "get_recent_conversation", "explain_own_architecture",
    "get_conversation_history", "evaluate_own_recent_responses", "list_pending_patterns",
}

# How many INDEPENDENT reasoning cycles must separately arrive at the
# same behavioral rule before it adopts itself without waiting for
# /confirm_rule. Higher than pattern_synthesis's threshold because a
# behavioral rule changes how JARVIS acts in every future turn, where
# a bad extraction pattern only mis-parses one kind of sentence.
RULE_AUTO_ADOPT_THRESHOLD = 8


def _turn_was_tool_backed(tool_trace) -> bool:
    """THE WEB-SEARCH BUG (2026-09-13, UK's live trace): the grounding
    checker's hedge was overwriting REAL web-search answers, which is
    why "web search nahi karta, bakwaas karta hai" -- it WAS searching
    (3 browser_search calls visible in the trace) and then throwing the
    result away.

    Cause: this check was written as `c.get("name") in
    READ_ONLY_DATA_TOOLS`, but browser_search resolves server-side and
    is recorded by tool_registry's run_tool_loop with NO "name" key at
    all -- it appends {"builtin_tool": True, "search_results": [...]}.
    So a turn genuinely backed by live sources scored as
    tool_backed=False and got hedged over every single time.

    A turn counts as tool-backed if EITHER a named read-only data tool
    returned data, OR a built-in web search actually ran.
    """
    for call in (tool_trace or []):
        if not isinstance(call, dict):
            continue
        if call.get("name") in READ_ONLY_DATA_TOOLS and call.get("result"):
            return True
        if call.get("builtin_tool") and (call.get("search_results") or call.get("executed_tools_summary")):
            return True
    return False
from ..cognition.native_reasoner import NativeReasoner
from ..learning.native_response_learning import NativeResponseLearner
from ..contracts import validate_input, validate_output, ContractError
from ..learning.post_response_reasoning import build_reasoning_trace
from ..learning.dependency_metrics import DependencyMetrics, contradiction_rate
from ..learning.fallback_pattern_detector import FallbackPatternDetector
from ..learning.category_word_learner import CategoryWordLearner
from ..skills.skill_executor import SkillExecutor
from typing import Any, Dict, Optional

from ..learning.learning_queue import AsyncLearningQueue
from ..runtime.log import log_event
from ..runtime.chat_log import log_chat_turn



# ---------------------------------------------------------------- episodes
# EXPONENTIAL EPISODE GROWTH (fixed 2026-09-14). This is the RAM bug that
# was crashing Termux.
#
# Each USER_CHAT episode stored the ENTIRE perception dict. On the
# llm_fallback path, perception carries
#     semantic_learning.candidate.evidence.context.recent_experiences
# which is a list of PREVIOUS EPISODES -- each of which contains its own
# perception, which contains its own recent_experiences, and so on.
#
# Measured: episode size doubled every turn. Turn 1 = 309 bytes,
# turn 12 = 575,330 bytes, a 1,862x increase. Twenty turns of
# conversation is hundreds of megabytes, all of it held in memory,
# written to SQLite, AND embedded into FAISS. That is what was taking
# the phone down, and why the load appeared only after long sessions.
#
# The fix is to store a FLAT, BOUNDED summary. Learning needs the
# relations and the intent; it has never needed a recursive copy of the
# conversation so far.
_EPISODE_FIELD_LIMIT = 2000
_EPISODE_MAX_RELATIONS = 12


def _flatten_perception_for_episode(perception: Any) -> Dict[str, Any]:
    """Bounded, non-recursive snapshot of a turn's perception."""
    if not isinstance(perception, dict):
        return {}

    semantic = perception.get("semantic_understanding")
    if not isinstance(semantic, dict):
        semantic = {}

    def _clip(value: Any) -> Any:
        try:
            text = value if isinstance(value, str) else json.dumps(value, default=str)
        except Exception:
            text = str(value)
        return text[:_EPISODE_FIELD_LIMIT]

    intent = perception.get("intent")
    if isinstance(intent, dict):
        intent = {k: intent.get(k) for k in ("name", "type", "confidence") if k in intent}

    return {
        "normalized_text": _clip(perception.get("normalized_text") or ""),
        "intent": intent,
        "language": perception.get("language"),
        "confidence": perception.get("confidence"),
        "source": perception.get("source"),
        # Relations are what KnowledgeBuilder actually reads. Capped, and
        # each field clipped, so one runaway value cannot blow the row up.
        "relations": [
            {k: _clip(r.get(k)) for k in ("subject", "predicate", "value", "confidence", "source")}
            for r in (semantic.get("relations") or [])[:_EPISODE_MAX_RELATIONS]
            if isinstance(r, dict)
        ],
        "entities": [
            _clip(e.get("text") if isinstance(e, dict) else e)
            for e in (semantic.get("entities") or [])[:_EPISODE_MAX_RELATIONS]
        ],
        # DELIBERATELY ABSENT: semantic_evidence, semantic_learning,
        # fallback_request, context. Those are the recursive fields.
        "_note": "flattened for storage -- full perception lives in the trace log only",
    }


# MINIMUM TOKENS FOR A COMPLETE USER-VISIBLE REPLY (2026-09-17, UK:
# "Jarvis ka response hamesha unlimited hona chahiye hamesha reserved"
# / "response kabhi bhi truncate na ho"). The budget-exhaustion retry
# below used to fire at >= 40 tokens remaining -- nowhere near enough
# to finish a Hinglish sentence, so it produced a reply that stopped
# mid-clause, which reads as JARVIS breaking off rather than as a
# short answer. Below this floor it is more honest to deliver the
# already-drafted response (or the explicit out-of-space message)
# than to emit a sentence that cannot finish.
_MIN_COMPLETE_REPLY_TOKENS = 250


class Brain(CompanionToolsMixin):
    """
    Central orchestration organ of JARVIS.

    Brain coordinates major cognitive organs.

    Brain is NOT:
        - the LLM
        - the memory database
        - the learning engine itself
        - the evaluator
        - the knowledge builder
        - the evolution engine
        - an unrestricted executor

    Authoritative semantic architecture:

        User Input
          ↓
        Perception
          ↓
        Semantic Understanding
          ↓
        Structured Semantic Result
          ↓
        Cognition
          ↓
        Response
          ↓
        Experience / Learning

    Evolution remains controlled:

        Proposal
            ↓
        Validate
            ↓
        Approve
            ↓
        Apply

    Brain only orchestrates these operations.

    Semantic understanding is authoritative for semantic interpretation.
    Brain orchestrates Perception → Semantic Understanding → Cognition →
    Response → Experience / Learning and does not perform a second semantic
    extraction pass through the LLM.
    """

    VERSION = "0.6.0"

    def __init__(
        self,
        memory_manager=None,
        experience_engine=None,
        self_evaluator=None,
        knowledge_builder=None,
        memory_consolidator=None,
        learning_coordinator=None,
        evolution_engine=None,
        event_bus=None,
        internal_state=None,
        planner=None,
        goal_manager=None,
        llm_bridge=None,
        cognitive_router=None,
        perception_engine=None,
        skill_registry=None,
        skill_executor=None,
        auto_accept_knowledge: bool = True,
    ):
        # =========================================================
        # CORE ORGANS
        # =========================================================

        self.memory = memory_manager
        # Native, zero-LLM-cost rule capture -- see core/cognition/user_rules.py.
        # getattr(...) because self.memory can be a bare MemoryManager
        # (has .semantic) OR None (standalone/test Brain instances);
        # UserRuleStore already no-ops cleanly when semantic_memory is None.
        self._user_rules = UserRuleStore(getattr(self.memory, "semantic", None))
        # Standing (triggered) instructions -- distinct from the
        # behavioral rules above. See core/autonomy/
        # standing_instructions.py's module docstring: captures "do X
        # when Y happens" (today: daily time triggers), e.g. UK's
        # "roz subah good morning bolo". Public (no leading underscore,
        # unlike _user_rules) because idle_loop needs read access to
        # due_now()/mark_fired() from outside Brain -- see bootstrap.py.
        self.standing_instructions = StandingInstructionStore(getattr(self.memory, "semantic", None))
        # Self-authored EXTRACTION PATTERNS (2026-09-12, UK's explicit
        # "regex = hardcoding" objection): see core/learning/
        # pattern_synthesis.py's module docstring for the full design.
        # llm_bridge isn't set yet at this point in __init__ (see
        # set_llm_bridge() below) -- PatternSynthesizer reads
        # self.llm live via getattr each time it's used, so this is
        # safe to construct before the bridge is attached.
        self.pattern_synthesizer = PatternSynthesizer(llm_bridge=None, semantic_memory=getattr(self.memory, "semantic", None))
        # UK's #5: learns to answer repeated, safe, non-fact-dependent
        # small talk without an LLM call -- see core/learning/
        # native_response_learning.py's module docstring for the full
        # safety design (why it's restricted to a narrow intent
        # allowlist, never fact questions).
        self.native_response_learner = NativeResponseLearner(event_bus=event_bus)
        # UK's #2 recall/learning/memory proposal: the formal
        # procedural-memory organ (see core/memory/procedural_memory.py)
        # that native_response_learner now delegates its storage to --
        # exposed directly on Brain too so introspection/monitor.py can
        # show it as its own memory type, not just a sub-detail of one
        # feature.
        self.procedural_memory = self.native_response_learner.procedural_memory
        # Unified native (zero-LLM-cost) resolver chain (blueprint
        # section 27) -- see core/cognition/native_reasoner.py.
        # identity_system is often attached AFTER Brain construction
        # (bootstrap.py wiring order), so it's refreshed on the
        # instance right before each use rather than fixed here.
        self._native_reasoner = NativeReasoner(memory_manager=self.memory, brain=self, native_response_learner=self.native_response_learner)
        # Bound after construction via bootstrap.py (JarvisIdentity needs
        # this Brain instance to read live capabilities, so it can't be
        # constructed before Brain exists). None-safe everywhere it's read.
        self.identity_system: Optional[Any] = None
        # Post-response reasoning history (see process_experience below
        # and core/learning/post_response_reasoning.py) -- bounded so it
        # can't grow unboundedly over a long session.
        self.last_reasoning_traces: list = []
        # Most recent turn's LLM tool-call trace (see
        # core/orchestration/tool_registry.py's run_tool_loop()) --
        # which tools the model proposed, the gated result of each,
        # for traceability the same way last_reasoning_traces already is.
        self.last_tool_call_trace: list = []
        # OUTCOME FEEDBACK part 1/2 -- see the capture site right
        # after build_response_brief() and the correction-detection
        # site near the top of the turn-processing method.
        self.last_turn_fact_ids: list = []
        # THE ACTUAL FIX for UK's core 2026-09-11 complaint, evidenced
        # by trace-log analysis: questions about JARVIS's OWN recent
        # conversation ("hum log kya baat kar rahe the", "last 5
        # response do") had NO real data source, so the LLM was
        # forced to improvise an answer every time -- explaining the
        # wild inconsistency (contradicting itself turn to turn about
        # whether it can "see" its own past responses). This is a
        # real ring buffer, appended once per turn at the single
        # chokepoint _record_action_response() already documents as
        # "every turn passes through this regardless of route" --
        # see get_recent_conversation() below and its tool-calling
        # exposure in core/orchestration/tool_registry.py.
        from collections import deque
        self.recent_turns = deque(maxlen=50)
        # Foundation for the "response vs brief" hallucination-learning
        # loop (2026-09-11, flagged as a bigger design item, scoped
        # down to a first real piece here): every time
        # check_response_grounding() flags a response, the actual
        # violation gets recorded here -- not just logged and
        # forgotten -- so patterns across turns (e.g. "self-reference
        # claims keep getting fabricated") become something Brain can
        # actually inspect and act on, not just a warning line no one
        # reads. See get_grounding_violation_patterns() below.
        self.grounding_violations = deque(maxlen=100)
        # Behavioral rules that adopted themselves on accumulated
        # evidence (see RULE_AUTO_ADOPT_THRESHOLD) -- surfaced so this
        # is never a silent change.
        self.auto_adopted_rules = deque(maxlen=50)
        # NEW: real, retained history of WHY each layer produced what it
        # produced this turn -- not just a transient CLI display line.
        # Every layer (perception, semantic understanding) now reports
        # a structured validation: did it succeed, and if not, exactly
        # why (which mechanism was tried, what specifically failed).
        # This is what makes "why didn't you extract X" answerable from
        # real retained data via the self-awareness fast path, instead
        # of only ever being visible for the ONE turn it happened on,
        # in the CLI, then discarded.
        self.last_layer_validations: list = []
        # UK's explicit ask: no protection existed against a message
        # trying to hide malicious "instructions" for JARVIS. Retained
        # history (like last_layer_validations) so flagged inputs can
        # genuinely be reviewed later, not lost after one turn.
        self.safety_check_history: list = []
        # LLM Dependency Metrics (blueprint section 43) -- one shared
        # counter set for the whole Brain lifetime, updated at the same
        # single chokepoint background learning uses.
        self.dependency_metrics = DependencyMetrics()
        # Evolution-of-LLM-fallbacks detector (blueprint section 48) --
        # see core/learning/fallback_pattern_detector.py.
        self.fallback_pattern_detector = FallbackPatternDetector()
        # WIRED THIS SESSION (was built earlier but never connected --
        # a real, confirmed gap UK caught: overnight idle-learning had
        # almost nothing to work with because fallback_pattern_detector
        # only tracks ONE narrow failure shape (recall-miss questions),
        # while category_word_learner tracks something far more common:
        # every time the LLM successfully extracts a favourite_<category>
        # fact that native regex's indicator-word set didn't already
        # know, THAT word is a genuine, real vocabulary-expansion
        # candidate -- happening on ordinary STATEMENTS, not just the
        # narrow recall-question case.
        try:
            from ..cognition.semantic_understanding.engine import SemanticUnderstandingEngine
            known_words = set(SemanticUnderstandingEngine._CATEGORY_INDICATOR_WORDS)
        except Exception:
            known_words = set()
        self.category_word_learner = CategoryWordLearner(known_indicator_words=known_words, min_occurrences=2)
        # Per-turn memoization for build_context(). _perceive(),
        # _build_cognition_input() and the LLM-fallback route each call
        # build_context() with essentially the same query text once per
        # turn -- that's 3 separate FAISS similarity searches + ONNX
        # embedding computations for one user message, which is real,
        # avoidable latency (each is real compute, not free). Cache is
        # cleared at the top of every think_and_respond() call.
        self._context_cache: dict = {}
        self.experience = experience_engine
        self.evaluator = self_evaluator
        self.knowledge_builder = knowledge_builder
        self.consolidator = memory_consolidator
        self.learning = learning_coordinator
        self.evolution = evolution_engine

        # =========================================================
        # SYSTEM SERVICES
        # =========================================================

        self.events = event_bus
        self.state = internal_state
        self.planner = planner
        self.goal_manager = goal_manager
        self.llm = llm_bridge

        # =========================================================
        # COGNITION / PERCEPTION / SKILLS
        # =========================================================

        self.cognitive_router = cognitive_router or CognitiveRouter()
        self.skill_registry = skill_registry
        self.skill_executor = (
            skill_executor
            if skill_executor is not None
            else (
                SkillExecutor(skill_registry)
                if skill_registry is not None
                else None
            )
        )
        self.perception = perception_engine or PerceptionEngine(state=self.state)

        if self.llm is not None:
            self.set_llm_bridge(self.llm)

        self.last_cognitive_decision: Optional[Dict[str, Any]] = None
        self.last_perception: Optional[Dict[str, Any]] = None
        self.last_context: Optional[Dict[str, Any]] = None
        self.last_brain_decision: Optional[Dict[str, Any]] = None
        self.last_action_response: Optional[Dict[str, Any]] = None
        # Set at the top of every think_and_respond() call; read back by
        # _record_action_response() so the centralized background-
        # learning hand-off (see _record_action_response below) has the
        # live user_input without having to thread it through every one
        # of the ~10 return points in think_and_respond().
        self._last_user_input: str = ""

        # What JARVIS's own last response asked or offered, so the next
        # bare "haan"/"ok" can be resolved against it instead of
        # arriving at perception nearly empty. See
        # core/cognition/pending_expectation.py.
        self._pending_expectation = None

        # =========================================================
        # LEARNING POLICY
        # =========================================================
        # Whether experiences that pass through process_experience()
        # get their resulting knowledge candidate auto-accepted into
        # persistent memory. This is what actually makes JARVIS learn
        # instead of just logging episodes. Set to False if you want
        # a manual review step (accept_knowledge / reject_knowledge).
        self.auto_accept_knowledge = auto_accept_knowledge

        # =========================================================
        # RUNTIME
        # =========================================================

        self.created_at = time.time()
        self.last_cycle_at: Optional[float] = None
        self.cycle_count = 0
        self.last_result: Optional[Dict[str, Any]] = None
        self.running = True

        # =========================================================
        # ASYNC LEARNING QUEUE
        # =========================================================
        # Response synchronous, learning asynchronous + ordered queue.
        # think_and_respond() returns to the user as soon as the LLM
        # reply is ready; the full Experience -> Learning -> Evaluate
        # -> KnowledgeBuilder -> DB pipeline runs in the background,
        # one job at a time, in the exact order turns happened. See
        # core/learning/learning_queue.py for the full rationale.
        self._learning_queue = AsyncLearningQueue(worker=self._run_learning_job)

        # =========================================================
        # LIVE TELEMETRY (for CLI trace + web /api endpoints)
        # =========================================================
        # Real, cumulative counters updated every turn -- no simulated
        # numbers. `last_turn_trace` is the single source of truth
        # both cli.py and the web backend read from after a turn.
        self.last_turn_trace: Optional[Dict[str, Any]] = None
        self.total_turns = 0
        self.total_latency_seconds = 0.0
        self.total_tokens_estimate = 0

        # =========================================================
        # HINGLISH TYPO NORMALIZATION (retrieval-time only)
        # =========================================================
        # A small, expandable dictionary of common Hinglish/typo forms
        # UK actually types (see project chat history) -> their clean
        # form. This is applied ONLY to the copy of the text used for
        # memory retrieval (so "confident retrieval hone chahiye rules
        # for typos" is real, not aspirational) -- the original
        # user_input is still what gets stored/shown, unmodified.
        self.typo_map: Dict[str, str] = {
            "chahie": "chahiye", "chahia": "chahiye", "chaiye": "chahiye",
            "krde": "kar de", "krdo": "kar do", "kr": "kar", "krna": "karna",
            "hoga": "hoga", "hona": "hona", "nhi": "nahi", "nahi": "nahi",
            "mje": "mujhe", "mjhe": "mujhe", "mai": "main", "mein": "main",
            "yhi": "yahi", "yha": "yahan", "wha": "wahan",
            "smjha": "samjha", "smjhna": "samjhna",
            "bta": "bata", "btao": "batao", "bta do": "bata do",
            "thik": "theek", "thk": "theek",
            "acha": "accha", "achha": "accha",
            "rha": "raha", "rhi": "rahi", "rhe": "rahe",
            "kese": "kaise", "kse": "kaise",
            "tmhe": "tumhe", "tmhara": "tumhara", "tm": "tum",
            "dedo": "de do", "dena": "dena",
            # Added from real observed transcript failures -- each of
            # these directly caused an extraction-cascade failure
            # ("Extraction cascade exhausted...", confidence=0.00)
            # before being caught here.
            "hye": "hey", "nam": "naam",
            "onnly": "only", "gielfriend": "girlfriend", "girlfrien": "girlfriend",
            "nahu": "nahi", "crator": "creator",
            "tunhe": "tumhe", "tunhara": "tumhara", "tunhari": "tumhari",
            "muje": "mujhe", "mujje": "mujhe",
            "insoect": "inspect",
        }

    def _normalize_hinglish_typos(self, text: str) -> Dict[str, Any]:
        """
        Whole-word substitution against self.typo_map. Returns the
        normalized text plus the list of corrections actually made,
        so the trace/UI can show real typo-correction data instead of
        nothing (the web frontend has a dedicated slot for this --
        CognitiveTrace.typosCorrected -- that was never populated).
        """
        if not text:
            return {"normalized": text, "corrections": []}

        tokens = re.findall(r"\w+|\W+", text)
        corrections = []
        out_tokens = []
        for tok in tokens:
            key = tok.lower()
            if key in self.typo_map and self.typo_map[key] != key:
                corrected = self.typo_map[key]
                corrections.append({"raw": tok, "corrected": corrected})
                out_tokens.append(corrected)
            else:
                out_tokens.append(tok)

        return {"normalized": "".join(out_tokens), "corrections": corrections}

    # =============================================================
    # THINK AND RESPOND (LLM + IDENTITY + MEMORY + PIPELINE)
    # =============================================================
    
    def think_and_respond(
        self,
        user_input: str,
        identity_profile: Optional[Dict[str, Any]] = None,
        source: str = "cli",
        grounding_context: Optional[str] = None,
    ) -> str:
        """
        Canonical Brain entry point.

        Flow:
            User Input
              -> Perception
              -> Cognitive Router
              -> Goal / Native / Hybrid / LLM
              -> Brain Decision
              -> Action Response
              -> Trace

        The router is the authority for choosing the cognition route.
        LLM is optional and is only required for routes that actually
        need language cognition/synthesis.
        """
        started = time.time()
        user_input = str(user_input or "").strip()

        # RESOLVE "HAAN" / "OK" AGAINST JARVIS'S OWN LAST QUESTION
        # (fixed 2026-09-14, verified against UK's trace).
        #
        # A bare affirmative has almost no content on its own -- the
        # trace showed exactly this landing at confidence 0.0-0.2 with
        # unknowns=['meaning','language','intent'], because nothing
        # recorded what JARVIS itself had just asked or offered. This
        # expands the SAME short reply into one that names what it is
        # affirming, using ONLY what JARVIS's own prior response
        # actually said -- never invented, so if there was nothing
        # pending the turn goes through unchanged and perception is no
        # worse off than before.
        try:
            from ..cognition.pending_expectation import expand_short_reply
            pending = getattr(self, "_pending_expectation", None)
            expanded = expand_short_reply(user_input, pending)
            if expanded != user_input:
                log_event("brain", f"short reply expanded against pending expectation: "
                          f"'{user_input}' -> '{expanded}'", level="info")
                self._raw_short_reply = user_input   # keep the original for logging/trace
                user_input = expanded
            self._pending_expectation = None   # consumed either way -- one-shot
        except Exception as exc:
            log_event("brain", f"pending-expectation expansion skipped: {exc}", level="warning")

        self._last_user_input = user_input
        # Fresh per-turn: see build_context() docstring note above.
        self._context_cache = {}

        # THE ACTUAL FIX (UK's explicit ask: "good morning bolo" jaisi
        # baat ek RULE hai, fact nahi, aur JARVIS ko yaad rakhna chahiye"):
        # this used to run ONLY inside the LLM route further below, so a
        # standing instruction like "hamesha subah good morning bolo"
        # was captured ONLY on turns the router happened to send to the
        # LLM -- a clear imperative like that is exactly the kind of
        # message the router is likely to classify as a goal/native
        # instruction instead, meaning the rule was silently never
        # captured at all. Rule capture is a handful of zero-cost regex
        # checks against the user's own words (see core/cognition/
        # user_rules.py) -- it must run on EVERY turn, before routing
        # decides anything, not just the ones that end up needing the LLM.
        try:
            self._user_rules.capture_from_message(user_input)
        except Exception:
            pass
        try:
            self.standing_instructions.capture_from_message(user_input)
        except Exception:
            pass
        # OUTCOME FEEDBACK, part 2/2 (2026-09-11 roadmap Phase 6): if
        # THIS message reads as UK correcting the PREVIOUS answer, the
        # facts that answer was built from (captured last turn -- see
        # the capture site right after build_response_brief() below)
        # get weakened. Real negative evidence, not internal
        # self-corroboration. Deliberately checked BEFORE
        # last_turn_fact_ids gets overwritten by this turn's own
        # brief-building further down.
        try:
            if detect_correction(user_input) and self.last_turn_fact_ids:
                semantic = getattr(self.memory, "semantic", None)
                if semantic is not None and hasattr(semantic, "weaken"):
                    weakened = []
                    for kid in self.last_turn_fact_ids:
                        try:
                            semantic.weaken(kid, confidence_delta=0.15)
                            weakened.append(kid)
                        except Exception:
                            continue
                    if weakened:
                        log_event("brain", f"negative outcome feedback: weakened {len(weakened)} fact(s) used in the previous answer after UK's correction", level="info")
                        self._emit("OUTCOME_FEEDBACK_NEGATIVE", {"weakened_knowledge_ids": weakened})
        except Exception:
            pass

        self._emit(
            "BRAIN_CYCLE_STARTED",
            {
                "source": source,
                "user_input": user_input,
            },
        )

        # ---------------------------------------------------------
        # 0. NATIVE DIRECT-ANSWER FAST PATH (before ANY LLM call)
        # ---------------------------------------------------------
        # This is what actually makes "every API call has a cost" real
        # instead of a design statement. Without this, a simple recall
        # question like "mera favourite color kya hai" still spent 3
        # LLM calls before ever reaching the LLM route's own fast path
        # below: perception's extraction cascade tries up to 2 (primary
        # + refined), then semantic understanding's own LLM fallback
        # tries a 3rd when native symbolic parsing is uncertain -- all
        # BEFORE routing even decides whether an LLM is needed at all.
        # Checking here, first, means a fact JARVIS already has costs
        # zero API calls end to end, not just zero for the final
        # response-generation step.
        try:
            early_context = self.build_context(query=user_input, recent_limit=0, knowledge_limit=6) if hasattr(self, "build_context") else {}
        except Exception:
            early_context = {}
        speaker_name = identity_profile.get("creator") if isinstance(identity_profile, dict) else None
        self._native_reasoner.identity = getattr(self, "identity_system", None)
        self._native_reasoner.llm_bridge = self.llm
        try:
            native_answer = self._native_reasoner.try_answer(user_input, early_context, speaker_name=speaker_name)
        except Exception:
            native_answer = None
        direct_answer = native_answer.text if native_answer is not None else None
        answered_by = native_answer.resolver if native_answer is not None else None
        if direct_answer is not None:
            # FAST PATH PERCEPTION GAP (fixed 2026-09-15, from UK's own
            # chat log). The fast path above deliberately skips the LLM
            # to keep a known answer at zero API cost -- that design is
            # correct and stays. But it left `self.last_perception`
            # with almost nothing in it: no intent, no language, no
            # entities. UK's log showed this exactly:
            #     "mai kaun hu?" -> perception = {source: identity,
            #      reason: "perception/LLM skipped entirely"} -- no
            #      intent, no language at all.
            # That emptiness then propagates into the trace viewer, the
            # response brief's context recap, and anything downstream
            # that reads perception -- all blind on every fast-path
            # turn, which by design is the MAJORITY of turns once
            # JARVIS has learned enough.
            #
            # Fix: derive a best-effort intent from the resolver name
            # (the fast path already knows WHICH KIND of stored
            # knowledge answered -- identity, learned_template, etc. --
            # which is itself a coarse intent label) and detect language
            # with the same cheap, non-LLM regex heuristic
            # semantic_understanding/engine.py already uses elsewhere.
            # Neither of these costs an API call; both were sitting
            # right there unused.
            try:
                from ..cognition.semantic_understanding.engine import SemanticUnderstandingEngine as _SUE
                detected_language = _SUE._detect_language(user_input)
            except Exception:
                detected_language = "unknown"

            _RESOLVER_INTENT_LABELS = {
                "identity": "identity_question",
                "learned_template": "learned_response",
                "semantic_recall": "recall_question",
                "procedural": "procedural_recall",
            }
            inferred_intent = {
                "name": _RESOLVER_INTENT_LABELS.get(answered_by, answered_by or "native_fast_path"),
                "confidence": 1.0,
                "source": f"native_fast_path:{answered_by}",
            }

            self.last_perception = {
                "user_input": user_input, "normalized_text": user_input,
                "source": answered_by, "confidence": 1.0, "uncertainty": 0.0,
                "reason": "answered directly from stored knowledge; full LLM perception skipped "
                          "(intent/language below are cheap heuristics, not the full extraction)",
                "intent": inferred_intent,
                "language": detected_language,
                "entities": [], "relations": [], "events": [], "references": [],
            }
            self.last_cognitive_decision = {"mode": "llm", "confidence": 1.0, "reason": f"native fast path: {answered_by}"}
            self.last_brain_decision = {"mode": "llm", "status": "completed", "answered_by": answered_by}
            response = self._record_action_response(
                mode="llm", status="completed", response=direct_answer,
                action={"answered_by": answered_by},
            )
            self._trace(user_input, response, self.last_cognitive_decision, self.last_perception, started, False)
            return response

        # ---------------------------------------------------------
        # 1. PERCEPTION
        # ---------------------------------------------------------
        try:
            perception = self._perceive(user_input)
        except Exception as exc:
            self.last_brain_decision = {
                "mode": "error",
                "status": "perception_failed",
                "error": str(exc),
            }
            response = f"[Brain Perception Error: {exc}]"
            self._record_action_response(
                mode="error",
                status="failed",
                response=response,
                error=str(exc),
            )
            self._trace(
                user_input,
                response,
                {"mode": "error", "status": "perception_failed"},
                {},
                started,
                self.llm is not None,
            )
            return response

        # ---------------------------------------------------------
        # 2. COGNITIVE ROUTING
        # ---------------------------------------------------------
        try:
            route = self._route_cognition(user_input, perception)
        except Exception as exc:
            self.last_brain_decision = {
                "mode": "error",
                "status": "routing_failed",
                "error": str(exc),
            }
            response = f"[Brain Routing Error: {exc}]"
            self._record_action_response(
                mode="error",
                status="failed",
                response=response,
                error=str(exc),
            )
            self._trace(
                user_input,
                response,
                {"mode": "error", "status": "routing_failed"},
                perception,
                started,
                self.llm is not None,
            )
            return response

        mode = str(route.get("mode", "llm")).lower()
        intent = perception.get("intent") or {}
        skill_name = (
            intent.get("skill")
            or intent.get("name")
            if isinstance(intent, dict)
            else None
        )

        # ---------------------------------------------------------
        # 3. GOAL ROUTE
        # ---------------------------------------------------------
        if mode == "goal":
            perceived_goal = perception.get("goal")

            result = self._register_and_plan_goal(perceived_goal)

            if result.get("status") != "planned":
                response = "Goal could not be planned."
                self.last_brain_decision = {
                    "mode": "goal",
                    "status": result.get("status", "failed"),
                    "goal": perceived_goal,
                }
                self._record_action_response(
                    mode="goal",
                    status="failed",
                    response=response,
                    action={"goal": perceived_goal},
                )
            else:
                goal = result.get("goal") or {}
                plan = result.get("plan") or []

                response = (
                    f"Goal accepted and planned: {goal.get('text', '')}"
                    if goal.get("text")
                    else "Goal accepted and planned."
                )

                self.last_brain_decision = {
                    "mode": "goal",
                    "status": "planned",
                    "goal": goal,
                    "plan": plan,
                }

                self._record_action_response(
                    mode="goal",
                    status="planned",
                    response=response,
                    action={
                        "goal": goal,
                        "plan": plan,
                    },
                )

            self._trace(
                user_input,
                response,
                route,
                perception,
                started,
                self.llm is not None,
            )
            return response

        # ---------------------------------------------------------
        # 4. NATIVE / TOOL ROUTE
        # ---------------------------------------------------------
        if mode in {"tool", "native"}:
            if self.skill_executor is None or not skill_name:
                response = self._fallback(user_input)

                self.last_brain_decision = {
                    "mode": "native",
                    "status": "no_capability",
                    "skill": skill_name,
                }

                self._record_action_response(
                    mode="native",
                    status="failed",
                    response=response,
                    action={"skill": skill_name},
                    error="capability_not_available",
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

            try:
                native_result = self.skill_executor.execute(
                    skill_name,
                    user_input=user_input,
                )

                response = str(native_result)

                self.last_brain_decision = {
                    "mode": "native",
                    "status": "completed",
                    "skill": skill_name,
                    "action_result": response,
                }

                self._record_action_response(
                    mode="native",
                    status="completed",
                    response=response,
                    action={"skill": skill_name},
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

            except Exception as exc:
                response = f"[Brain Action Error: {exc}]"

                self.last_brain_decision = {
                    "mode": "native",
                    "status": "failed",
                    "skill": skill_name,
                    "error": str(exc),
                }

                self._record_action_response(
                    mode="native",
                    status="failed",
                    response=response,
                    action={"skill": skill_name},
                    error=str(exc),
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

        # ---------------------------------------------------------
        # 5. HYBRID ROUTE
        # ---------------------------------------------------------
        if mode == "hybrid":
            if self.skill_executor is None or not skill_name:
                response = self._fallback(user_input)

                self.last_brain_decision = {
                    "mode": "hybrid",
                    "status": "no_native_capability",
                    "skill": skill_name,
                }

                self._record_action_response(
                    mode="hybrid",
                    status="failed",
                    response=response,
                    action={"skill": skill_name},
                    error="capability_not_available",
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

            try:
                native_result = self.skill_executor.execute(
                    skill_name,
                    user_input=user_input,
                )

                synthesized = self._hybrid_synthesize(
                    user_input=user_input,
                    skill_name=skill_name,
                    native_result=native_result,
                    source=source,
                )

                response = str(synthesized)

                self.last_brain_decision = {
                    "mode": "hybrid",
                    "status": "completed",
                    "native_skill": skill_name,
                    "native_result": str(native_result),
                }

                self._record_action_response(
                    mode="hybrid",
                    status="completed",
                    response=response,
                    action={
                        "skill": skill_name,
                        "native_result": str(native_result),
                    },
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

            except Exception as exc:
                response = f"[Brain Hybrid Error: {exc}]"

                self.last_brain_decision = {
                    "mode": "hybrid",
                    "status": "failed",
                    "skill": skill_name,
                    "error": str(exc),
                }

                self._record_action_response(
                    mode="hybrid",
                    status="failed",
                    response=response,
                    action={"skill": skill_name},
                    error=str(exc),
                )

                self._trace(
                    user_input,
                    response,
                    route,
                    perception,
                    started,
                    self.llm is not None,
                )
                return response

        # ---------------------------------------------------------
        # 6. LLM / KNOWN / OTHER LANGUAGE ROUTE
        # ---------------------------------------------------------
        if self.llm is None:
            response = self._fallback(user_input)

            self.last_brain_decision = {
                "mode": mode,
                "status": "llm_unavailable",
            }

            self._record_action_response(
                mode=mode,
                status="degraded",
                response=response,
            )

            self._trace(
                user_input,
                response,
                route,
                perception,
                started,
                False,
            )
            return response

        # Reuse the existing LLM + memory implementation, but do not
        # recursively call think_and_respond(). The LLM bridge is the
        # language cognition provider for this route.
        typo_result = self._normalize_hinglish_typos(user_input)
        retrieval_query = typo_result["normalized"]

        context = (
            self.build_context(query=retrieval_query, recent_limit=3)
            if hasattr(self, "build_context")
            else {}
        )

        # Rule capture now runs unconditionally near the top of
        # think_and_respond() (before routing), so every route -- not
        # just this LLM one -- captures standing instructions. Only the
        # read side is needed here.
        active_rules = []
        try:
            active_rules = self._user_rules.get_active_rules()
        except Exception:
            pass

        bot_name = "JARVIS"
        creator_name = "UK"

        if isinstance(identity_profile, dict):
            bot_name = identity_profile.get("name", bot_name)
            creator_name = identity_profile.get("creator", creator_name)

        # THE ACTUAL FIX (UK's explicit ask: "Brain ko pata hona chahiye
        # wo kaun hai, sirf identity route nahi"): previously
        # self.identity_system (JarvisIdentity -- purpose, invariants,
        # the REAL learned owner name/addressing-preference, live
        # capabilities) was only ever wired into the narrow native
        # "identity question" fast path (see _native_reasoner.identity
        # above). Every OTHER route -- including this LLM route, which
        # handles the majority of turns -- never read it at all, so the
        # model only ever saw the two bare hardcoded strings
        # "JARVIS"/"UK" cli.py passes on every single call, with no
        # purpose, no real learned name, no capability list. This block
        # pulls the SAME structured identity data the identity fast path
        # already uses and folds it into every LLM call, not just
        # identity-shaped questions.
        identity_block = None
        identity_system = getattr(self, "identity_system", None)
        if identity_system is not None:
            try:
                inv = identity_system.invariants()
                owner = identity_system.owner_profile()
                current = identity_system.current_self()
                bot_name = inv.get("name", bot_name)
                if owner.get("known"):
                    creator_name = owner["display_name"]
                identity_block = {
                    "i_am": inv.get("name"),
                    "designation": inv.get("designation"),
                    "role": inv.get("role"),
                    "purpose": inv.get("purpose"),
                    "created_by": inv.get("creator"),
                    "talking_to": owner.get("display_name") or inv.get("creator"),
                    "talking_to_is_creator": True,
                    "live_capabilities": current.get("capabilities", [])[:12],
                    # UK's explicit ask: JARVIS previously had no idea
                    # whether a turn arrived from the CLI terminal or the
                    # web browser chat -- `source` was passed all the way
                    # down to think_and_respond() but only ever used for
                    # event/learning metadata, never told to the model or
                    # made answerable. Real, cheap, already-available.
                    "channel": source,
                }
            except Exception:
                identity_block = None

        # Native direct-answer fast path: a narrow class of "what is my
        # X" recall questions with an exact stored fact can be answered
        # without spending an LLM call at all. This is the concrete
        # "every API call has a cost" behaviour -- an actual skip, not
        # a policy statement. Anything even slightly ambiguous falls
        # through to the LLM route below unchanged.
        # Second chance at the native fast path: the early check above
        # (step 0) used the raw, non-typo-corrected user_input and a
        # narrower context. This one runs against the typo-normalized
        # retrieval query and the fuller LLM-route context, so a fact
        # that only surfaces after typo correction still gets answered
        # for free instead of falling through to a real LLM call.
        direct_answer = try_direct_recall_answer(user_input, context)
        if direct_answer is not None:
            self.last_brain_decision = {
                "mode": "llm",
                "status": "completed",
                "answered_by": "native_direct_recall",
            }
            response = direct_answer
            self._record_action_response(
                mode="llm",
                status="completed",
                response=response,
                action={"answered_by": "native_direct_recall"},
            )
            self._trace(user_input, response, route, perception, started, True)
            return response

        # Structured response brief (see response_brief.py): Brain's own
        # native reasoning (perception, retrieval, rules) assembles a
        # small, strictly-typed schema of what's actually true and what
        # the user asked. The LLM's only job is to phrase ONE reply from
        # it -- it does not get raw dict dumps of memory objects and it
        # is explicitly told not to invent facts outside the schema.
        self_authored_rules = []
        try:
            self_authored_rules = get_self_authored_rules(self.memory)
        except Exception:
            pass
        # CONVERSATION INTELLIGENCE LAYER (2026-09-19, UK's explicit ask
        # after a full session trace: the layer existed and was fully
        # tested from an earlier pass, but nothing ever called
        # update_from_turn() with real perception data, and nothing
        # ever fed its state into THIS brief -- it only reached the
        # separate Extended Thinking SSE panel. Both gaps fixed here,
        # defensively (hasattr-guarded) so base Brain (no continuity
        # layer) is unaffected -- only BlueprintBrain has one.
        continuity_context = None
        if hasattr(self, "conversation_continuity"):
            try:
                entity_names = list((perception.get("entities") or {}).keys()) if isinstance(perception.get("entities"), dict) else None
                perception_intent = perception.get("intent") if isinstance(perception.get("intent"), dict) else None
                self.conversation_continuity.update_from_turn(
                    user_input,
                    user_intent=perception_intent,
                    perception_entities=entity_names,
                )
                continuity_context = self.conversation_continuity.get_relevant_context()
            except Exception:
                pass  # continuity is an enhancement, never a reason to fail the turn

        brief = build_response_brief(
            user_input=user_input,
            perception=perception,
            context=context,
            active_rules=active_rules,
            self_authored_rules=self_authored_rules,
            bot_name=bot_name,
            creator_name=creator_name,
            grounding_context=grounding_context,
            continuity_context=continuity_context,
        )

        # OUTCOME FEEDBACK, part 1/2 (2026-09-11 roadmap Phase 6):
        # snapshot which real stored facts were actually surfaced to
        # the LLM THIS turn, so that if UK corrects JARVIS on the
        # VERY NEXT turn ("galat hai", "wrong", ...), Brain knows
        # exactly which facts to weaken -- see the correction-
        # detection block near the top of this method (searches for
        # detect_correction(user_input) against self.last_turn_fact_ids,
        # which still holds THIS turn's ids until the line below runs
        # again next turn). Deliberately captured here (after the
        # brief that will actually reach the LLM is built), not
        # earlier from build_context()'s raw retrieval, so this only
        # reflects facts that were genuinely part of what the LLM saw.
        try:
            self.last_turn_fact_ids = [
                kid for kid in (
                    getattr(item, "knowledge_id", None) if not isinstance(item, dict) else item.get("knowledge_id")
                    for item in (context.get("relevant_knowledge") or [])
                ) if kid
            ]
        except Exception:
            self.last_turn_fact_ids = []

        # Response Data Contract (blueprint section 13 / Rule 08): the
        # brief must itself be well-formed BEFORE it's allowed to reach
        # the LLM -- this is what turns "response_brief.py builds a
        # nice-looking dict" into an actually-enforced organ boundary,
        # matching the same contract-first discipline every other layer
        # transition already has (see core/contracts/schemas.py
        # "response.input"/"response.output").
        try:
            brief = validate_input("response", brief)
        except ContractError as exc:
            log_event("brain", f"response brief failed its own contract, using it anyway (degraded): {exc}", level="warning")

        system_prompt = (
            f"You are {bot_name}, a self-contained cognitive AI organism. "
            f"The user is {creator_name}, your developer and creator -- never "
            f"swap roles or claim to be {creator_name}. You will be given a "
            f"structured JSON brief below describing this turn. Follow its "
            f"instructions_for_llm exactly.\n\n"
            + (f"YOUR IDENTITY (who you are, real and current, not a persona to improvise):\n"
               f"{json.dumps(identity_block, ensure_ascii=False)}\n\n" if identity_block else "")
            + f"BRIEF:\n{json.dumps(brief, ensure_ascii=False)}"
        )

        # EXTENDED THINKING (wired 2026-09-13). The composer toggle used
        # to write its value to sessionStorage where nothing read it, so
        # the Brain button changed colour and did nothing. It now
        # reaches here.
        #
        # The cap matters: UK saw "Thought for 26.7s" and then a crash.
        # Deliberation is several sequential LLM calls, and on a phone
        # over mobile data that adds up fast enough to exhaust the turn
        # budget and stall the process. So thinking is skipped whenever
        # the remaining budget is thin, regardless of the toggle -- a
        # setting should not be able to run the organism out of room.
        try:
            mode = getattr(self, "thinking_mode", "off")
            if mode in ("on", "auto"):
                from ..cognition.thinking import resolve_mode
                decision = resolve_mode(mode, user_input,
                                        getattr(self, "last_information_need", None))
                remaining = 0
                try:
                    remaining = int(self.llm.budget_status().get("remaining_calls", 0))
                except Exception:
                    remaining = 0
                if decision["think"] and remaining < 4:
                    decision = {"think": False, "mode": mode,
                                "reason": "Budget kam hai -- is turn sochne ke bajaye seedha jawab."}
                self.last_thinking_decision = decision
                if decision["think"]:
                    system_prompt += (
                        "\n\nTHINK FIRST: Before answering, reason through this privately in a few "
                        "short lines -- what is being asked, what you are assuming, what could make "
                        "you wrong. Then give the answer itself. Do NOT narrate that you were "
                        f"thinking. ({decision['reason']})"
                    )
        except Exception as exc:
            log_event("brain", f"thinking mode skipped: {exc}", level="warning")

        # PERSONA + PER-USER MEMORY (2026-09-13).
        #
        # The persona is the films' JARVIS: dry, economical, volunteers
        # the inconvenient number, and contradicts its owner when he is
        # wrong. It is written to REINFORCE honesty rather than decorate
        # over it -- a charming JARVIS that softens real risks would undo
        # the thing this whole system was built around.
        #
        # The memory block is keyed on the SPEAKER's username. Isolation
        # is enforced in SQL inside user_memory.py, not by asking the
        # model nicely -- a prompt instruction can be argued with, a
        # WHERE clause cannot.
        try:
            from ..identity.persona import persona_prompt
            speaker = getattr(self, "current_speaker", None) or {}

            # THE PRIVACY LEAK, AGAIN (fixed 2026-09-14). This branch had
            # regressed back to "role = speaker.get('role', 'owner' if
            # not speaker else 'user')" -- an EMPTY speaker (i.e. nobody
            # authenticated) resolved to role='owner', handing every
            # anonymous caller UK's own persona and authority. This was
            # fixed once already in an earlier round and came back in
            # this branch. No identity means GUEST, always -- never a
            # convenience default toward the most privileged role.
            role = (speaker.get("role") or "guest").strip().lower()
            username = speaker.get("username")
            verified = bool(speaker.get("is_verified")) and bool(username or role == "owner")
            if not verified:
                role = "guest"

            user_style = None
            memory_block = ""
            try:
                from ..identity.user_memory import context_block, recall_for_user, observe_turn
                observe_turn(username, user_input)
                if username:
                    user_style = (recall_for_user(username, limit=1) or {}).get("style")
                    memory_block = context_block(username, role=role)
            except Exception:
                pass

            # PER-IDENTITY MEMORY SCHEMA (2026-09-14, UK's spec). Adds
            # this speaker's OWN persistent (or, for guests, bounded
            # ephemeral) memory on top of the flat user_memory block
            # above. Resolved through identity_memory.resolve_identity(),
            # which is the single choke point that makes
            # cross-contamination structurally impossible -- there is no
            # code path here capable of reading another identity's
            # schema.
            identity_block = ""
            try:
                from ..identity.identity_memory import context_for
                speaker_for_schema = {**speaker, "role": role, "username": username,
                                      "is_verified": verified}
                schema_ctx = context_for(speaker_for_schema, limit=8)
                if schema_ctx["lines"]:
                    identity_block = (
                        f"\n\n{schema_ctx['note']}\n" +
                        "\n".join(schema_ctx["lines"])
                    )
                else:
                    # FIRST-TURN MARKER (2026-09-14, UK: "JARVIS ko
                    # maloom ho first reply se hi ki user role kya hai
                    # -- stranger, owner, logged-in user, ya admin").
                    #
                    # persona_prompt() already sets tone by role (owner
                    # gets "sir", a guest gets generic courtesy) on
                    # every turn -- that part existed already. What was
                    # missing is that JARVIS never SAID which of the
                    # five it believed it was talking to, so from UK's
                    # side there was no way to tell "JARVIS knows I am
                    # the owner" from "JARVIS is just being polite to
                    # everyone the same way".
                    #
                    # An empty schema_ctx['lines'] means this identity
                    # has no prior turns at all -- genuinely the first
                    # message from this person. That is the one moment
                    # worth being explicit, rather than on every turn,
                    # where repeating "you are the owner" would be
                    # stilted.
                    role_label = {
                        "owner": "verified owner (UK)", "co_owner": "verified co-owner",
                        "admin": "verified admin", "user": "verified user",
                        "guest": "an unverified guest -- possibly a stranger",
                    }.get(role, "an unverified guest")
                    identity_block = (
                        f"\n\nFIRST TURN: This is the first message from this identity "
                        f"({role_label}). Naturally, in your own opening line, make it clear "
                        f"you know who you are speaking to -- do not just be generically "
                        f"polite. Do this once, briefly, not as a checklist."
                    )
            except Exception:
                pass

            system_prompt = (
                persona_prompt(role=role, speaker_name=username, is_verified=verified,
                               user_style=user_style)
                + "\n\n" + system_prompt
                + (f"\n\n{memory_block}" if memory_block else "")
                + identity_block
            )
        except Exception as exc:
            log_event("brain", f"persona injection skipped: {exc}", level="warning")

        # SEARCH DECISION (2026-09-13, UK: JARVIS khud decide kare kab
        # internet jaana hai -- aur borderline case mein poochhe, na ki
        # guess kare ya chupke se search kar le). Brain has already
        # worked out WHERE this answer lives (information_need); this
        # turns that into an explicit instruction, so the model is not
        # left to improvise the search decision on its own.
        try:
            from .companion_tools import should_confirm_search
            search_decision = should_confirm_search(user_input, getattr(self, "last_information_need", None))
            self.last_search_decision = search_decision
            if search_decision["action"] == "search":
                system_prompt += (
                    f"\n\nSEARCH: Use browser_search for this turn. Reason: {search_decision['reason']} "
                    "Say in your reply that you looked it up, and never state a figure or fact from "
                    "this category without having actually searched for it."
                )
            elif search_decision["action"] == "confirm":
                system_prompt += (
                    f"\n\nSEARCH: Borderline -- {search_decision['reason']} Answer from what you "
                    "genuinely know, and then ask UK in one short line whether he wants you to check "
                    "the web for the current picture. Do not search without his yes."
                )
            else:
                # SAY NOTHING (re-fixed 2026-09-15 -- this was fixed once
                # earlier and lost in the revert; UK's fresh chat log
                # showed the regression: 29/144 turns ended in an
                # unprompted "web se check karun?"). This branch used to
                # append "SEARCH: Do not search this turn. Reason: ..."
                # to EVERY non-search turn. Putting the word 'search' in
                # the system prompt on every turn is what made JARVIS
                # habitually mention the web even on "2*2 = ?" and "how
                # are you" -- the cheapest way to stop a model raising a
                # topic is to stop raising it first.
                system_prompt += (
                    "\n\nDo not offer to look anything up online this turn, and do not mention "
                    "the web at all. Answer from what you know and from the brief above."
                )
        except Exception as exc:
            log_event("brain", f"search-decision unavailable this turn: {exc}", level="warning")

        # The current user message must NEVER be lost to context-budget
        # truncation. CognitiveBudgeter trims each side of the payload
        # by *dropping the tail*, so anything that must survive has to
        # live in its own short, isolated blob rather than at the end
        # of a long, unbounded memory dump. The live question therefore
        # stays here, separate from the brief above.
        context_prompt = f"{creator_name}: {user_input}\n\n{bot_name}:"

        try:
            # TOOL-CALLING (M2, 2026-09-11): tried BEFORE the plain
            # generate() path below. See core/orchestration/
            # tool_registry.py's module docstring for the full design
            # rationale (cortex-basal-ganglia gating, why this replaced
            # a regex-routing proposal UK explicitly rejected). Returns
            # None (falls through unchanged to plain generate()) when
            # tool-calling isn't usable this turn (offline, no tool
            # was actually needed and the model preferred plain text,
            # or the loop failed) -- this is purely additive, nothing
            # below this block changes.
            tool_response = None
            try:
                from .tool_registry import run_tool_loop
                # Reset BEFORE attempting -- run_tool_loop() only ever
                # sets this on paths that actually reach its internal
                # loop; if generate_with_tools isn't available at all
                # (offline, no Groq key) it returns None immediately
                # without touching this, which would otherwise leave
                # a PREVIOUS turn's trace looking like it happened this
                # turn in cli.py's "4c. TOOL CALLS" panel / monitor.py.
                self.last_tool_call_trace = []
                self.last_tool_loop_failed = False
                tool_response = run_tool_loop(self, system_prompt=system_prompt, user_message=user_input)
            except Exception as exc:
                log_event("brain", f"tool-calling loop failed, falling back to plain generation: {exc}", level="warning")
                tool_response = None
                # An exception here is the SAME kind of hard failure as
                # generate_with_tools returning None inside run_tool_loop
                # (see tool_registry.py) -- not "no tool was needed".
                self.last_tool_loop_failed = True

            if tool_response:
                response = tool_response
            else:
                # HONEST DEGRADATION (2026-09-20, root-cause pass): if
                # tool-calling genuinely failed this turn (provider
                # outage/rate-limit -- see run_tool_loop's own comment),
                # the plain generate() fallback below has NO way to
                # actually run code, create files, or invoke the coding
                # agent, even though the request may need exactly that.
                # UK's chat log showed this exact gap: JARVIS kept asking
                # unrelated clarifying questions turn after turn instead
                # of ever saying it simply could not act right then. Tell
                # the fallback call the truth so it tells UK the truth,
                # instead of silently losing capability and improvising.
                if getattr(self, "last_tool_loop_failed", False):
                    system_prompt += (
                        "\n\nACTION TOOLS UNAVAILABLE THIS TURN: the tool-calling system (coding "
                        "agent, file operations, research/planning workers) could not be reached "
                        "this turn -- likely a provider/connectivity issue, not a decision that no "
                        "tool was needed. If UK's message asks for code, a project, a plan, or any "
                        "action, say plainly that the action systems are temporarily unreachable and "
                        "to please try again in a moment -- do NOT claim anything was created, "
                        "planned, saved or registered, and do NOT ask unrelated clarifying questions "
                        "as if progress is being made when none can happen this turn."
                    )
                generate = getattr(self.llm, "generate", None)

                if callable(generate):
                    response = str(
                        generate(
                            system_prompt,
                            context_prompt,
                        )
                    ).strip()
                else:
                    generate_response = getattr(
                        self.llm,
                        "generate_response",
                        None,
                    )

                    if not callable(generate_response):
                        raise AttributeError(
                            "LLM bridge exposes neither generate() nor "
                            "generate_response()."
                        )

                    # LENGTH-AWARE BUDGET (2026-09-12, UK's explicit
                    # requirement that he be able to ask for genuinely
                    # long replies): previously this call took the
                    # bridge's default max_tokens (512) regardless of
                    # what UK actually asked for, so even with budget
                    # available a long-form request was silently capped
                    # at a few sentences. Now a detected long-form ask
                    # ("detailed research", "1000 characters",
                    # "vistrit", a big explicit number) gets a much
                    # larger allowance, drawn from the raised turn
                    # budget (see config/cognition.json) and still
                    # bounded by whatever genuinely remains.
                    wants_long = False
                    try:
                        from .tool_registry import is_deep_research_request
                        wants_long = is_deep_research_request(user_input)
                    except Exception:
                        wants_long = False
                    requested_tokens = 512
                    chunked_result = None
                    if wants_long:
                        try:
                            available = int(self.llm.budget_status().get("remaining_output_tokens", 0)) if hasattr(self.llm, "budget_status") else 0
                        except Exception:
                            available = 0
                        requested_tokens = max(512, min(8000, available - 100))

                        # CHUNKED LONG-FORM (2026-09-13, UK: "500 kya
                        # 50000 lines bhi generate karwa saku"). Raising
                        # the per-turn budget only widens ONE call, and
                        # every model has a hard per-response cap no
                        # amount of budget removes -- so anything truly
                        # large has to be written in sections and
                        # assembled. Only triggered when the request
                        # genuinely implies more than a single call can
                        # hold; ordinary long answers still take the
                        # cheaper one-call path below.
                        try:
                            from .long_form import estimate_chunks_needed, generate_long_form
                            import re as _re
                            asked_lines = None
                            m = _re.search(r"(\d{3,6})\s*(lines?|line|shabd|words?|characters?)", user_input, _re.I)
                            if m:
                                asked_lines = int(m.group(1))
                            chunks = estimate_chunks_needed(requested_lines=asked_lines) if asked_lines else 1
                            if chunks > 1:
                                log_event("brain", f"long-form request needs {chunks} chunks -- using multi-call assembly", level="info")
                                chunked_result = generate_long_form(
                                    generate_response,
                                    system_prompt=system_prompt,
                                    request=user_input,
                                    chunk_count=chunks,
                                    budget_remaining=(
                                        (lambda: int(self.llm.budget_status().get("remaining_output_tokens", 0)))
                                        if hasattr(self.llm, "budget_status") else None
                                    ),
                                )
                        except Exception as lf_err:
                            log_event("brain", f"chunked generation unavailable, falling back to single call: {lf_err}", level="warning")
                            chunked_result = None

                    if chunked_result is not None and chunked_result.text:
                        response = chunked_result.text
                        self.last_long_form = chunked_result.as_dict()
                    else:
                        response = str(
                            generate_response(
                                system_prompt=system_prompt,
                                user_input=context_prompt,
                                max_tokens=requested_tokens,
                                level="response_generation",
                            )
                        ).strip()

            if not response:
                response = "..."

            # response.output side of the Response Data Contract: the
            # LLM's output returns to JARVIS and is not automatically
            # trusted (Rule 09). check_response_grounding() (see
            # response_brief.py) is a real, conservative check -- it
            # flags proper-noun/number tokens in the reply that don't
            # appear anywhere in the brief's own legitimate sources, so
            # the most flagrant class of fabrication (an invented name,
            # place, or figure) is caught. It only ever WARNS: a false
            # positive here would silently corrupt real replies, which
            # would be worse than an occasional missed hallucination.
            grounding = check_response_grounding(
                response, brief,
                relations_extracted_this_turn=len((perception.get("semantic_understanding") or {}).get("relations") or []) if isinstance(perception, dict) else None,
                tool_calls_this_turn=[c.get("name") for c in (getattr(self, "last_tool_call_trace", None) or []) if isinstance(c, dict) and c.get("name")],
                tool_results_this_turn=[c.get("result") for c in (getattr(self, "last_tool_call_trace", None) or []) if isinstance(c, dict) and c.get("result") is not None],
            )
            # Detection-side safety net for false action claims (see
            # check_action_claim_grounding's docstring) -- unlike the
            # general grounding check above, this one is narrow and
            # confident enough to safely SUBSTITUTE the response, not
            # just flag it. action_executed is hardcoded False here:
            # reaching this branch at all already means routing found
            # no native/skill capability for this turn (this is the
            # "no executable native capability was selected" path --
            # see the ROUTING trace line) -- so no real action ran.
            action_correction = check_action_claim_grounding(response, action_executed=False)
            if action_correction:
                log_event(
                    "brain",
                    "response claimed a delete/update/verify action that never executed -- substituted an honest reply",
                    level="warning",
                )
                response = action_correction
                grounding = check_response_grounding(response, brief, relations_extracted_this_turn=0)
            try:
                validate_output("response", {
                    "text": response,
                    "stayed_within_brief": grounding.stayed_within_brief,
                    "flagged_unsupported": grounding.flagged_unsupported,
                })
            except ContractError as exc:
                log_event("brain", f"response.output contract violation: {exc}", level="warning")
            if not grounding.stayed_within_brief:
                log_event(
                    "brain",
                    f"response may contain unsupported content not present in the brief: {grounding.flagged_unsupported}",
                    level="warning",
                )
                try:
                    self.grounding_violations.append({
                        "user_input": user_input, "response": response,
                        "flagged": list(grounding.flagged_unsupported or []),
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
                # AUTO-CORRECTION (2026-09-11, UK's explicit ask: "LLM
                # JARVIS ko overrule na kare" -- Brain should act on a
                # caught violation, not just log it and let the
                # fabrication reach UK anyway). Scoped to the ONE
                # category safe to auto-fix without another LLM call:
                # an unverified self-reference claim (session/episodic
                # memory explanations, "am I JARVIS or the LLM" claims)
                # that skipped the real tool. Brain calls the SAME
                # deterministic tool directly here and replaces the
                # fabricated text with the real answer -- zero extra
                # LLM cost, zero risk of a second hallucination on
                # retry, because nothing is being regenerated, just
                # substituted with ground truth.
                if any("unverified self-reference" in str(f) for f in (grounding.flagged_unsupported or [])):
                    try:
                        if re.search(r"\b(last|recent|pichl[ae]|hum.{0,10}baat)\b", user_input, re.I):
                            real = self.get_recent_conversation(n=5)
                            if real.get("turns"):
                                last = real["turns"][-1]
                                response = f'Pichhli baar tumne poocha tha "{last.get("user_said")}", maine jawab diya tha: "{last.get("jarvis_replied")}"'
                            else:
                                response = "Abhi tak is session mein koi record nahi hai."
                        else:
                            arch = self.explain_own_architecture()
                            response = arch.get("how_replies_are_generated", response)
                        log_event("brain", "auto-corrected an unverified self-reference response using the real tool data directly", level="info")
                    except Exception:
                        pass
                else:
                    # GENERAL AUTO-CORRECTION (2026-09-11, UK's explicit
                    # "sab fix karo" ask) -- NOW GATED (2026-09-12,
                    # after UK's live trace showed this firing on
                    # correct, tool-backed answers over and over):
                    # if a read-only data tool actually ran this turn
                    # and returned real data, the reply is grounded in
                    # the most reliable source JARVIS has -- its own
                    # stores -- and hedging over it is strictly wrong,
                    # not "safe". The hedge now only applies when there
                    # was NO real data backing the reply at all.
                    tool_backed = _turn_was_tool_backed(getattr(self, "last_tool_call_trace", None))
                    if not tool_backed:
                        # NO MORE HARDCODED HEDGE (2026-09-13, UK: "ye
                        # hard coded response nahi chahiye, JARVIS
                        # hamesha khud bol ke bataye"). The old code
                        # pasted ONE fixed sentence here, so UK saw the
                        # identical paragraph dozens of times -- it read
                        # as a canned error, not as JARVIS thinking.
                        #
                        # Now JARVIS states its OWN uncertainty, in its
                        # own words, about THIS specific turn: Brain
                        # supplies the real reason (what it could not
                        # back up) and the LLM only words it. Same
                        # division of labour as every other reply --
                        # Brain decides what is true, LLM phrases it.
                        # If that call is impossible (no budget/calls
                        # left), the original response is kept rather
                        # than substituting a canned line.
                        unsupported = ", ".join(str(f) for f in (grounding.flagged_unsupported or [])[:3]) or "kuch hisse"
                        try:
                            response = str(self.llm.generate_response(
                                system_prompt=(
                                    # REWORDED 2026-09-19 (UK's real chat
                                    # logs: this exact instruction's
                                    # "check memory, ask him, or search
                                    # the web" phrasing was the literal
                                    # source of the "kya main memory
                                    # check karu ya web search karu ya
                                    # aapse pooch loon" pattern spamming
                                    # nearly every reply -- the model was
                                    # following this prompt's own
                                    # prescribed three options verbatim,
                                    # turn after turn, reading as a
                                    # scripted refusal rather than
                                    # genuine reasoning). Combined with
                                    # the grounding-check itself now
                                    # being far less trigger-happy (see
                                    # response_brief.py's technical-
                                    # vocabulary exemption -- this path
                                    # should fire MUCH more rarely from
                                    # here on, only for genuine personal/
                                    # contextual claims, not ordinary
                                    # technical discussion), this prompt
                                    # no longer hands the model a fixed
                                    # menu to recite. It states JARVIS's
                                    # actual nature instead: cooperative,
                                    # never a refusal engine, act on
                                    # what's genuinely uncertain rather
                                    # than announcing uncertainty as a
                                    # dead end.
                                    "You are JARVIS speaking to UK in Hinglish. You just drafted a reply, "
                                    "and your own grounding check flagged a SPECIFIC part of it as not yet "
                                    "backed by a stored fact or tool result -- most of your knowledge does "
                                    "NOT need this (general/technical knowledge is always fine to state "
                                    "plainly); this is specifically about the flagged part. In ONE or TWO "
                                    "natural sentences: say plainly what you're still working out about "
                                    "THAT specific part, then actually move toward resolving it in the SAME "
                                    "reply (state what you already know for certain, or ask ONE precise "
                                    "question that would settle it) -- never a generic list of your own "
                                    "available actions, never a flat refusal, never the same phrasing twice "
                                    "in a row. You are UK's collaborator working through this WITH him, not "
                                    "a system declining a request."
                                ),
                                user_input=(
                                    f"UK asked: {user_input}\n"
                                    f"Your unverified draft was: {response}\n"
                                    f"Unsupported in it: {unsupported}"
                                ),
                                # 700, not 200 (fixed 2026-09-17). UK's
                                # exact complaint -- "Jarvis ka response
                                # kabhi bhi truncate na ho" -- and EVERY
                                # truncated line in his chat log is this
                                # path's output, cut off mid-sentence:
                                #   "...ya ODFV-reader ke liye koi built-in
                                #    support milti hai; is baare mein main
                                #    apne knowledge base ya official docs
                                #    check karke ya aapse"          <-- ends here
                                #   "...Agar aap chahein, toh main"  <-- ends here
                                # Both start with this prompt's own
                                # "Mujhe ... confirm nahi..." shape. The
                                # prompt asks for ONE or TWO natural
                                # Hinglish sentences naming an unsupported
                                # claim AND what could be done about it;
                                # that is routinely 250-400 tokens in
                                # Devanagari-heavy Hinglish, so a 200-token
                                # ceiling cut the model off mid-clause
                                # every time. The reserve exists precisely
                                # so the FINAL user-visible reply always
                                # has room -- capping it below what the
                                # sentence needs defeats that.
                                max_tokens=700,
                                level="response_generation",
                            )).strip() or response
                            log_event("brain", "flagged response replaced with JARVIS's own worded uncertainty (no canned string)", level="info")
                        except Exception:
                            log_event("brain", "response flagged but no budget left to reword it -- delivering the draft rather than a canned hedge", level="warning")
                    else:
                        log_event("brain", "response was flagged but is backed by real tool/search data -- delivering it as-is (grounding checker false positive)", level="info")

            self.last_brain_decision = {
                "mode": "llm",
                "status": "completed",
                "stayed_within_brief": grounding.stayed_within_brief,
            }

            # Bug 16 fix (2026-09-11 trace-log audit): strip harmony-
            # format channel-separator artifacts ("【analysis】" etc.)
            # that leaked into user-facing text twice in the audited
            # log -- gpt-oss models internally separate a reasoning/
            # "analysis" channel from the final-answer channel, and
            # this bracket marker is a leftover fragment of that
            # separation surfacing where it shouldn't. Conservative:
            # only strips the exact observed marker shape, doesn't
            # touch any other bracketed text a real response might
            # legitimately contain.
            response = re.sub(r"【[^】]{0,40}】", "", response).strip()

            response = self._record_action_response(
                mode="llm",
                status="completed",
                response=response,
            )

            self._trace(
                user_input,
                response,
                route,
                perception,
                started,
                True,
            )
            return response

        except Exception as exc:
            # Bug 7 REAL fix (2026-09-11, going beyond just the
            # friendly-message patch from before): if this specifically
            # was an output-token budget shortfall, try ONE graceful
            # retry with whatever budget genuinely remains, instead of
            # giving up outright. Only for THIS exact failure mode
            # (never call-count or per-level budget exhaustion, which
            # mean "no calls left at all" -- retrying there would just
            # raise the identical exception again).
            exc_text = str(exc)
            retried_response = None
            if "output-token budget" in exc_text.lower():
                try:
                    remaining = int(self.llm.budget_status().get("remaining_output_tokens", 0)) if hasattr(self.llm, "budget_status") else 0
                except Exception:
                    remaining = 0
                if remaining >= _MIN_COMPLETE_REPLY_TOKENS:
                    try:
                        retried_response = str(self.llm.generate_response(
                            system_prompt=system_prompt,
                            user_input=context_prompt + "\n\n(Reply in ONE short sentence -- very little space left this turn.)",
                            max_tokens=remaining,
                            level="response_generation",
                        )).strip()
                        if retried_response.startswith("[LLM unavailable:") or retried_response.startswith("[Model Generation Error"):
                            retried_response = None
                    except Exception:
                        retried_response = None

            if retried_response:
                # HALLUCINATION BUG (2026-09-12, UK's trace: asked for
                # today's Nifty price during a budget-exhaustion retry,
                # got back a confident, completely made-up number).
                # This retry call above passes NO tools and NO grounding
                # check -- it just tells the LLM "answer in one short
                # sentence" with whatever's left of the token budget, so
                # for anything needing live/factual data the model fills
                # the gap with a plausible-looking guess. Route the
                # retried reply through the same grounding check the
                # normal path uses before accepting it.
                try:
                    retry_grounding = check_response_grounding(retried_response, brief, relations_extracted_this_turn=0)
                    retry_tool_backed = _turn_was_tool_backed(getattr(self, "last_tool_call_trace", None))
                except Exception:
                    retry_grounding = None
                    retry_tool_backed = True  # fail open to the original retried_response rather than erroring the whole turn
                if retry_grounding is not None and not retry_grounding.stayed_within_brief and not retry_tool_backed:
                    response = (
                        "Is turn mein iska pakka jawab dene ke liye mere paas na toh space bacha na verified data -- "
                        "guess nahi dena chahta, dobara poocho ya thodi der mein try karo."
                    )
                    log_event("brain", "budget-retry reply was unverifiable and not tool-backed -- replaced with an honest decline instead of risking a fabricated answer", level="warning")
                else:
                    response = retried_response
                    log_event("brain", f"budget-exhaustion retry succeeded with a shorter reply ({remaining} tokens)", level="info")
            # THE ACTUAL BUG (2026-09-11 trace-log audit, Bug 6 + 7):
            # this used to put the raw technical exception text
            # DIRECTLY into the user-facing response -- e.g. "[Brain
            # Thinking Error: LLM output-token budget exceeded:
            # requested 512 tokens but only 42 remain of the 2700-
            # token turn budget]" appeared verbatim in the chat. The
            # technical detail still goes into `error` below (visible
            # in cli.py's workflow panel / monitor.py's log tail --
            # exactly where debugging should look), but what UK sees
            # is now a plain, honest, natural apology, never raw
            # exception text.
            elif "budget" in exc_text.lower() or "token" in exc_text.lower():
                response = (
                    "Is turn mein jawab poora likhne ke liye jitni space chahiye thi utni nahi bach paayi -- "
                    "chhota sawaal dobara pooch lo, ya thodi der mein try karo."
                )
            else:
                response = "Mujhe abhi jawab dene mein dikkat aa rahi hai -- kripya thodi der baad try karo."

            self.last_brain_decision = {
                "mode": "llm",
                "status": "failed",
                "error": str(exc),
            }

            self._record_action_response(
                mode="llm",
                status="failed",
                response=response,
                error=str(exc),
            )

            self._trace(
                user_input,
                response,
                route,
                perception,
                started,
                True,
            )
            return response

    # =============================================================
    # ASYNC LEARNING HAND-OFF
    # =============================================================

    def _enqueue_learning(
        self,
        event_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
        source: Optional[str],
        importance: float,
    ) -> None:
        """
        Push one completed turn onto the ordered background learning
        queue. If the queue isn't running for any reason (e.g. start()
        was never called), falls back to the old synchronous path so a
        turn is never silently dropped -- it just costs latency instead,
        exactly like before this change.
        """
        job = {
            "event_type": event_type,
            "context": context,
            "action": action,
            "outcome": outcome,
            "source": source,
            "importance": importance,
            "build_knowledge": True,
            "auto_accept": self.auto_accept_knowledge,
        }

        if self._learning_queue.is_alive():
            if not self._learning_queue.submit(job):
                log_event("brain", "learning queue rejected job (full); running inline as fallback.", level="warning")
                self._run_learning_job(job)
        else:
            # Queue never started (e.g. Brain used standalone/tests) —
            # keep behaviour correct by falling back to synchronous.
            self._run_learning_job(job)

    def _run_learning_job(self, job: Dict[str, Any]) -> None:
        """Executed on the background learning-queue thread (or inline
        as a fallback). Never lets a learning failure reach the user."""
        self._set_learning_active(True)
        try:
            self.process_experience(
                event_type=job["event_type"],
                context=job["context"],
                action=job["action"],
                outcome=job["outcome"],
                source=job["source"],
                importance=job["importance"],
                build_knowledge=job["build_knowledge"],
                auto_accept=job["auto_accept"],
            )
        except Exception as exp_err:
            log_event("brain", f"could not process experience: {exp_err}", level="error")
        finally:
            self._set_learning_active(False)

    def _set_learning_active(self, active: bool) -> None:
        """Best-effort mirror of live learning-worker activity into the
        state bus, so monitor.py can show LEARNING as distinct from the
        synchronous IDLE/PERCEIVING/INDEXING/EXECUTING turn pipeline --
        the background worker legitimately overlaps with the next turn."""
        try:
            from ..runtime.state_bus import get_state_bus

            bus = get_state_bus(create=False)
            if bus is not None:
                bus.update_learning(status=self._learning_queue.status(), active=active)
        except Exception:
            pass

    # =============================================================
    # PROCESS EXPERIENCE
    # =============================================================

    def process_experience(
        self,
        event_type: str,
        context: Optional[Dict[str, Any]] = None,
        action: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        importance: float = 0.5,
        build_knowledge: bool = True,
        auto_accept: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Process one completed experience.

        Flow:
            Brain -> ExperienceEngine -> LearningCoordinator ->
            SelfEvaluator -> KnowledgeBuilder -> acceptance

        `auto_accept` defaults to self.auto_accept_knowledge when not
        explicitly passed, so the "built but never persisted" bug
        can't silently recur.
        """
        if self.experience is None:
            raise RuntimeError("ExperienceEngine is not connected.")

        if auto_accept is None:
            auto_accept = self.auto_accept_knowledge

        started_at = time.time()

        # =========================================================
        # 1. EXPERIENCE ENGINE
        # =========================================================
        experience_result = self.experience.process(
            event_type=event_type,
            context=context or {},
            action=action or {},
            outcome=outcome or {},
            source=source,
            importance=importance,
        )

        if not isinstance(experience_result, dict):
            raise RuntimeError("ExperienceEngine returned an invalid result.")

        experience = experience_result.get("experience", {})

        # THE IDLE-LOOP BUG (2026-09-13, UK: "idle me kuchh kaam nahi
        # hota -- na learning, na consolidation, na pattern matching").
        #
        # ExperienceEngine processes a turn but never PERSISTS it as an
        # episode -- verified by grep: nothing in experience_engine.py
        # touches episodic memory at all. So every chat turn went into
        # the learning queue (monitor showed processed=1118, which is
        # why this looked healthy) while the episodic store itself
        # received nothing new. Idle consolidation reads USER_CHAT
        # episodes, found only a handful of stale ones from an earlier
        # session -- all already tagged "consolidated" -- and reported
        # examined=25 candidates=0 forever.
        #
        # A standalone repro confirmed the consolidator's own logic is
        # correct: given fresh episodes it promotes them, and it picks
        # up new ones on later runs. The defect was purely that nothing
        # was feeding it. Classic "built but never wired".
        #
        # Guarded and best-effort: a persistence failure must never
        # break a turn that already answered the user.
        if self.memory is not None and event_type:
            try:
                self.memory.remember_experience(
                    event_type=event_type,
                    context=context or {},
                    action=action or {},
                    outcome=outcome or {},
                    importance=importance,
                    source=source,
                )
            except Exception as persist_err:
                log_event("brain", f"episode persistence failed (idle consolidation will miss this turn): {persist_err}", level="warning")

        # =========================================================
        # 2. LEARNING COORDINATOR (preferred path)
        # =========================================================
        learning_result = None

        if self.learning is not None and build_knowledge:
            learn_method = getattr(self.learning, "learn", None)
            if not callable(learn_method):
                raise RuntimeError("LearningCoordinator does not expose learn().")

            learning_result = learn_method(
                experience=experience,
                auto_accept=auto_accept,
            )

        # =========================================================
        # 3. COMPATIBILITY FALLBACK (no LearningCoordinator connected)
        # =========================================================
        elif self.learning is None and build_knowledge:
            evaluation = None
            if self.evaluator is not None:
                evaluation = self.evaluator.evaluate(experience)

            knowledge = None
            if self.knowledge_builder is not None and evaluation is not None:
                knowledge = self.knowledge_builder.build(
                    experience=experience,
                    evaluation=evaluation,
                )

            accepted = False
            # THIS is the part that was previously missing: without
            # it, `knowledge` was created but never written to the
            # persistent knowledge table.
            if (
                auto_accept
                and knowledge is not None
                and self.knowledge_builder is not None
            ):
                knowledge_id = (
                    knowledge.get("id")
                    if isinstance(knowledge, dict)
                    else getattr(knowledge, "id", None)
                )
                accept_method = getattr(self.knowledge_builder, "accept", None)
                if knowledge_id is not None and callable(accept_method):
                    try:
                        accept_method(knowledge_id)
                        accepted = True
                    except Exception as accept_err:
                        log_event("brain", f"could not auto-accept knowledge: {accept_err}", level="warning")

            learning_result = {
                "success": True,
                "experience": experience,
                "evaluation": evaluation,
                "knowledge": knowledge,
                "accepted": accepted,
                "duration": 0.0,
                "timestamp": time.time(),
            }

        # =========================================================
        # 4. BUILD RESULT
        # =========================================================
        evaluation = None
        knowledge = None
        accepted = False

        if isinstance(learning_result, dict):
            evaluation = learning_result.get("evaluation")
            knowledge = learning_result.get("knowledge")
            accepted = bool(learning_result.get("accepted", False))

        result = {
            "type": "BRAIN_EXPERIENCE_CYCLE",
            "success": True,
            "experience": experience,
            "learning": learning_result,
            "evaluation": evaluation,
            "knowledge": knowledge,
            "accepted": accepted,
            "episode_id": experience_result.get("episode_id"),
            "duration": time.time() - started_at,
            "timestamp": time.time(),
        }

        # OUTCOME FEEDBACK positive side (2026-09-11 roadmap Phase 6):
        # when SelfEvaluator judges the WHOLE turn a success, lightly
        # reinforce the facts that were actually surfaced to the LLM
        # for it (self.last_turn_fact_ids, captured right after
        # build_response_brief()). Distinct from NativeReasoner's
        # existing reinforcement (which fires immediately on a
        # successful NATIVE direct-recall hit, a different code path)
        # -- this is the LLM-answered-turn half that never existed
        # before: those facts previously got zero feedback regardless
        # of whether the turn actually went well.
        try:
            if isinstance(evaluation, dict) and evaluation.get("success") and self.last_turn_fact_ids:
                semantic = getattr(self.memory, "semantic", None)
                if semantic is not None and hasattr(semantic, "reinforce"):
                    for kid in self.last_turn_fact_ids:
                        try:
                            semantic.reinforce(kid, confidence_delta=0.02)
                        except Exception:
                            continue
        except Exception:
            pass

        # ---------------------------------------------------------
        # POST-RESPONSE REASONING (response -> reasoning -> experience
        # -> learning): the structured 11-question self-reflection
        # cycle, built natively from the evaluation/experience data
        # already computed above -- zero extra LLM calls per turn.
        # See core/learning/post_response_reasoning.py.
        try:
            reasoning_trace = build_reasoning_trace(experience, evaluation, accepted, recent_traces=self.last_reasoning_traces)
            result["reasoning"] = reasoning_trace.as_dict()
            self.last_reasoning_traces.append(result["reasoning"])
            if len(self.last_reasoning_traces) > 50:
                self.last_reasoning_traces = self.last_reasoning_traces[-50:]
            # THE ACTUAL FEEDBACK LOOP: when the reasoning cycle decides
            # this recommendation is genuinely worth adopting (repeated,
            # not a one-off), JARVIS writes a SELF-authored rule into
            # memory -- distinct from UserRuleStore's user-stated rules
            # -- so future turns' response briefs are actually
            # influenced by what JARVIS itself has learned, not just a
            # judgment that gets logged and forgotten.
            # THE ACTUAL FEEDBACK LOOP (UK's explicit ask: JARVIS may
            # author its own rules from repeated evidence, exactly like
            # a real organism would -- but MUST NOT apply one until UK
            # has verified it. Previously this wrote straight to memory
            # and get_self_authored_rules() read it back on the very
            # next turn with zero human confirmation in between -- a
            # self-proposed rule was silently already governing
            # responses before anyone ever saw it. Stored the same way,
            # just tagged "pending_confirmation" instead of live --
            # see get_self_authored_rules() (only reads "confirmed"
            # ones) and Brain.confirm_self_rule()/reject_self_rule()/
            # list_pending_self_rules() below, reachable via cli.py's
            # /pending_rules, /confirm_rule, /reject_rule.
            if reasoning_trace.adopt_as_learning:
                try:
                    semantic = getattr(self.memory, "semantic", None)
                    if semantic is not None and hasattr(semantic, "remember"):
                        # UNIQUE PREDICATE (fix for a real collision bug
                        # found 2026-09-11: predicate was previously just
                        # f"learned_behavior_{mode}" -- shared by EVERY
                        # distinct proposal under the same mode, so a
                        # second, different next_time_different text
                        # would silently overwrite the first one's row,
                        # including union-merging its tags (a rejected
                        # row could end up tagged BOTH "rejected" and
                        # "pending_confirmation" at once). Hashing the
                        # actual recommendation text into the predicate
                        # gives each distinct proposal its own row;
                        # re-proposing the IDENTICAL text still correctly
                        # reinforces the same row via remember()'s normal
                        # update path.
                        rule_key = hashlib.sha1(
                            reasoning_trace.next_time_different.strip().lower().encode("utf-8")
                        ).hexdigest()[:10]
                        predicate = f"learned_behavior_{reasoning_trace.mode}_{rule_key}"

                        # REJECTION MEMORY (UK's explicit ask: "reject
                        # kiya to dubara wahi rule na banaye"). Previously
                        # reject_self_rule() hard-deleted the row, so
                        # nothing remembered a rejection ever happened --
                        # the identical recommendation would just get
                        # re-proposed the next time the pattern repeated
                        # 3x, forcing UK to reject the same thing forever.
                        # reject_self_rule() now tombstones instead of
                        # deleting (tags=["rejected"], see below) -- check
                        # for that tombstone BEFORE writing a new proposal.
                        already_rejected = False
                        try:
                            existing_rows = semantic.find(subject="jarvis_self_rule", predicate=predicate) or []
                            already_rejected = any("rejected" in (getattr(r, "tags", None) or []) for r in existing_rows)
                        except Exception:
                            already_rejected = False

                        if already_rejected:
                            log_event("brain", f"self-authored rule SUPPRESSED (previously rejected by UK, not re-proposing): {reasoning_trace.next_time_different}", level="info")
                        else:
                            # SHADOW-EVIDENCE AUTO-ADOPT (2026-09-12,
                            # UK's explicit ask #1: give behavioral
                            # rules the SAME treatment self-authored
                            # PATTERNS already get in
                            # pattern_synthesis.shadow_test_pending_
                            # patterns -- otherwise "self-evolution"
                            # stops dead at a manual /confirm_rule and
                            # JARVIS can never actually adapt on its
                            # own). A rule re-proposed by INDEPENDENT
                            # reasoning cycles, over and over, on
                            # genuinely separate turns, is exactly the
                            # accumulating behavioural evidence UK
                            # described (the dog that adapts without
                            # being told). Counted here, and at
                            # threshold the rule confirms ITSELF.
                            #
                            # Never silent, always reversible: the
                            # promotion is logged, surfaced in
                            # monitor.py/CLI, and /reject_rule still
                            # works afterwards exactly as before.
                            prior_proposals = 0
                            try:
                                for row in (semantic.find(subject="jarvis_self_rule", predicate=predicate) or []):
                                    prior_proposals = max(prior_proposals, int(getattr(row, "evidence_count", 1) or 1))
                            except Exception:
                                prior_proposals = 0

                            auto_adopt = prior_proposals + 1 >= RULE_AUTO_ADOPT_THRESHOLD
                            rule_knowledge = semantic.remember(
                                subject="jarvis_self_rule",
                                predicate=predicate,
                                value=reasoning_trace.next_time_different,
                                confidence=0.9 if auto_adopt else 0.75,
                                importance=0.6,
                                source="self_reasoning",
                                tags=["self_authored", "confirmed", "auto_adopted"] if auto_adopt else ["self_authored", "pending_confirmation"],
                                namespace="SYSTEM",
                                # JARVIS's own inferred conclusion, nothing
                                # external checked it yet -- must read as
                                # unverified until UK reviews it via
                                # /confirm_rule (see confirm_self_rule()
                                # below, which upgrades this to
                                # "user_stated" on confirmation).
                                source_type="llm_unverified",
                            )
                            if auto_adopt:
                                self.auto_adopted_rules.append({
                                    "rule": reasoning_trace.next_time_different,
                                    "knowledge_id": rule_knowledge.knowledge_id,
                                    "independent_proposals": prior_proposals + 1,
                                    "timestamp": time.time(),
                                })
                                log_event("brain", f"self-authored rule AUTO-ADOPTED after {prior_proposals + 1} independent proposals (reversible via /reject_rule): {reasoning_trace.next_time_different}", level="info")
                            # EVIDENCE/TRACEABILITY (UK's explicit ask:
                            # "clarify kare ki kyun banaya, kya reason
                            # tha"). Previously only the terse conclusion
                            # (next_time_different) was persisted -- the
                            # supporting Q&A (what_and_why/strategy_
                            # evidence/evidence_reliability/change_reason)
                            # lived only in the ephemeral trace log and
                            # was gone on restart. Stored as a companion
                            # record under the SAME memory store, linked
                            # by the rule's own knowledge_id as the
                            # predicate -- no new schema needed, and
                            # explain_self_rule() below reads it back.
                            try:
                                semantic.remember(
                                    subject="jarvis_self_rule_evidence",
                                    predicate=rule_knowledge.knowledge_id,
                                    value=json.dumps({
                                        "what_and_why": reasoning_trace.what_and_why,
                                        "outcome_gap_reason": reasoning_trace.outcome_gap_reason,
                                        "strategy_evidence": reasoning_trace.strategy_evidence,
                                        "change_reason": reasoning_trace.change_reason,
                                        "evidence_reliability": reasoning_trace.evidence_reliability,
                                        "repeated_occurrences": "3+ matching turns in the last 20 (see adopt_as_learning threshold)",
                                    }, ensure_ascii=False),
                                    confidence=0.75,
                                    importance=0.6,
                                    source="self_reasoning",
                                    tags=["self_rule_evidence"],
                                    namespace="SYSTEM",
                                    source_type="llm_unverified",
                                )
                            except Exception as exc:
                                log_event("brain", f"could not write self-rule evidence record: {exc}", level="warning")
                            log_event("brain", f"self-authored rule PROPOSED, awaiting UK's confirmation (/pending_rules): {reasoning_trace.next_time_different}", level="info")
                except Exception as exc:
                    log_event("brain", f"could not write self-authored rule: {exc}", level="warning")
            # Aggregate LLM cost-awareness (see DependencyMetrics.
            # record_retry_cost) -- this is what turns "was that retry
            # worth it" from a per-turn guess into a measurable,
            # growing answer JARVIS can actually consult.
            llm_cost = reasoning_trace.llm_cost or {}
            if llm_cost.get("retry_used"):
                self.dependency_metrics.record_retry_cost(
                    retry_used=True, retry_paid_off=bool(llm_cost.get("retry_paid_off")),
                )
                self._check_retry_value_evolution()
        except Exception as exc:
            log_event("brain", f"post-response reasoning failed: {exc}", level="warning")

        self._finish_cycle(result)
        self._emit("BRAIN_EXPERIENCE_PROCESSED", result)

        return result

    # =============================================================
    # LEARN
    # =============================================================

    def learn(self, experience: Dict[str, Any], auto_accept: Optional[bool] = None) -> Dict[str, Any]:
        """Direct learning entry point for an already-structured experience."""
        if not isinstance(experience, dict):
            raise TypeError("experience must be a dictionary.")

        if self.learning is None:
            raise RuntimeError("LearningCoordinator is not connected.")

        method = getattr(self.learning, "learn", None)
        if not callable(method):
            raise RuntimeError("LearningCoordinator does not expose learn().")

        if auto_accept is None:
            auto_accept = self.auto_accept_knowledge

        result = method(experience=experience, auto_accept=auto_accept)
        self._emit("BRAIN_LEARNING_COMPLETED", result)
        return result

    # =============================================================
    # EVALUATE
    # =============================================================

    def evaluate(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        if self.learning is not None:
            method = getattr(self.learning, "evaluate", None)
            if callable(method):
                return method(experience)

        if self.evaluator is None:
            raise RuntimeError("SelfEvaluator is not connected.")

        return self.evaluator.evaluate(experience)

    # =============================================================
    # BUILD KNOWLEDGE
    # =============================================================

    def build_knowledge(
        self,
        experience: Dict[str, Any],
        evaluation: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.learning is not None:
            method = getattr(self.learning, "build_knowledge", None)
            if callable(method):
                return method(experience=experience, evaluation=evaluation)

        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")

        if evaluation is None:
            if self.evaluator is None:
                raise RuntimeError("SelfEvaluator is not connected.")
            evaluation = self.evaluator.evaluate(experience)

        return self.knowledge_builder.build(experience=experience, evaluation=evaluation)

    # =============================================================
    # ACCEPT / REJECT KNOWLEDGE
    # =============================================================

    def accept_knowledge(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        if self.learning is not None:
            method = getattr(self.learning, "accept_knowledge", None)
            if callable(method):
                result = method(knowledge_id)
                self._emit("BRAIN_KNOWLEDGE_ACCEPTED", result)
                return result

        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")

        result = self.knowledge_builder.accept(knowledge_id)
        self._emit("BRAIN_KNOWLEDGE_ACCEPTED", result)
        return result

    def reject_knowledge(self, knowledge_id: str, reason: str = "") -> Optional[Dict[str, Any]]:
        if self.learning is not None:
            method = getattr(self.learning, "reject_knowledge", None)
            if callable(method):
                result = method(knowledge_id=knowledge_id, reason=reason)
                self._emit("BRAIN_KNOWLEDGE_REJECTED", result)
                return result

        if self.knowledge_builder is None:
            raise RuntimeError("KnowledgeBuilder is not connected.")

        result = self.knowledge_builder.reject(knowledge_id=knowledge_id, reason=reason)
        self._emit("BRAIN_KNOWLEDGE_REJECTED", result)
        return result

    # =============================================================
    # SELF-AUTHORED RULES -- propose (automatic, see the post-response
    # reasoning block above) / confirm / reject (UK only). A self-
    # authored rule never reaches get_self_authored_rules() (and
    # therefore never influences a response) until confirm_self_rule()
    # has been called on it -- see response_brief.py's
    # get_self_authored_rules() docstring for why.
    # =============================================================

    def list_pending_self_rules(self) -> List[Dict[str, Any]]:
        """Self-authored rules JARVIS has proposed but UK has not yet
        reviewed. Read-only."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "find"):
            return []
        try:
            items = semantic.find(subject="jarvis_self_rule") or []
        except Exception:
            return []
        pending = [
            item for item in items
            if "pending_confirmation" in (getattr(item, "tags", None) or [])
            and "confirmed" not in (getattr(item, "tags", None) or [])
            and "rejected" not in (getattr(item, "tags", None) or [])
        ]
        pending.sort(key=lambda i: getattr(i, "created_at", 0), reverse=True)
        return [
            {
                "knowledge_id": getattr(item, "knowledge_id", None),
                "rule": getattr(item, "value", None),
                "predicate": getattr(item, "predicate", None),
                "confidence": getattr(item, "confidence", None),
                "created_at": getattr(item, "created_at", None),
                "source_type": getattr(item, "source_type", "unknown"),
            }
            for item in pending
        ]

    def confirm_self_rule(self, knowledge_id: str) -> Dict[str, Any]:
        """UK verifies a self-authored rule -- ONLY after this does it
        start influencing responses (get_self_authored_rules() starts
        returning it). remember() merges tags rather than replacing
        them (see SemanticMemory.remember()), so the old
        "pending_confirmation" tag harmlessly lingers alongside the new
        "confirmed" one -- both list_pending_self_rules() and
        get_self_authored_rules() key off "confirmed" being present,
        not "pending_confirmation" being absent."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "get"):
            return {"status": "error", "message": "Semantic memory not connected."}
        item = semantic.get(knowledge_id)
        if item is None or getattr(item, "subject", None) != "jarvis_self_rule":
            return {"status": "not_found", "knowledge_id": knowledge_id}
        try:
            semantic.remember(
                subject=item.subject, predicate=item.predicate, value=item.value,
                confidence=item.confidence, importance=item.importance,
                source=item.source, tags=["confirmed"], namespace=item.namespace,
                # UK personally reviewed and approved this -- that IS a
                # human verification step, so this is exactly the
                # "llm_unverified -> confirmed" upgrade path the
                # provenance system is for. remember()'s merge logic
                # (same value, source_type rank comparison) makes this
                # an upgrade only, never a downgrade.
                source_type="user_stated",
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        self._emit("BRAIN_SELF_RULE_CONFIRMED", {"knowledge_id": knowledge_id, "rule": item.value})
        return {"status": "confirmed", "knowledge_id": knowledge_id, "rule": item.value}

    def reject_self_rule(self, knowledge_id: str) -> Dict[str, Any]:
        """UK declines a self-authored rule. FIX (2026-09-11, UK's
        explicit ask): previously this hard-deleted the row via
        semantic.forget(), which meant nothing remembered the
        rejection ever happened -- the identical recommendation would
        simply get re-proposed the next time its trigger pattern
        repeated 3x, forcing UK to reject the same thing over and
        over. Now the row is TOMBSTONED instead: tags are replaced
        (not merged -- see SemanticMemory.set_tags(), since remember()
        always unions and would leave a stale "pending_confirmation"
        tag sitting next to "rejected" forever) with ["self_authored",
        "rejected"], and the adopt_as_learning block above checks for
        exactly this tombstone before writing a new proposal with the
        same predicate, so a rejected rule stays rejected."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "get"):
            return {"status": "error", "message": "Semantic memory not connected."}
        item = semantic.get(knowledge_id)
        if item is None or getattr(item, "subject", None) != "jarvis_self_rule":
            return {"status": "not_found", "knowledge_id": knowledge_id}
        try:
            if hasattr(semantic, "set_tags"):
                semantic.set_tags(knowledge_id, ["self_authored", "rejected"])
            else:
                # Older SemanticMemory without set_tags -- fall back to
                # the old hard-delete rather than error out, but this
                # means the rejection won't be remembered.
                semantic.forget(knowledge_id)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        result = {"status": "rejected", "knowledge_id": knowledge_id, "rule": item.value}
        self._emit("BRAIN_SELF_RULE_REJECTED", result)
        return result

    def explain_self_rule(self, knowledge_id: str) -> Dict[str, Any]:
        """UK asks "yeh rule kyun banaya" -- reconstructs the actual
        justification (what_and_why / strategy_evidence / evidence_
        reliability / change_reason) from the linked evidence record
        written alongside the rule proposal, instead of only being
        able to show the terse final recommendation text. See the
        adopt_as_learning block above for where this evidence record
        is written (subject="jarvis_self_rule_evidence", predicate=
        this rule's own knowledge_id)."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "get"):
            return {"status": "error", "message": "Semantic memory not connected."}
        item = semantic.get(knowledge_id)
        if item is None or getattr(item, "subject", None) != "jarvis_self_rule":
            return {"status": "not_found", "knowledge_id": knowledge_id}
        evidence: Dict[str, Any] = {}
        try:
            evidence_rows = semantic.find(subject="jarvis_self_rule_evidence", predicate=knowledge_id) or []
            if evidence_rows:
                raw = evidence_rows[0].value
                if isinstance(raw, dict):
                    evidence = raw
                elif isinstance(raw, str):
                    try:
                        evidence = json.loads(raw)
                    except Exception:
                        evidence = {"raw": raw}
        except Exception:
            evidence = {}
        tags = getattr(item, "tags", None) or []
        status = "confirmed" if "confirmed" in tags else ("rejected" if "rejected" in tags else "pending")
        return {
            "knowledge_id": knowledge_id,
            "rule": item.value,
            "status": status,
            "confidence": item.confidence,
            "source_type": getattr(item, "source_type", "unknown"),
            "created_at": item.created_at,
            "evidence": evidence or {"note": "no linked evidence record found (rule may predate the evidence-tracking fix)"},
        }

    def list_standing_instructions(self) -> List[Dict[str, Any]]:
        """All active daily standing instructions (see core/autonomy/
        standing_instructions.py). Read-only."""
        try:
            return self.standing_instructions.list_active()
        except Exception:
            return []

    def remove_standing_instruction(self, knowledge_id: str) -> Dict[str, Any]:
        """UK deletes a standing instruction outright (unlike a
        self-authored rule, there's nothing to "reject then remember
        the rejection" here -- UK stated this one directly, so
        removing it is just removing it)."""
        try:
            removed = self.standing_instructions.remove(knowledge_id)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        result = {"status": "removed" if removed else "not_found", "knowledge_id": knowledge_id}
        self._emit("STANDING_INSTRUCTION_REMOVED", result)
        return result

    def save_verified_fact(self, subject: str, predicate: str, value: str, source_type: str = "llm_unverified") -> Dict[str, Any]:
        """Persist a fact the LLM looked up (or already knew) into
        long-term semantic memory. See core/orchestration/
        tool_registry.py's save_verified_fact tool -- deliberately
        NOT called automatically after every browser_search. UK's
        explicit ask (2026-09-11): most searched facts are for
        answering the immediate question only and must stay
        conversational/ephemeral (already captured in episodic memory
        as part of the normal per-turn experience record -- see
        ExperienceEngine -- which is temporary/session-scoped context,
        not a durable fact store). This method only runs when UK
        explicitly asked to save/remember something, so semantic
        memory doesn't fill with one-off lookups nobody asked to keep."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "remember"):
            return {"status": "error", "message": "Semantic memory not connected."}
        resolved_source_type = source_type if source_type in ("verified", "llm_unverified") else "llm_unverified"
        try:
            knowledge = semantic.remember(
                subject=subject, predicate=predicate, value=value,
                confidence=0.85, importance=0.6,
                source="llm_explicit_save",
                tags=["llm_saved_on_request"],
                namespace="WORLD",
                source_type=resolved_source_type,
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        result = {
            "status": "saved", "knowledge_id": knowledge.knowledge_id,
            "subject": subject, "predicate": predicate, "value": value,
            "source_type": knowledge.source_type,
        }
        self._emit("BRAIN_FACT_SAVED_ON_REQUEST", result)
        return result

    def list_contested_facts(self) -> List[Dict[str, Any]]:
        """Facts where a less-trusted source tried to overwrite a
        more-trusted one and was held back (see SemanticMemory.
        remember()'s M6 contradiction-resolution branch). Read-only."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "list_contested_facts"):
            return []
        try:
            items = semantic.list_contested_facts()
        except Exception:
            return []
        out = []
        for item in items:
            contested = [h for h in (getattr(item, "history", None) or []) if isinstance(h, dict) and h.get("contested_candidate")]
            latest = contested[-1] if contested else {}
            out.append({
                "knowledge_id": getattr(item, "knowledge_id", None),
                "subject": getattr(item, "subject", None),
                "predicate": getattr(item, "predicate", None),
                "current_value": getattr(item, "value", None),
                "current_source_type": getattr(item, "source_type", "unknown"),
                "proposed_value": latest.get("proposed_value"),
                "proposed_source_type": latest.get("proposed_source_type"),
            })
        return out

    def resolve_contested_fact(self, knowledge_id: str, accept_new_value: bool) -> Dict[str, Any]:
        """UK's decision on a contested fact -- see list_contested_facts()."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "resolve_contested_fact"):
            return {"status": "error", "message": "Semantic memory not connected."}
        try:
            item = semantic.resolve_contested_fact(knowledge_id, accept_new_value=accept_new_value)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        if item is None:
            return {"status": "not_found", "knowledge_id": knowledge_id}
        result = {"status": "resolved", "knowledge_id": knowledge_id, "accepted_new_value": accept_new_value, "current_value": item.value}
        self._emit("BRAIN_CONTESTED_FACT_RESOLVED", result)
        return result

    def get_recent_auto_adopted_rules(self) -> List[Dict[str, Any]]:
        """Behavioral rules that confirmed THEMSELVES after enough
        independent reasoning cycles reached the same conclusion (see
        RULE_AUTO_ADOPT_THRESHOLD) -- the behavioral-rule counterpart
        to pattern auto-promotion. Surfaced deliberately: UK's
        condition for self-evolution was that it never be silent."""
        return list(self.auto_adopted_rules)

    def get_recent_auto_promotions(self) -> List[Dict[str, Any]]:
        """Self-authored patterns that graduated to confirmed on their
        OWN accumulated evidence (see pattern_synthesis.py's
        shadow_test_pending_patterns) rather than a manual /confirm_pattern
        -- UK's explicit ask that this always stay visible, never silent."""
        return list(getattr(self.semantic_understanding, "_last_auto_promotions", None) or [])

    def list_pending_patterns(self) -> List[Dict[str, Any]]:
        """Self-authored EXTRACTION PATTERNS awaiting UK's review --
        see core/learning/pattern_synthesis.py's module docstring.
        Each one already passed sandbox testing (compiles, matches its
        examples, doesn't false-positive on ordinary conversation)
        before ever reaching this list; UK's review is about whether
        it's actually a good fit, not a safety check (that already ran)."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "find"):
            return []
        try:
            items = semantic.find(subject="jarvis_learned_pattern") or []
        except Exception:
            return []
        pending = [
            item for item in items
            if "pending_confirmation" in (getattr(item, "tags", None) or [])
            and "confirmed" not in (getattr(item, "tags", None) or [])
            and "rejected" not in (getattr(item, "tags", None) or [])
        ]
        out = []
        for item in pending:
            data = item.value if isinstance(item.value, dict) else {}
            out.append({
                "knowledge_id": item.knowledge_id,
                "regex": data.get("regex"),
                "target_predicate": data.get("target_predicate"),
                "gap_description": data.get("gap_description"),
                "example_inputs": data.get("example_inputs"),
            })
        return out

    def confirm_pattern(self, knowledge_id: str) -> Dict[str, Any]:
        """UK approves a self-authored extraction pattern -- ONLY after
        this does semantic_understanding/engine.py's _try_learned_
        patterns() start trying it live (still timeout-guarded even
        then, see pattern_synthesis.py)."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "get"):
            return {"status": "error", "message": "Semantic memory not connected."}
        item = semantic.get(knowledge_id)
        if item is None or getattr(item, "subject", None) != "jarvis_learned_pattern":
            return {"status": "not_found", "knowledge_id": knowledge_id}
        try:
            semantic.remember(
                subject=item.subject, predicate=item.predicate, value=item.value,
                confidence=item.confidence, importance=item.importance,
                source=item.source, tags=["confirmed"], namespace=item.namespace,
                source_type="user_stated",
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        self._emit("BRAIN_PATTERN_CONFIRMED", {"knowledge_id": knowledge_id})
        return {"status": "confirmed", "knowledge_id": knowledge_id}

    def reject_pattern(self, knowledge_id: str) -> Dict[str, Any]:
        """UK declines a self-authored extraction pattern -- tombstoned
        (same pattern as reject_self_rule), never re-proposed identically."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        if semantic is None or not hasattr(semantic, "get"):
            return {"status": "error", "message": "Semantic memory not connected."}
        item = semantic.get(knowledge_id)
        if item is None or getattr(item, "subject", None) != "jarvis_learned_pattern":
            return {"status": "not_found", "knowledge_id": knowledge_id}
        try:
            if hasattr(semantic, "set_tags"):
                semantic.set_tags(knowledge_id, ["self_authored_pattern", "rejected"])
            else:
                semantic.forget(knowledge_id)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        self._emit("BRAIN_PATTERN_REJECTED", {"knowledge_id": knowledge_id})
        return {"status": "rejected", "knowledge_id": knowledge_id}

    def start_remote_access(self) -> Dict[str, Any]:
        """UK's explicit ask (2026-09-12): JARVIS should know about its
        own remote-access capability and be able to trigger it from
        chat, not just via a separate script UK has to remember to run.
        Only starts the ngrok TUNNEL here -- if this is being called at
        all, the backend (this very process) is obviously already
        running, and cli.py's dev mode already started Vite too, so
        there's nothing else to start (see jarvis_remote.py for the
        standalone version that also checks/starts backend+frontend,
        used when nothing is running yet)."""
        if getattr(self, "_remote_tunnel", None) is not None:
            return {"status": "already_running", "public_url": getattr(self, "_remote_tunnel_url", None)}
        try:
            from pyngrok import conf, ngrok
        except ImportError:
            return {"status": "error", "message": "pyngrok not installed -- run: pip install pyngrok --break-system-packages"}
        authtoken = os.environ.get("NGROK_AUTHTOKEN")
        if not authtoken:
            return {"status": "error", "message": "NGROK_AUTHTOKEN not set in environment/.env"}
        try:
            conf.get_default().auth_token = authtoken
            tunnel = ngrok.connect(5173, "http")
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        self._remote_tunnel = tunnel
        self._remote_tunnel_url = tunnel.public_url
        log_event("brain", f"remote access tunnel started: {tunnel.public_url}", level="info")
        return {"status": "started", "public_url": tunnel.public_url}

    def stop_remote_access(self) -> Dict[str, Any]:
        """Stops the tunnel started by start_remote_access(). Never
        touches the backend/frontend processes themselves -- only ever
        the tunnel, since those are UK's normal local session, not
        something a chat command should be able to shut down."""
        tunnel = getattr(self, "_remote_tunnel", None)
        if tunnel is None:
            return {"status": "not_running"}
        try:
            from pyngrok import ngrok
            ngrok.disconnect(tunnel.public_url)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        self._remote_tunnel = None
        self._remote_tunnel_url = None
        return {"status": "stopped"}

    def get_grounding_violation_patterns(self) -> Dict[str, Any]:
        """First real piece of the "response vs brief" hallucination-
        learning loop (2026-09-11, flagged as a bigger design item --
        this is the honest, scoped-down first step, not the full
        thing): analyzes self.grounding_violations for RECURRING
        categories of fabrication, not just a raw list. A single
        flagged response could be a fluke; the same category
        recurring is a real signal something structural needs fixing
        (e.g. self-referential claims kept needing explain_own_
        architecture before that tool existed). This reports patterns;
        it does not yet automatically act on them -- that next step
        (e.g. auto-tightening a prompt instruction when one category
        recurs past a threshold) is real future work, not silently
        claimed as done here."""
        violations = list(self.grounding_violations)
        if not violations:
            return {"total_violations": 0, "patterns": []}
        category_counts: Dict[str, int] = {}
        for v in violations:
            for flag in (v.get("flagged") or []):
                flag_str = str(flag)
                category = flag_str.split(":", 1)[0].strip("[] ") if ":" in flag_str else flag_str[:40]
                category_counts[category] = category_counts.get(category, 0) + 1
        patterns = sorted(
            [{"category": k, "count": v} for k, v in category_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )
        return {
            "total_violations": len(violations),
            "patterns": patterns,
            "most_recent_examples": [
                {"user_input": v.get("user_input"), "flagged": v.get("flagged")}
                for v in violations[-3:]
            ],
        }

    def get_recent_conversation(self, n: int = 5) -> Dict[str, Any]:
        """THE deterministic answer to "hum kya baat kar rahe the",
        "last N response do", "apna pichla response dekh sakte ho" --
        real data, not an LLM guess. Prefers self.recent_turns (this
        session's in-memory buffer, fast) but falls back to real
        PERSISTED episodic memory (survives restarts) when more turns
        are asked for than this session's buffer holds -- found
        2026-09-11: episodic memory was written every turn but NEVER
        read during live conversation anywhere in the codebase, so
        "last 40 messages" after a restart had nothing real to answer
        from. n is clamped to what's actually available, never
        fabricated."""
        n = max(1, int(n or 5))
        if n <= len(self.recent_turns):
            turns = list(self.recent_turns)[-n:]
            return {
                "source": "this_session", "turns_available": len(self.recent_turns),
                "turns_returned": len(turns),
                "turns": self._label_turn_positions([{"user_said": t["user_input"], "jarvis_replied": t["response"]} for t in turns]),
            }
        return self.get_conversation_history(n=n)

    @staticmethod
    def _label_turn_positions(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attaches explicit position_from_last/position_from_first
        integers to each turn (1-indexed) so a request like "second
        last message" doesn't depend on the model correctly counting
        list positions itself -- it can just match position_from_last
        == 2. Found 2026-09-11: this was the residual risk left even
        after get_recent_conversation/get_conversation_history existed
        -- the DATA was available, but "which one is the second-to-
        last" was still left for the model to count out by itself."""
        total = len(turns)
        for i, turn in enumerate(turns):
            turn["position_from_last"] = total - i
            turn["position_from_first"] = i + 1
        return turns

    def get_conversation_history(self, n: int = 20, hours_ago: Optional[float] = None) -> Dict[str, Any]:
        """Real, PERSISTED conversation history from episodic memory --
        survives restarts, unlike recent_turns. Supports an optional
        time window (e.g. "kal ke 12 baje ka message" -> hours_ago
        computed by the caller/LLM from the current time). This is
        the genuine fix for "JARVIS kuch bhi na bhoole" -- previously
        the ONLY code path that ever read episodic memory was idle-time
        consolidation (memory_consolidator.py); nothing in the live
        chat path ever looked at it, so history beyond this session's
        in-memory buffer was completely inaccessible no matter how it
        was asked for."""
        episodic = getattr(self.memory, "episodic", None)
        if episodic is None or not hasattr(episodic, "recent"):
            return {"source": "episodic", "available": False, "turns": []}
        try:
            # Over-fetch when time-filtering so the window isn't
            # truncated by n before the timestamp filter even runs.
            fetch_limit = max(n, 500) if hours_ago is not None else n
            episodes = episodic.recent(limit=fetch_limit)
        except Exception:
            return {"source": "episodic", "available": False, "turns": []}
        cutoff = (time.time() - hours_ago * 3600) if hours_ago is not None else None
        turns: List[Dict[str, Any]] = []
        for ep in episodes:
            ctx = getattr(ep, "context", None) or {}
            outcome = getattr(ep, "outcome", None) or {}
            if not isinstance(ctx, dict) or not isinstance(outcome, dict):
                continue
            user_input = ctx.get("user_input")
            if not user_input:
                continue
            ts = getattr(ep, "timestamp", None)
            if cutoff is not None and (ts is None or ts < cutoff):
                continue
            turns.append({
                "user_said": user_input, "jarvis_replied": outcome.get("response"),
                "timestamp": ts,
            })
        turns = turns[-n:]
        turns = self._label_turn_positions(turns)
        return {"source": "episodic", "available": True, "turns_returned": len(turns), "turns": turns}

    def evaluate_own_recent_responses(self, n: int = 3) -> Dict[str, Any]:
        """UK's ask: JARVIS should check its OWN recent replies against
        what came after them, and honestly say whether each one seems
        to have actually satisfied UK or not -- not just trust its own
        output as automatically correct. Deliberately a SYNCHRONOUS,
        cheap heuristic (not another LLM call judging "was this good")
        for two reasons: it reuses the exact same detect_correction()
        signal that already drives real memory-confidence changes (see
        outcome_feedback.py), so this reports the SAME thing Brain
        actually acts on, not a second, disconnected opinion; and it
        keeps this tool answerable instantly, with no LLM-budget cost,
        for what is fundamentally a self-inspection question."""
        from ..learning.outcome_feedback import detect_correction
        turns = list(self.recent_turns)[-(n + 1):]
        results = []
        for i in range(len(turns) - 1):
            this_turn = turns[i]
            next_turn = turns[i + 1]
            corrected = detect_correction(next_turn.get("user_input", ""))
            results.append({
                "user_said": this_turn.get("user_input"),
                "jarvis_replied": this_turn.get("response"),
                "next_message_was_a_correction": corrected,
                "self_assessment": "UK ne is jawab ko galat/asantosht bataya lagta hai (agla message ek correction jaisa tha)."
                                    if corrected else "Koi explicit correction nahi mila agle message mein -- par yeh sirf ek heuristic hai, guarantee nahi.",
            })
        return {"turns_checked": len(results), "results": results}

    def audit_and_learn_from_history(
        self, max_turns: int = 500, min_occurrences: int = 2,
    ) -> Dict[str, Any]:
        """RETROACTIVE self-training over PAST conversation history
        (2026-09-19, UK: "JARVIS ko audit karke purani chats consolidate
        karke, kya galat response diya tha, user ne kya correction diya
        tha, uska behavioral goal mein apnaaye").

        Distinct from the LIVE self-rule pipeline just above/around this
        method (reasoning_trace.adopt_as_learning -> semantic.remember
        with subject="jarvis_self_rule" -> pending_confirmation ->
        shadow-evidence auto-adopt after several genuinely SEPARATE live
        reasoning cycles independently reach the same conclusion). That
        pipeline only ever sees THIS turn's own self-evaluation; it has
        no way to look back at corrections from sessions before it
        existed, or from turns that never went through self-evaluation
        at all. This method is that backward sweep: pulls real,
        persisted history via get_conversation_history() (survives
        restarts, spans every past session, not just this one), finds
        corrections with core.cognition.correction_audit's hardened
        detector, consolidates REPEATED ones (min_occurrences, default
        2 -- a correction seen once is an isolated event, not a pattern
        worth learning from) into candidate rules, and writes each one
        into the SAME jarvis_self_rule schema the live pipeline uses --
        so it's visible via /pending_rules and governed by /confirm_rule
        /reject_rule exactly like any other proposal.

        ALWAYS pending_confirmation, NEVER auto-adopted here, even if a
        consolidated rule has many occurrences: the live pipeline's
        auto-adopt threshold is calibrated to INDEPENDENT reasoning
        cycles each separately concluding the same thing in real time,
        which is meaningfully stronger evidence than several historical
        turns where the user corrected the SAME underlying mistake
        (JARVIS may simply have kept making the same mistake without
        ever re-deriving the rule on its own) -- audit-derived rules
        haven't earned that trust level and must go through UK's
        explicit review regardless of occurrence count.
        """
        from ..cognition.correction_audit import audit_history_for_learnable_corrections

        history = self.get_conversation_history(n=max_turns)
        if not history.get("available"):
            return {"audited": False, "reason": "episodic memory not available", "rules_proposed": 0}

        turns = history.get("turns", [])
        rules = audit_history_for_learnable_corrections(turns, min_occurrences=min_occurrences)

        semantic = getattr(self.memory, "semantic", None)
        if semantic is None or not hasattr(semantic, "remember"):
            return {"audited": True, "turns_scanned": len(turns), "rules_found": len(rules),
                    "rules_proposed": 0, "reason": "semantic memory not available to persist proposals"}

        proposed: List[Dict[str, Any]] = []
        already_known: List[Dict[str, Any]] = []
        for rule in rules:
            rule_key = hashlib.sha1(rule.rule_text.strip().lower().encode("utf-8")).hexdigest()[:10]
            predicate = f"learned_behavior_audit_{rule_key}"

            # REJECTION MEMORY -- same tombstone check the live pipeline
            # uses (see above): if UK already rejected this exact rule
            # text via /reject_rule, do not re-propose it just because
            # the audit found it again in history.
            already_rejected = False
            try:
                existing_rows = semantic.find(subject="jarvis_self_rule", predicate=predicate) or []
                already_rejected = any("rejected" in (getattr(r, "tags", None) or []) for r in existing_rows)
            except Exception:
                already_rejected = False

            if already_rejected:
                already_known.append({"rule": rule.rule_text, "status": "previously_rejected_by_uk"})
                continue

            try:
                rule_knowledge = semantic.remember(
                    subject="jarvis_self_rule",
                    predicate=predicate,
                    value=rule.rule_text,
                    confidence=min(0.6 + 0.05 * rule.occurrences, 0.85),
                    importance=0.6,
                    source="history_audit",
                    tags=["self_authored", "pending_confirmation", "from_audit"],
                    namespace="SYSTEM",
                    # Same as the live pipeline: unverified until UK
                    # reviews it via /confirm_rule.
                    source_type="llm_unverified",
                )
                proposed.append({
                    "rule": rule.rule_text,
                    "occurrences": rule.occurrences,
                    "example_evidence": rule.example_evidence,
                    "knowledge_id": getattr(rule_knowledge, "knowledge_id", None),
                })
            except Exception as exc:
                already_known.append({"rule": rule.rule_text, "status": f"failed_to_store: {exc}"})

        if proposed:
            log_event(
                "brain",
                f"history audit proposed {len(proposed)} rule(s) from {len(turns)} past turns, "
                f"awaiting UK's confirmation (/pending_rules)",
                level="info",
            )

        return {
            "audited": True,
            "turns_scanned": len(turns),
            "rules_found": len(rules),
            "rules_proposed": len(proposed),
            "proposed": proposed,
            "skipped": already_known,
        }

    def explain_own_architecture(self) -> Dict[str, Any]:
        """THE deterministic answer to "session memory vs episodic
        memory mein fark", "kya tum JARVIS ho ya LLM", "tumhare paas
        kitni memory hai" -- a FIXED, accurate description, not a
        fresh LLM improvisation every time (which is why these
        answers kept contradicting each other turn to turn in the
        trace-log audit -- see 2026-09-11 bug report). This is
        genuinely static architectural fact, not something that needs
        regenerating."""
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        semantic_count = None
        try:
            semantic_count = len(semantic.list_all()) if semantic is not None and hasattr(semantic, "list_all") else None
        except Exception:
            semantic_count = None
        return {
            "how_replies_are_generated": (
                "JARVIS's own cognition (Brain) decides what's true and relevant first -- stored facts, "
                "rules, recent context -- and assembles it into a structured brief. An LLM call then only "
                "phrases that brief into natural language; it is not supposed to invent facts outside it. "
                "So a reply is JARVIS's decision, worded by an LLM -- not the LLM deciding on its own, and "
                "not something that changes answer to answer."
            ),
            "memory_types": {
                "semantic_memory": f"Long-term facts about UK and the project, persisted to disk (SQLite + FAISS), survives restarts. Currently holds {semantic_count if semantic_count is not None else 'an unknown number of'} entries.",
                "episodic_memory": "A record of past conversation experiences (what happened, when), also persisted to disk -- used during idle time to extract new semantic facts, and is the source for get_recent_conversation().",
                "procedural_memory": "Learned habits/action-sequences JARVIS has practiced -- currently exists as infrastructure but nothing has been learned into it yet.",
                "session_memory": "The current conversation's short-term working context only -- not separately persisted; whatever from it matters gets captured into episodic memory as the turn happens, not kept as its own store.",
            },
            "recent_conversation_available": len(self.recent_turns) > 0,
        }


        """M8 (2026-09-11, scoped): how much of semantic understanding
        is currently resolved WITHOUT an LLM call this session, and
        whether the learned-native path is taking real share from LLM
        fallback over time. See SemanticLearningBoundary.stats() for
        the full design note on why this is a measurable-telemetry
        slice, not a new autonomous-replacement subsystem."""
        boundary = getattr(self.semantic_understanding, "learning_boundary", None)
        if boundary is None or not hasattr(boundary, "stats"):
            return {"available": False}
        try:
            stats = boundary.stats()
            stats["available"] = True
            return stats
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    # =============================================================
    # CONSOLIDATE
    # =============================================================

    def consolidate(self, limit: int = 50) -> Dict[str, Any]:
        if self.consolidator is None:
            raise RuntimeError("MemoryConsolidator is not connected.")

        result = self.consolidator.consolidate(limit=limit)
        self._emit("BRAIN_MEMORY_CONSOLIDATED", result)
        return result

    def learn_and_consolidate(
        self,
        experience: Dict[str, Any],
        auto_accept: Optional[bool] = None,
        consolidation_limit: int = 50,
    ) -> Dict[str, Any]:
        learning_result = self.learn(experience=experience, auto_accept=auto_accept)

        consolidation_result = None
        if self.consolidator is not None:
            consolidation_result = self.consolidate(limit=consolidation_limit)

        return {
            "learning": learning_result,
            "consolidation": consolidation_result,
            "timestamp": time.time(),
        }

    # =============================================================
    # EVOLUTION
    # =============================================================

    def propose_evolution(self, evaluation: Dict[str, Any], target: str, reason: Optional[str] = None) -> Dict[str, Any]:
        if self.evolution is None:
            raise RuntimeError("EvolutionEngine is not connected.")
        proposal = self.evolution.propose(evaluation=evaluation, target=target, reason=reason)
        self._emit("BRAIN_EVOLUTION_PROPOSED", proposal)
        return proposal

    def validate_evolution(self, proposal_id: str) -> Dict[str, Any]:
        if self.evolution is None:
            raise RuntimeError("EvolutionEngine is not connected.")
        return self.evolution.validate(proposal_id)

    def approve_evolution(self, proposal_id: str) -> Dict[str, Any]:
        if self.evolution is None:
            raise RuntimeError("EvolutionEngine is not connected.")
        return self.evolution.approve(proposal_id)

    def apply_evolution(self, proposal_id: str) -> Dict[str, Any]:
        if self.evolution is None:
            raise RuntimeError("EvolutionEngine is not connected.")
        result = self.evolution.apply(proposal_id)
        # This is the ONE place a proposal becomes a real, applied change
        # -- so it's the correct place to grow JARVIS's own HISTORY
        # (see core/identity/jarvis_identity.py). Best-effort: identity
        # tracking must never block an evolution apply from succeeding.
        identity_system = getattr(self, "identity_system", None)
        if identity_system is not None:
            try:
                identity_system.record_adaptation(
                    description=f"Applied evolution proposal {proposal_id}",
                    evidence={"proposal_id": proposal_id, "result": result},
                )
            except Exception:
                pass
        return result

    # =============================================================
    # MEMORY CONTEXT (FAISS + Knowledge Graph retrieval)
    # =============================================================

    def build_context(
        self,
        query: Optional[str] = None,
        subject: Optional[str] = None,
        recent_limit: int = 5,
        knowledge_limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Retrieve memory context for reasoning from MemoryManager.
        Brain intentionally does not know HOW retrieval works (FAISS
        similarity search, graph traversal, etc.) — that all lives in
        MemoryManager so it can be upgraded independently.
        """
        if self.memory is None:
            empty_context = {
                "recent_experiences": [],
                "relevant_knowledge": [],
                "graph_relations": [],
            }
            self.last_context = empty_context
            return empty_context

        cache_key = (query, subject, recent_limit, knowledge_limit)
        cached = self._context_cache.get(cache_key)
        if cached is not None:
            return cached

        # Only the real cache-miss path does actual FAISS/graph work, so
        # this is the genuine INDEXING stage of the pipeline -- a cache
        # hit is free and shouldn't flicker the monitor's lifecycle state.
        self._emit("CONTEXT_RETRIEVAL_STARTED", {"query": query, "subject": subject})
        result = self.memory.build_context(
            query=query,
            subject=subject,
            recent_limit=recent_limit,
            knowledge_limit=knowledge_limit,
        )
        self._context_cache[cache_key] = result
        self.last_context = result
        self._emit("CONTEXT_RETRIEVAL_COMPLETED", {
            "query": query,
            "recent_experiences": len(result.get("recent_experiences") or []),
            "relevant_knowledge": len(result.get("relevant_knowledge") or []),
            "graph_relations": len(result.get("graph_relations") or []),
        })
        return result

    # =============================================================
    # PLAN / GOALS
    # =============================================================

    def plan(self, goal: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        if self.planner is None:
            raise RuntimeError("Planner is not connected.")
        method = getattr(self.planner, "plan", None)
        if not callable(method):
            raise RuntimeError("Connected planner does not expose plan().")
        return method(goal=goal, context=context or {})

    def create_goal(self, goal: Any) -> Any:
        if self.goal_manager is None:
            raise RuntimeError("GoalManager is not connected.")
        method = getattr(self.goal_manager, "create_goal", None)
        if not callable(method):
            raise RuntimeError("Connected GoalManager does not expose create_goal().")
        return method(goal)

    # =============================================================
    # STATUS
    # =============================================================

    def status(self) -> Dict[str, Any]:
        learning_status = None
        if self.learning is not None:
            method = getattr(self.learning, "status", None)
            if callable(method):
                try:
                    learning_status = method()
                except Exception as exc:
                    learning_status = {"error": str(exc)}

        consolidator_status = None
        if self.consolidator is not None:
            method = getattr(self.consolidator, "status", None)
            if callable(method):
                try:
                    consolidator_status = method()
                except Exception as exc:
                    consolidator_status = {"error": str(exc)}

        return {
            "version": self.VERSION,
            "running": self.running,
            "created_at": self.created_at,
            "cycles": self.cycle_count,
            "last_cycle_at": self.last_cycle_at,
            "auto_accept_knowledge": self.auto_accept_knowledge,
            "total_turns": self.total_turns,
            "total_latency_seconds": self.total_latency_seconds,
            "avg_latency_ms": round(
                (self.total_latency_seconds / self.total_turns) * 1000, 1
            ) if self.total_turns else 0.0,
            "total_tokens_estimate": self.total_tokens_estimate,
            "organs": {
                "memory": self.memory is not None,
                "experience_engine": self.experience is not None,
                "self_evaluator": self.evaluator is not None,
                "knowledge_builder": self.knowledge_builder is not None,
                "memory_consolidator": self.consolidator is not None,
                "learning_coordinator": self.learning is not None,
                "evolution_engine": self.evolution is not None,
                "planner": self.planner is not None,
                "goal_manager": self.goal_manager is not None,
                "llm_bridge": self.llm is not None,
            },
            "learning_status": learning_status,
            "consolidator_status": consolidator_status,
            "async_learning_queue": self._learning_queue.status(),
            # LLM Dependency Metrics (blueprint section 43) -- the
            # measurable answer to "is JARVIS actually needing the LLM
            # less over time", not a description of intent.
            "dependency_metrics": self.dependency_metrics.as_dict(),
            "contradiction_rate": contradiction_rate(self.memory),
        }

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        return self.last_result

    # =============================================================
    # START / STOP
    # =============================================================

    def start(self) -> None:
        self.running = True
        self._learning_queue.start()
        if self.learning is not None:
            method = getattr(self.learning, "start", None)
            if callable(method):
                method()

    def stop(self) -> None:
        self.running = False
        # Drain=True: finish learning whatever is already queued before
        # shutting the worker down, so a clean stop never loses a fact
        # that was already accepted from the user.
        self._learning_queue.stop(drain=True)
        if self.learning is not None:
            method = getattr(self.learning, "stop", None)
            if callable(method):
                method()

    # =============================================================
    # INTERNAL HELPERS
    # =============================================================

    def _finish_cycle(self, result: Dict[str, Any]) -> None:
        self.cycle_count += 1
        self.last_cycle_at = time.time()
        self.last_result = result

    def set_llm_bridge(self, llm_bridge: Any) -> None:
        self.llm = llm_bridge
        if hasattr(self, "pattern_synthesizer") and self.pattern_synthesizer is not None:
            self.pattern_synthesizer.llm = llm_bridge

        if not hasattr(self, "perception") or self.perception is None:
            return

        self.perception.providers = [
            provider
            for provider in self.perception.providers
            if getattr(provider, "name", None) != "llm"
        ]

        if llm_bridge is not None:
            self.perception.add_provider(
                LLMPerceptionProvider(llm_bridge)
            )

    def execute_autonomous_step(self, step: Dict[str, Any], goal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute one planner-approved step through the Brain boundary."""
        started = time.time()
        step_data = dict(step or {})
        action_name = step_data.get("action")
        # THE ACTUAL FIX (UK's explicit ask: idle time should genuinely
        # hunt for facts and resolve its own uncertainty, not sit empty)
        # -- these two actions come from Planner's verify_knowledge plan
        # (core/autonomy/planner.py), now genuinely reachable since
        # idle_loop.py's _find_knowledge_gaps() feeds Curiosity real
        # low-confidence facts. No skill is registered under either
        # name (nothing is registered in skill_registry in this build),
        # so falling through to the generic skill_executor path below
        # would always fail with "no_capability" -- handled natively
        # here instead, directly against real semantic memory.
        if action_name in ("search_supporting_evidence", "update_confidence"):
            return self._execute_verify_knowledge_step(action_name, step_data, goal, started)
        if action_name == "standing_instruction_fire":
            return self._execute_standing_instruction(step_data, started)
        skill_name = step_data.get("capability") or step_data.get("skill") or action_name
        self._emit("BRAIN_CYCLE_STARTED", {"source": "idle", "goal": goal or {}, "step": step_data})
        if step_data.get("requires_confirmation") is True:
            result = {"success": False, "status": "blocked_pending_confirmation", "action": action_name, "result": "confirmation_required"}
            self.last_brain_decision = {"mode": "native", "source": "idle", "status": result["status"], "action": action_name}
            self.last_action_response = result
            self._emit("ACTION_RESPONSE_COMPLETED", result)
            return result
        if self.skill_executor is None or not skill_name:
            result = {"success": False, "status": "no_capability", "action": action_name, "result": f"capability_not_available: {skill_name}"}
            self.last_brain_decision = {"mode": "native", "source": "idle", "status": result["status"], "action": action_name}
            self.last_action_response = result
            self._emit("ACTION_RESPONSE_FAILED", result)
            self._enqueue_learning(event_type="AUTONOMOUS_STEP", context={"goal": goal or {}, "step": step_data}, action={"skill": skill_name, "action": action_name}, outcome=result, source="idle", importance=0.3)
            return result
        try:
            native_result = self.skill_executor.execute(skill_name, user_input=step_data.get("input", action_name))
            result = {"success": True, "status": "completed", "action": action_name, "skill": skill_name, "result": str(native_result), "duration": time.time() - started}
            self.last_brain_decision = {"mode": "native", "source": "idle", "status": "completed", "skill": skill_name, "action_result": str(native_result)}
            self.last_action_response = result
            self._emit("ACTION_RESPONSE_COMPLETED", result)
            self._enqueue_learning(event_type="AUTONOMOUS_STEP", context={"goal": goal or {}, "step": step_data}, action={"skill": skill_name, "action": action_name, "result": str(native_result)}, outcome=result, source="idle", importance=0.5)
            self._emit("BRAIN_CYCLE_COMPLETED", {"source": "idle", "brain_decision": self.last_brain_decision, "action_response": result, "duration": time.time() - started})
            return result
        except Exception as exc:
            result = {"success": False, "status": "failed", "action": action_name, "skill": skill_name, "result": str(exc), "duration": time.time() - started}
            self.last_brain_decision = {"mode": "native", "source": "idle", "status": "failed", "skill": skill_name, "error": str(exc)}
            self.last_action_response = result
            self._emit("ACTION_RESPONSE_FAILED", result)
            self._enqueue_learning(event_type="AUTONOMOUS_STEP", context={"goal": goal or {}, "step": step_data}, action={"skill": skill_name, "action": action_name}, outcome=result, source="idle", importance=0.5)
            return result

    def _execute_standing_instruction(self, step_data: Dict[str, Any], started: float) -> Dict[str, Any]:
        """Fires a due standing instruction (see core/autonomy/
        standing_instructions.py + idle_loop.py's step(), which pushes
        due items here via Scheduler.schedule()->due_tasks(), the fix
        for Scheduler.schedule() previously having no producer at all).
        Speaks via Termux:API TTS when available (core/runtime/voice.py);
        always also emits an event so the web frontend/CLI can show it
        even headless/without TTS. mark_fired() only runs AFTER this
        attempt, so a crash mid-fire correctly retries next idle tick
        instead of being silently marked done."""
        knowledge_id = step_data.get("knowledge_id")
        action_text = str(step_data.get("action_text") or "")
        spoken = False
        try:
            from ..runtime import voice
            if voice.voice_available():
                spoken = bool(voice.speak(action_text))
        except Exception:
            spoken = False
        result = {
            "success": True, "status": "completed", "action": "standing_instruction_fire",
            "result": f"fired: {action_text}", "spoken": spoken, "duration": time.time() - started,
        }
        self.last_brain_decision = {"mode": "native", "source": "idle", "status": "completed", "action": "standing_instruction_fire", "action_result": action_text}
        self.last_action_response = result
        self._emit("STANDING_INSTRUCTION_FIRED", {"knowledge_id": knowledge_id, "action_text": action_text, "spoken": spoken})
        self._emit("ACTION_RESPONSE_COMPLETED", result)
        try:
            self.standing_instructions.mark_fired(knowledge_id)
        except Exception:
            pass
        return result

    def _execute_verify_knowledge_step(self, action_name: str, step_data: Dict[str, Any], goal: Optional[Dict[str, Any]], started: float) -> Dict[str, Any]:
        """Native handler for verify_knowledge idle goals: re-check a
        real low-confidence fact against everything else stored about
        the same subject, and nudge its confidence honestly --
        bounded, reversible, and never inventing or deleting the fact
        itself. subject is parsed from the goal's own text because
        GoalManager.add() only persists text/priority/origin (no
        arbitrary metadata field), and that text is produced by
        Curiosity.candidates()'s exact "Knowledge about 'X' has low
        confidence (...)" format -- see core/autonomy/curiosity.py.
        """
        semantic = getattr(self.memory, "semantic", None) if self.memory is not None else None
        goal_text = str((goal or {}).get("text") or "")
        subject_match = re.search(r"Knowledge about '(.+?)' has low confidence", goal_text)
        subject = subject_match.group(1) if subject_match else None

        if semantic is None or not subject or not hasattr(semantic, "find_by_subject"):
            result = {
                "success": False, "status": "no_capability", "action": action_name,
                "result": "semantic memory unavailable or subject unresolved from goal text",
                "duration": time.time() - started,
            }
            self.last_brain_decision = {"mode": "native", "source": "idle", "status": result["status"], "action": action_name}
            self.last_action_response = result
            self._emit("ACTION_RESPONSE_FAILED", result)
            return result

        try:
            related = semantic.find_by_subject(subject) or []
        except Exception:
            related = []
        corroborating = [r for r in related if isinstance(getattr(r, "confidence", None), (int, float)) and getattr(r, "confidence") >= 0.6]

        if action_name == "search_supporting_evidence":
            outcome_text = f"subject='{subject}': {len(related)} related fact(s) on file, {len(corroborating)} already at confidence>=0.6"
            result = {
                "success": True, "status": "completed", "action": action_name, "result": outcome_text,
                "related_count": len(related), "corroborating_count": len(corroborating), "duration": time.time() - started,
            }
        else:  # update_confidence
            adjusted = 0
            for item in related:
                kid = getattr(item, "knowledge_id", None)
                confidence = getattr(item, "confidence", None)
                if not kid or not isinstance(confidence, (int, float)) or confidence >= 0.6:
                    continue
                try:
                    if corroborating:
                        semantic.reinforce(kid, confidence_delta=0.05)
                    else:
                        semantic.weaken(kid, confidence_delta=0.02)
                    adjusted += 1
                except Exception:
                    continue
            direction = "reinforced (corroborated by other facts on the same subject)" if corroborating else "weakened further (still unconfirmed after this check)"
            outcome_text = f"subject='{subject}': {adjusted} low-confidence fact(s) {direction}"
            result = {
                "success": True, "status": "completed", "action": action_name, "result": outcome_text,
                "adjusted_count": adjusted, "duration": time.time() - started,
            }

        self.last_brain_decision = {"mode": "native", "source": "idle", "status": "completed", "action": action_name, "action_result": result["result"]}
        self.last_action_response = result
        self._emit("ACTION_RESPONSE_COMPLETED", result)
        self._enqueue_learning(
            event_type="AUTONOMOUS_STEP", context={"goal": goal or {}, "step": step_data},
            action={"action": action_name, "subject": subject}, outcome=result, source="idle", importance=0.4,
        )
        return result

    def _perceive(self, user_input: str) -> Dict[str, Any]:
        context = self.build_context(query=user_input, recent_limit=3) if self.memory is not None else {}
        result = self.perception.perceive(user_input, context=context)
        payload = result.as_dict()
        self.last_perception = payload
        self._emit("PERCEPTION_COMPLETED", {"user_input": user_input, "perception": payload})
        return payload

    def _route_cognition(self, user_input: str, perception: Dict[str, Any]) -> Dict[str, Any]:
        context = self.build_context(query=user_input, recent_limit=3) if self.memory is not None else {}
        goals = []
        if self.goal_manager is not None:
            current_goal = getattr(self.goal_manager, "current_goal", None)
            if current_goal is not None:
                goals = [current_goal]
        # BRAIN DECIDES FIRST (2026-09-13, the authority inversion).
        # Brain works out WHICH memory system or source owns this turn
        # before the router counts anything, then hands that down as a
        # directive. Pure structure inspection -- no LLM call and no
        # extra latency, so this costs nothing on the hot path.
        brain_directive = None
        try:
            from .information_need import decide_information_need
            has_stored_match = bool(
                (context or {}).get("relevant_knowledge") or (context or {}).get("graph_relations")
            )
            need = decide_information_need(
                user_input, perception,
                has_stored_match=has_stored_match,
                native_capability_available=bool(getattr(self.skill_registry, "skills", None)),
            )
            brain_directive = need.as_dict()
            self.last_information_need = brain_directive
            log_event("brain", f"information need: {need.source} -> route={need.route} ({need.reason})", level="info")
        except Exception as exc:
            # Never let routing classification break a turn -- fall back
            # to the router's own evidence counting, which is what ran
            # before this layer existed.
            log_event("brain", f"information-need classification unavailable, router decides alone: {exc}", level="warning")

        decision = self.cognitive_router.decide(user_input=user_input, context=context, skills=getattr(self.skill_registry, "skills", None), identity=None, goals=goals, perception=perception, brain_directive=brain_directive)
        payload = decision.as_dict()
        self.last_cognitive_decision = payload
        if self.state is not None:
            try:
                self.state.update(last_route=decision.mode, confidence=decision.confidence, uncertainty=1.0 - decision.confidence)
            except Exception:
                pass
        self._emit("COGNITION_ROUTED", {"user_input": user_input, "decision": payload})
        return payload

    def _register_and_plan_goal(self, perceived_goal: Any) -> Dict[str, Any]:
        """Persist a user goal and plan it; execution remains Brain/idle-owned."""
        if self.goal_manager is None:
            return {"status": "goal_manager_unavailable", "goal": perceived_goal}
        if isinstance(perceived_goal, dict):
            text = str(perceived_goal.get("text") or perceived_goal.get("description") or "").strip()
            priority = float(perceived_goal.get("priority", 0.7) or 0.7)
        else:
            text = str(perceived_goal or "").strip()
            priority = 0.7
        if not text:
            return {"status": "invalid_goal", "goal": perceived_goal}
        existing = next((g for g in self.goal_manager.pending() if str(g.get("text", "")).strip().lower() == text.lower()), None)
        goal = existing or self.goal_manager.add(text=text, priority=priority, origin="user")
        self.goal_manager.update_status(goal["id"], "active")
        planner = getattr(self, "planner", None)
        plan = goal.get("plan") or []
        if not plan and planner is not None:
            plan = planner.plan(goal)
            self.goal_manager.set_plan(goal["id"], plan)
            goal = self.goal_manager._find(goal["id"]) or goal
        return {"status": "planned", "goal": goal, "plan": plan}

    def _hybrid_synthesize(self, user_input: str, skill_name: str, native_result: Any, source: str) -> str:
        if self.llm is None:
            return str(native_result)

        system_prompt = "You are JARVIS's response synthesizer. A native organism skill has already executed successfully. Do not invent actions or claim to execute anything. Return a concise user-facing response based only on the native result."
        synthesis_input = f"User request: {user_input}\nNative skill: {skill_name}\nNative result: {native_result}"
        try:
            generate = getattr(self.llm, "generate", None)
            if callable(generate):
                return str(generate(system_prompt, synthesis_input)).strip()
            generate_response = getattr(self.llm, "generate_response", None)
            if callable(generate_response):
                return str(generate_response(system_prompt=system_prompt, user_input=synthesis_input, level="response_generation")).strip()
        except Exception as exc:
            self.last_brain_decision = {"mode": "hybrid", "status": "native_success_llm_synthesis_failed", "error": str(exc)}
        return str(native_result)

    def attach_skill_registry(self, skill_registry: Any) -> None:
        """Attach or replace the skill registry and its executor."""
        self.skill_registry = skill_registry
        self.skill_executor = (
            SkillExecutor(skill_registry)
            if skill_registry is not None
            else None
        )

    def attach_skill_executor(self, skill_executor: Any) -> None:
        self.skill_executor = skill_executor

    # Devanagari range. Used to catch script violations -- see
    # _enforce_hinglish_script below.
    _DEVANAGARI = re.compile(r"[\u0900-\u097F]")

    def _enforce_hinglish_script(self, text: str) -> str:
        """UK's standing rule is Hinglish in Latin script. The model
        ignores it often enough that a prompt line alone is not a fix --
        the trace shows replies like "नमस्ते, सर।" on a turn where the
        rule was in context.

        So: detect, and ask the model once to rewrite the SAME content in
        Latin script. One extra call, only when the rule was actually
        broken, and only when there is budget to spare -- a style rule
        must never be the reason a turn runs out of room.

        Deliberately NOT mechanical transliteration: converting
        Devanagari to Latin by table gives stilted output ("namaste
        sar"), which trades one thing UK dislikes for another. The model
        rewrites it properly or the original stands.
        """
        if not text or not self._DEVANAGARI.search(text):
            return text
        try:
            remaining = int(self.llm.budget_status().get("remaining_calls", 0))
        except Exception:
            remaining = 0
        if remaining < 2:
            log_event("brain", "Devanagari in reply but no budget to rewrite -- left as-is",
                      level="warning")
            return text
        try:
            rewritten = str(self.llm.generate_response(
                system_prompt=("Rewrite the user's text in Hinglish using LATIN script only. "
                               "Keep the meaning, tone and length identical. Change nothing "
                               "except the script. Output only the rewritten text."),
                user_input=text,
                max_tokens=900,
                level="response_generation",
            )).strip()
            if rewritten and not self._DEVANAGARI.search(rewritten):
                log_event("brain", "reply rewritten from Devanagari to Latin script", level="info")
                return rewritten
        except Exception as exc:
            log_event("brain", f"script rewrite failed: {exc}", level="warning")
        return text

    def _record_action_response(self, *, mode: str, status: str, response: Any, action: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> str:
        response_text = self._enforce_hinglish_script(str(response))
        # SAFETY NET (2026-09-11 trace-log audit, Bug 6): catches the
        # SAME class of bug even from paths that don't raise an
        # exception -- llm_bridge.py's generate_response() has a
        # normal (non-exception) return-value sentinel
        # ("[LLM unavailable: ...]") for when no backend is usable,
        # and it was reaching the chat verbatim because nothing
        # between there and here ever checked for it. Every turn
        # passes through this exact chokepoint regardless of route,
        # so this is the one place that reliably catches it no matter
        # which caller produced it.
        if response_text.startswith("[LLM unavailable:") or response_text.startswith("[Brain Thinking Error:") or response_text.startswith("[Model Generation Error"):
            if error is None:
                error = response_text.strip("[]")
            response_text = "Mujhe abhi jawab dene mein dikkat aa rahi hai -- kripya thodi der baad try karo."
            status = "failed" if status == "completed" else status
        # EMPTY REPLY (2026-09-19, UK's own screenshots/logs: a bare
        # "..." bubble with no text at all, in both normal and extended
        # thinking). The sentinel check above only catches the KNOWN
        # "[LLM unavailable: ...]" text; a genuinely empty string (the
        # model returning "" outright, or some upstream step producing
        # nothing) fell through untouched and reached the chat as a
        # literal blank message -- the single most confusing possible
        # failure mode, since it gives the user nothing to react to.
        # Same chokepoint, same reasoning as the sentinel check: every
        # turn passes through here regardless of route, so this is the
        # one place that reliably catches it no matter which caller
        # produced the empty string.
        elif not response_text.strip():
            if error is None:
                error = "empty_response"
            response_text = "Mujhe is baar koi jawab nahi mila -- kripya dobara try karein ya sawaal thoda alag tarike se poochein."
            status = "failed" if status == "completed" else status
        record: Dict[str, Any] = {"mode": mode, "status": status, "response": response_text}
        if action is not None:
            record["action"] = action
        if error is not None:
            record["error"] = error
        self.last_action_response = record
        self._emit("ACTION_RESPONSE_COMPLETED", record)

        # STORE WHAT THIS RESPONSE OFFERED (2026-09-14). If this turn's
        # response ends in a question/offer, remember it so a bare
        # "haan"/"ok" NEXT turn resolves against what JARVIS itself just
        # asked, rather than arriving at perception as near-empty
        # content. See core/cognition/pending_expectation.py for why
        # this is narrow by design: it stores only what was actually
        # said, never an inference about intent.
        try:
            from ..cognition.pending_expectation import detect_offer, PendingExpectation
            offer_text = detect_offer(response_text)
            self._pending_expectation = (
                PendingExpectation(
                    jarvis_said=response_text,
                    offer_text=offer_text,
                    source_user_input=self._last_user_input,
                )
                if offer_text else None
            )
        except Exception as exc:
            log_event("brain", f"pending-expectation storage skipped: {exc}", level="warning")

        # PERSIST TO THIS SPEAKER'S OWN SCHEMA (2026-09-14). Every turn,
        # regardless of route, lands in exactly one identity's memory --
        # owner's turns in the owner schema, a guest's in their bounded
        # ephemeral buffer, and never in each other's. See
        # core/identity/identity_memory.py for why this is the one
        # choke point that makes cross-identity leakage structural,
        # not just policy.
        try:
            from ..identity.identity_memory import remember_turn as _remember_identity_turn
            speaker = getattr(self, "current_speaker", None) or {}
            _remember_identity_turn(speaker, self._last_user_input, response_text)
        except Exception as exc:
            log_event("brain", f"identity-memory persist skipped: {exc}", level="warning")

        # Clean, readable chat transcript (separate from the internal
        # debug log) -- every turn passes through this single
        # chokepoint regardless of route (goal/native/hybrid/llm), so
        # this is the correct place to log it once, consistently.
        try:
            log_chat_turn(self._last_user_input, response_text)
        except Exception:
            pass

        try:
            # THE PRIORITY BUG (2026-09-11, UK's explicit top ask):
            # get_recent_conversation WAS firing correctly, but got
            # polluted by workflow_narration turns -- a native fast
            # path that itself just narrates "pichhla turn: aapne kaha
            # X" as a debug/meta convenience, not a real answer. Those
            # were getting recorded into recent_turns like any other
            # turn, so a LATER get_recent_conversation call would
            # return a narration-ABOUT-a-narration, and the LLM quoted
            # it back as if it were a genuine past reply (the garbled
            # "Pichla response tha: 'Pichhla turn: aapne kaha...'"
            # recursive-quote UK saw). Excluded here so recent_turns
            # only ever holds genuine conversational exchanges.
            answered_by = (action or {}).get("answered_by") if isinstance(action, dict) else None
            if answered_by != "workflow_narration":
                self.recent_turns.append({
                    "user_input": self._last_user_input, "response": response_text,
                    "mode": mode, "timestamp": time.time(),
                })
        except Exception:
            pass

        try:
            self.dependency_metrics.record_turn(
                mode=mode, status=status,
                answered_by=(action or {}).get("answered_by") if isinstance(action, dict) else None,
            )
        except Exception:
            pass

        # Evolution-of-LLM-fallbacks detection (blueprint section 48):
        # only meaningful for turns that genuinely reached the LLM
        # (mode == "llm" and not one of the native fast paths above --
        # those already answered_by something and are excluded by the
        # "not action" check, since native fast paths pass action=None
        # or a dict without this specific shape).
        answered_by = (action or {}).get("answered_by") if isinstance(action, dict) else None
        if mode == "llm" and answered_by not in ("native_direct_recall", "identity", "graph_multi_hop", "slm_assisted_recall"):
            try:
                from .response_brief import detect_recall_miss
                pattern_key = detect_recall_miss(self._last_user_input, {})
                if pattern_key:
                    self.fallback_pattern_detector.record(
                        pattern_key=pattern_key, success=(status == "completed"), user_input=self._last_user_input,
                    )
                    self._check_fallback_promotion_candidates()
            except Exception:
                pass

        # ---------------------------------------------------------------
        # BACKGROUND LEARNING HAND-OFF (post-response context ingestion)
        # ---------------------------------------------------------------
        # This is the single chokepoint every conversational route (goal,
        # native, hybrid, llm) passes through on its way to returning a
        # reply, so it is the correct place to trigger background
        # learning -- previously _enqueue_learning() was only ever
        # called from the autonomous idle loop, so a normal chat turn
        # never fed the learning pipeline at all. mode == "error" is
        # excluded: a perception/routing crash has no structured
        # context worth persisting into semantic memory.
        if mode != "error":
            try:
                perception = self.last_perception or {}
                self._enqueue_learning(
                    event_type="USER_CHAT",
                    context={
                        "user_input": self._last_user_input,
                        # Flattened -- see _flatten_perception_for_episode.
                        # Storing the raw perception here made each episode
                        # contain every previous episode.
                        "perception": _flatten_perception_for_episode(perception),
                        # KnowledgeBuilder reads context["semantic"]["relations"]
                        # to turn ordinary chat turns ("remember X") into durable
                        # knowledge-graph facts -- keep this key even for the
                        # base Brain, where perception won't carry a semantic
                        # understanding block yet (it will just be {}).
                        "semantic": {
                            "relations": (
                                (perception.get("semantic_understanding") or {}).get("relations") or []
                            )[:_EPISODE_MAX_RELATIONS],
                            "intent": (perception.get("semantic_understanding") or {}).get("intent"),
                        },
                        # last_cognition_input can also carry a full context
                        # tree; only its shape is useful here.
                        "cognition": {"present": bool(getattr(self, "last_cognition_input", None))},
                    },
                    action=action or {"mode": mode},
                    outcome={"response": response_text, "status": status, "error": error},
                    source="chat",
                    importance=0.6 if status in ("completed", "planned") else 0.3,
                )
            except Exception as exc:
                # Learning hand-off must never break the response that
                # has already been produced for the user.
                log_event("brain", f"background learning hand-off failed: {exc}", level="warning")

            # -----------------------------------------------------------
            # PERSISTENT TRACE LOG (UK's #4)
            # -----------------------------------------------------------
            # _enqueue_learning above feeds semantic-fact extraction, but
            # its context dict is scoped to what KnowledgeBuilder needs --
            # it does NOT carry the grounding-check verdict, LLM budget
            # spend, or the raw response text long-term (episodic memory
            # keeps its own copy, but self.last_turn_trace above gets
            # overwritten every single turn). This is the durable, full-
            # fidelity record: one JSON line per turn, forever (subject to
            # retention), that #5's native-response-learning miner and any
            # future introspection command both read from.
            try:
                from ..runtime.trace_log import get_trace_log

                decision = self.last_brain_decision or {}
                budget = self.llm.budget_status() if getattr(self, "llm", None) is not None and hasattr(self.llm, "budget_status") else {}
                get_trace_log().write({
                    "timestamp": time.time(),
                    "user_input": self._last_user_input,
                    "response": response_text,
                    "mode": mode,
                    "status": status,
                    "error": error,
                    "perception": perception,
                    "brain_decision": decision,
                    "stayed_within_brief": decision.get("stayed_within_brief"),
                    "flagged_unsupported": decision.get("flagged_unsupported"),
                    "llm_budget": budget,
                })
            except Exception as exc:
                log_event("brain", f"trace log write failed: {exc}", level="warning")

        return response_text

    _retry_value_evolution_proposed = False

    def _check_retry_value_evolution(self) -> None:
        """The other half of "JARVIS ko apne LLM-call kharche ki value
        khud pata honi chahiye": not just measuring retry_value_rate
        (DependencyMetrics), but actually ACTING on it when the number
        is bad enough, via the same governed evolution-proposal
        mechanism as _check_fallback_promotion_candidates below --
        never auto-applied, always requires separate approval (Rule 19).

        Deliberately conservative thresholds: at least 5 retries spent
        before drawing any conclusion (one or two bad retries prove
        nothing), and a paid-off rate below 30% before proposing
        anything -- retries that pay off even half the time are still
        worth their cost given how cheap the alternative (silently
        losing the data) is.
        """
        if self.evolution is None or self._retry_value_evolution_proposed:
            return
        used = self.dependency_metrics.llm_retry_used_count
        rate = self.dependency_metrics.retry_value_rate()
        if used < 5 or rate is None or rate >= 0.3:
            return
        try:
            self.propose_evolution(
                evaluation={
                    "score": rate,
                    "errors": [],
                    "evolution_target": "llm_retry_policy",
                    "evolution_reason": (
                        f"LLM reinforced-retry stages (perception's and/or semantic "
                        f"understanding's) have been spent {used} times and only paid "
                        f"off {rate*100:.0f}% of the time. Candidate: reconsider whether "
                        f"the retry is worth its extra API call for this deployment/model, "
                        f"or investigate why retries are failing so often (e.g. a model "
                        f"that consistently can't follow the reinforced JSON instruction)."
                    ),
                },
                target="llm_retry_policy",
                reason=f"Retry value rate {rate:.2f} across {used} spent retries is below the 0.3 worth-keeping threshold",
            )
            self._retry_value_evolution_proposed = True
            log_event("brain", f"proposed evolution: low retry value rate ({rate:.2f} across {used} retries)", level="info")
        except Exception as exc:
            log_event("brain", f"could not propose retry-value evolution: {exc}", level="warning")

    def _check_fallback_promotion_candidates(self) -> None:
        """Promote a recall-miss pattern into a governed evolution
        proposal once it's crossed the reliability threshold. This
        NEVER writes code or a resolver directly -- propose_evolution()
        creates an inspectable PROPOSED record via the existing
        ControlledEvolutionEngine; approval/apply remain a separate,
        explicit governed step (Rule 19), completely untouched here."""
        if self.evolution is None:
            return
        for candidate in self.fallback_pattern_detector.promotion_candidates():
            pattern_key = candidate["pattern_key"]
            try:
                self.propose_evolution(
                    evaluation={
                        "score": candidate["success_rate"],
                        "errors": [],
                        "evolution_target": "memory_retrieval",
                        "evolution_reason": (
                            f"Recall coverage gap: '{pattern_key}' was asked "
                            f"{candidate['occurrences']} times (all via LLM fallback, "
                            f"{candidate['success_rate']*100:.0f}% successful). The question "
                            f"shape matched native recall exactly but the predicate word "
                            f"wasn't in the recognized map -- candidate: add '{pattern_key}' "
                            f"as a recognized predicate alias in "
                            f"core/orchestration/response_brief.py's _ASK_WORD_TO_PREDICATE."
                        ),
                    },
                    target="memory_retrieval",
                    reason=f"Repeated LLM fallback for a native-recall-shaped question: '{pattern_key}'",
                )
                self.fallback_pattern_detector.mark_proposed(pattern_key)
                log_event("brain", f"proposed evolution for recall coverage gap: {pattern_key}", level="info")
            except Exception as exc:
                log_event("brain", f"could not propose evolution for '{pattern_key}': {exc}", level="warning")

    def _trace(self, user_input: str, response: str, route: Dict[str, Any], perception: Dict[str, Any], started: float, llm: bool) -> None:
        self.last_turn_trace = {"source": "brain", "query": user_input, "response_preview": response[:200], "perception": perception, "cognitive_route": route, "brain_decision": self.last_brain_decision, "action_response": self.last_action_response, "llm_available": llm, "pipeline_success": True, "timings": {"total": time.time() - started}}
        self._emit("BRAIN_CYCLE_COMPLETED", {"trace": self.last_turn_trace})

    # Retrieval-based context bound for the LLM fallback route (blueprint
    # Phase 4: never dump full memory/knowledge/graph state into an LLM
    # prompt). Caps item count and per-item length *before* the string
    # ever reaches CognitiveBudgeter, so the hard 4096-token guard is a
    # backstop rather than the only thing standing between this and an
    # unbounded prompt.
    _CONTEXT_MAX_ITEMS = 5
    _CONTEXT_MAX_ITEM_CHARS = 200

    @classmethod
    def _bounded_context_items(cls, items: Any) -> list:
        if not items:
            return []
        try:
            sequence = list(items)
        except TypeError:
            return []
        bounded = []
        for item in sequence[: cls._CONTEXT_MAX_ITEMS]:
            text = str(item)
            if len(text) > cls._CONTEXT_MAX_ITEM_CHARS:
                text = text[: cls._CONTEXT_MAX_ITEM_CHARS] + "…"
            bounded.append(text)
        return bounded

    @classmethod
    def _bounded_context_block(cls, context: Dict[str, Any]) -> str:
        # Epistemic-boundary fix: the old labels ("RETRIEVED MEMORIES" /
        # "SEMANTIC KNOWLEDGE") gave a raw chat-log excerpt and an actual
        # confirmed database fact equal rhetorical weight. A weak model
        # reading both sections back-to-back has no signal telling it
        # "only the second one is something you're allowed to claim you
        # remember" -- so it answers factual questions straight out of
        # the conversation transcript even when KnowledgeBuilder never
        # actually stored that fact (visible in production as: JARVIS
        # answers correctly, but /memory_inspect shows nothing saved).
        # Relabeling alone doesn't fix extraction, but it stops the model
        # from *asserting* unsaved chat history as saved, confirmed fact.
        experiences = cls._bounded_context_items(context.get("recent_experiences"))
        knowledge = cls._bounded_context_items(context.get("relevant_knowledge"))
        graph = cls._bounded_context_items(context.get("graph_relations"))
        return (
            f"=== PAST CONVERSATION EXCERPTS (context only -- NOT confirmed saved facts, max {cls._CONTEXT_MAX_ITEMS}) ===\\n"
            f"{experiences}\\n\\n"
            f"=== CONFIRMED KNOWLEDGE (verified facts actually saved in JARVIS's permanent store, max {cls._CONTEXT_MAX_ITEMS}) ===\\n"
            f"{knowledge}\\n\\n"
            f"=== KNOWLEDGE GRAPH EDGES (verified relations, max {cls._CONTEXT_MAX_ITEMS}) ===\\n"
            f"{graph}\\n\\n"
            f"=== MEMORY RULE (STRICT) ===\\n"
            f"Only treat something as a fact you 'remember' or have 'saved' if it "
            f"appears in CONFIRMED KNOWLEDGE or KNOWLEDGE GRAPH EDGES above. If a "
            f"detail only appears in PAST CONVERSATION EXCERPTS, you may refer to it "
            f"conversationally, but you must NOT claim it is remembered/saved -- say "
            f"it hasn't been confirmed/stored yet if the user asks directly."
        )

    def _fallback(self, user_input: str) -> str:
        lower = (user_input or "").strip().lower()
        if lower in {"status", "health", "ping"}:
            return "JARVIS Core ONLINE. LLM unavailable; operating in degraded cognitive mode."
        return "JARVIS received the input, but no language cognition provider is currently available. Core organism remains active."

    def _emit(self, event_name: str, payload: Any = None) -> None:
        if self.events is None:
            return
        safe_emit = getattr(self.events, "safe_emit", None)
        if callable(safe_emit):
            safe_emit(event_name, payload, source="brain")
