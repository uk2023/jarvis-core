from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Mapping, Optional

from ..contracts import validate_input, validate_output
from ..contracts.validator import begin_validation_trace, get_validation_trace
from ..cognition.semantic_understanding import SemanticUnderstanding
from ..cognition.translator import normalize as translator_normalize
from ..learning.training_data_collector import get_training_data_collector
from .llm_bridge import can_afford_another_llm_call
from ..runtime.log import log_event
from .brain import Brain


class BlueprintBrain(Brain):
    """The actual runtime Brain; contracts are enforced at live boundaries.

    The Brain itself owns the Perception -> Semantic Understanding ->
    Cognition -> Router -> Response -> Experience/Learning orchestration
    boundary. There is no proxy wrapper around this runtime organ.
    """

    VERSION = "1.4.0"
    _SUPPORTED_ROUTES = frozenset({"goal", "native", "hybrid", "llm", "clarify"})

    _SEMANTIC_FALLBACK_PROMPT = (
        "You are JARVIS semantic understanding fallback. Return ONLY JSON. "
        "Do not answer the user and do not invent external facts. "
        'Shape: {"semantic":{"normalized":"...","intent":{},"entities":[],'
        '"relations":[],"events":[],"references":[],"confidence":0.0,'
        '"provenance":{"source":"llm_fallback"},"inferences":[],"unknowns":[]}}'
    )

    def __init__(self, *args, semantic_understanding: Optional[SemanticUnderstanding] = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.semantic_understanding = semantic_understanding or SemanticUnderstanding(
            semantic_memory=getattr(self.memory, "semantic", None)
        )
        
        # CONVERSATION INTELLIGENCE LAYER (2026-09-18, UK requirement section 2)
        # Maintains coherent conversational state across turns, orchestrates which
        # memory is relevant, tracks mode/topic/corrections/decisions.
        from ..cognition.conversation_continuity import ConversationContinuityLayer
        from ..cognition.tool_capability_registry import get_global_registry
        session_id = kwargs.get("session_id", "default_session")
        run_id = getattr(self, "_run_id", "unknown_run")
        self.conversation_continuity = ConversationContinuityLayer(
            session_id=session_id,
            run_id=run_id,
            memory_manager=self.memory,
        )
        self.tool_registry = get_global_registry()

        # CROSS-SESSION BOOTSTRAP (2026-09-19, UK: "continuity aur
        # coherent nature stops jab restart karta hoon"). Right after
        # creating a brand-new (correctly blank) ConversationState,
        # pull real recent history from episodic memory -- which
        # survives restarts, unlike this in-memory continuity state --
        # and seed prior_session_context from it. Best-effort: episodic
        # memory may not be ready yet this early in some startup
        # orders, or this may genuinely be the first session ever, and
        # neither is an error worth failing __init__ over.
        try:
            history = self.get_conversation_history(n=6)
            if history.get("available") and history.get("turns"):
                self.conversation_continuity.bootstrap_from_history(history["turns"])
        except Exception:
            pass

        # PROJECT DIRECTORY AWARENESS + BACKUP-THEN-MODIFY (roadmap.md
        # Priority 2). ONE active project at a time, real filesystem
        # evidence only (never invented paths), with a persistent
        # (survives restarts, no git needed) change journal per
        # project. Backup tracker is created lazily per-project (it
        # needs a root directory), not here -- see
        # get_backup_tracker_for_active_project() below.
        from ..cognition.project_context import ProjectContextManager
        self.project_context = ProjectContextManager()
        self._backup_trackers: Dict[str, Any] = {}  # project root -> BackupThenModifyTracker

        # LONG-TERM GOAL STORE (2026-09-19, UK: "long term goal clear
        # ho"). Loaded once at startup -- survives restarts, unlike
        # ConversationState's session_goal/stated_goal. Path is
        # configurable via JARVIS_DATA_DIR since core/ must not import
        # backend/config.py (that would be a layering violation --
        # backend depends on core, never the reverse); falls back to a
        # relative ./data/ directory, matching where this process is
        # actually launched from.
        from ..cognition.goal_store import LongTermGoalStore
        goal_store_dir = os.environ.get("JARVIS_DATA_DIR") or os.path.join(os.getcwd(), "data")
        self.goal_store = LongTermGoalStore(os.path.join(goal_store_dir, "long_term_goals.json"))
        self.conversation_continuity.state.long_term_goals = self.goal_store.get_active_goals()

        self.last_contracts: Dict[str, Dict[str, Any]] = {}
        self._current_perception_hint: Dict[str, Any] = {}
        self._current_perception_extended: Dict[str, Any] = {}
        self.last_cognition_output = None
        self.last_router_input = None
        self.last_router_output = None
        self.last_brain_input = None
        self.last_brain_output = None
        self.last_experience_input = None
        self.last_experience_output = None
        self.last_learning_input = None
        self.last_learning_output = None
        self.last_memory_input = None
        self.last_memory_output = None
        self.last_self_evaluation_input = None
        self.last_self_evaluation_output = None
        self.last_evolution_input = None
        self.last_evolution_output = None
        self.last_runtime_contract_trace: list[dict[str, Any]] = []
        self.last_route_authority: Dict[str, Any] = {}
        self._configure_semantic_fallback()

    def get_backup_tracker_for_active_project(self) -> Optional[Any]:
        """The BackupThenModifyTracker for whichever project is
        currently active, creating it on first use for that project
        root. Returns None if no project is active -- callers (e.g.
        the coding tool, before it edits a file) must check for that
        rather than assume a tracker always exists; there is nothing
        to back up into if JARVIS doesn't know which project directory
        it's working in."""
        project = self.project_context.get_active()
        if project is None:
            return None
        root = project.root_directory
        if root not in self._backup_trackers:
            from ..cognition.backup_tracker import BackupThenModifyTracker
            self._backup_trackers[root] = BackupThenModifyTracker(root)
        return self._backup_trackers[root]

    def _configure_semantic_fallback(self) -> None:
        boundary = getattr(self.semantic_understanding, "learning_boundary", None)
        if boundary is None:
            return
        boundary.learning = self.learning
        if self.llm is None:
            return

        def fallback(request: Dict[str, Any]) -> Mapping[str, Any]:
            text_in = str(request.get("text", ""))

            # Cost-minimization: if perception's OWN cascade already
            # spent an LLM call this turn and got a usable result, reuse
            # it instead of spending a SECOND, separate LLM call here for
            # essentially the same underlying question. This directly
            # cuts the worst-case per-turn call count (perception 2 +
            # semantic understanding 2 + response 1 = 5) whenever the
            # two layers' LLM needs actually overlap, which is common --
            # both are fundamentally asking "what did the user mean".
            # Conservative: only reuses when perception's own confidence
            # was reasonably high and it actually named an intent;
            # anything softer falls through to a real (possibly retried)
            # LLM call here, same as before this optimization existed.
            hint = self._current_perception_hint or {}
            hint_source = str((hint.get("metadata") or {}).get("source", ""))
            hint_confidence = float(hint.get("confidence", 0.0) or 0.0)
            hint_intent = hint.get("basic_intent") if isinstance(hint.get("basic_intent"), dict) else {}
            if hint_source in ("llm", "llm_refined") and hint_confidence >= 0.6 and hint_intent.get("name"):
                log_event("blueprint_brain", f"reused perception's LLM result for semantic understanding, skipped a redundant call (intent={hint_intent.get('name')})", level="info")
                extended = self._current_perception_extended or {}
                return {"semantic": {
                    "normalized": text_in,
                    "intent": hint_intent,
                    "entities": [],  # perception's entities are a dict shape, semantic understanding's is list-of-dicts -- left empty rather than guessing a wrong mapping
                    "relations": list(extended.get("relations") or []),
                    "events": list(extended.get("events") or []),
                    "references": list(extended.get("references") or []),
                    "confidence": hint_confidence,
                    "provenance": {"source": "reused_from_perception_llm", "degraded": False},
                    "inferences": [],
                    "unknowns": [],
                }}

            def _degraded(reason: str) -> Mapping[str, Any]:
                # A malformed/truncated LLM response must never crash the
                # whole turn (that was surfacing as a hard "Brain Perception
                # Error" to the user for almost any non-trivial message).
                # Native-first: degrade to a low-confidence semantic result
                # and let Router/Brain keep going, same as
                # LLMPerceptionProvider already does on its own JSON failures.
                return {"semantic": {
                    "normalized": text_in,
                    "intent": {},
                    "entities": [],
                    "relations": [],
                    "events": [],
                    "references": [],
                    "confidence": 0.0,
                    "provenance": {"source": "llm_fallback", "degraded": True, "reason": reason},
                    "inferences": [],
                    "unknowns": [],
                }}

            # 256 tokens is tight for this schema (intent/entities/relations/
            # events/references/inferences/unknowns all as separate fields) --
            # verbose models truncate mid-JSON before closing every bracket,
            # which is exactly what produced "Expecting ',' delimiter" and
            # "did not return JSON" crashing whole turns in practice. 384
            # gives real headroom without materially changing latency/cost.
            budget_tokens = getattr(self.llm, "_budget_semantic_tokens", 384)

            def _attempt(reinforced_reason: Optional[str]) -> Mapping[str, Any]:
                """One extraction attempt. Raises on any failure -- the
                caller decides whether to retry or degrade. Deliberately
                NOT routed through core.contracts.extraction's generic
                cascade: that validates against the "semantic_understanding"
                contract, whose required field is "normalized_text", while
                this intermediate {"semantic": {...}} shape (reworked into
                normalized_text further up the pipeline) uses "normalized"
                -- reusing that cascade here would validate the wrong
                field name and fail every single attempt. Same retry
                philosophy, without that mismatch.
                """
                system_prompt = self._SEMANTIC_FALLBACK_PROMPT
                prompt_text = text_in
                if reinforced_reason is not None:
                    system_prompt = system_prompt + " STRICT MODE: output ONLY the JSON object -- no markdown fences, no prose before or after it."
                    prompt_text = (
                        f"Your previous output was REJECTED: {reinforced_reason}\n"
                        f"Return ONLY compact, valid JSON matching the required shape exactly, "
                        f"with every key present even if empty.\n{text_in}"
                    )
                try:
                    raw = self.llm.generate_response(
                        system_prompt=system_prompt,
                        user_input=prompt_text,
                        max_tokens=budget_tokens,
                        temperature=0.1,
                        level="perception_and_understanding",
                        # Same fix as perception.py's LLMPerceptionProvider
                        # (2026-09-11): guarantee syntactically valid JSON
                        # at the API level instead of hoping the reasoning
                        # model's free-form output happens to parse.
                        response_format={"type": "json_object"},
                        reasoning_effort="low",
                    )
                except Exception as exc:
                    # THE ACTUAL GAP that let a shared-budget shortfall crash
                    # the whole turn: generate_response() itself can raise
                    # CognitiveBudgetExceeded (or a network/model error) with
                    # nothing catching it. Escalate to the caller instead of
                    # propagating out of the semantic understanding boundary.
                    raise RuntimeError(f"LLM semantic fallback call failed: {exc}") from exc

                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw).strip(), flags=re.I | re.S).strip()
                try:
                    from ..contracts.extraction import extract_first_json_object
                    payload = extract_first_json_object(text)
                except Exception:
                    raise ValueError("LLM semantic fallback did not return JSON")

                if not isinstance(payload, dict):
                    raise ValueError("LLM semantic fallback JSON was not an object")
                semantic = payload.get("semantic", payload)
                if not isinstance(semantic, dict):
                    raise ValueError("LLM semantic fallback 'semantic' field was not an object")
                semantic.setdefault("normalized", text_in)
                semantic.setdefault("intent", {})
                semantic.setdefault("entities", [])
                semantic.setdefault("relations", [])
                semantic.setdefault("events", [])
                semantic.setdefault("references", [])
                semantic.setdefault("confidence", 0.0)
                semantic.setdefault("provenance", {"source": "llm_fallback" if reinforced_reason is None else "llm_fallback_refined"})
                semantic.setdefault("inferences", [])
                semantic.setdefault("unknowns", [])
                return {"semantic": semantic}

            # Stage 1: primary attempt.
            try:
                return _attempt(None)
            except Exception as exc:
                reason = str(exc)

            # Stage 2: ONE reinforced retry, quoting the failure back to the
            # model -- matching perception's own 3-stage cascade (see
            # core/contracts/extraction.py) instead of giving up after a
            # single JSON failure. This is the direct fix for "is this the
            # LLM's fault or JARVIS's": the model failing strict JSON once
            # is a real model limitation, but JARVIS previously never gave
            # it a genuine second attempt before discarding the data --
            # that half was an architecture gap, not the model's fault.
            # Budget-guarded: this is now the SECOND independent retry
            # stage in the same turn (perception has its own), so it must
            # not greedily spend the shared per-turn budget and starve the
            # main response call -- see can_afford_another_llm_call.
            if can_afford_another_llm_call(self.llm):
                try:
                    return _attempt(reason)
                except Exception as exc:
                    reason = str(exc)

            # Stage 3: deterministic safe default -- no further LLM calls.
            return _degraded(reason)

        boundary.llm_fallback = fallback

    def think_and_respond(self, user_input: str, identity_profile: Optional[Dict[str, Any]] = None, source: str = "cli", grounding_context: Optional[str] = None) -> str:
        """Run one real turn and capture the validator's live boundary trace.

        Background learning (the async Experience -> Learning -> Evaluate
        -> KnowledgeBuilder hand-off) is triggered exactly once per turn
        by the base class's _record_action_response(), which every mode
        branch of think_and_respond() already passes through. This used
        to ALSO be triggered here with a second, separate USER_CHAT job
        after super().think_and_respond() returned -- that duplicated
        the entire learning pipeline (double DB writes, double FAISS
        embedding calls) for every single conversational turn. Removed;
        see Brain._record_action_response for the single canonical hook.
        """
        begin_validation_trace()
        
        # CONVERSATION INTELLIGENCE LAYER HOOK (2026-09-18, UK requirement section 2)
        # Update continuity state at the START of the turn so routing decisions
        # (should_invoke_coding_agent, current_mode, etc.) have correct context.
        if hasattr(self, "conversation_continuity"):
            self.conversation_continuity.begin_turn(user_input)
        
        if self.llm is not None:
            begin_budget = getattr(self.llm, "begin_turn_budget", None)
            if callable(begin_budget):
                begin_budget()
        try:
            response = super().think_and_respond(user_input=user_input, identity_profile=identity_profile, source=source, grounding_context=grounding_context)
            
            # CONVERSATION CONTINUITY END-OF-TURN (save the turn for history/references)
            if hasattr(self, "conversation_continuity"):
                self.conversation_continuity.end_turn(user_input, response)
            
            return response
        finally:
            self.last_runtime_contract_trace = get_validation_trace()
            if self.last_turn_trace is not None:
                self.last_turn_trace["contract_validation_trace"] = list(self.last_runtime_contract_trace)
                if self.llm is not None:
                    budget_status = getattr(self.llm, "budget_status", None)
                    if callable(budget_status):
                        self.last_turn_trace["llm_budget"] = budget_status()

    def _perceive(self, user_input: str) -> Dict[str, Any]:
        # PROMPT-INJECTION SAFETY CHECK (UK's explicit ask) -- runs
        # FIRST, on the raw input, via a dedicated tiny classifier
        # model (see core/orchestration/safety.py), not the main chat
        # model. Diagnostic-only for now (see that module's honest-
        # scope note): flagged inputs are retained for review, never
        # silently blocked, since a false positive here would be worse
        # than the gap this closes.
        try:
            from .safety import check_prompt_injection
            safety_result = check_prompt_injection(user_input, getattr(self, "llm", None))
            if safety_result.get("checked"):
                self.safety_check_history.append({
                    "timestamp": time.time(), "input_text": user_input,
                    "label": safety_result.get("label"), "flagged": safety_result.get("flagged"),
                })
                if len(self.safety_check_history) > 50:
                    self.safety_check_history = self.safety_check_history[-50:]
        except Exception:
            pass

        # Native, zero-LLM-cost typo/Hinglish-shorthand correction
        # (self.typo_map, see Brain.__init__) -- this infrastructure
        # existed but was PREVIOUSLY NEVER CALLED anywhere in
        # BlueprintBrain (the class actually used in production), only
        # in the base Brain.think_and_respond(), which isn't the path
        # that runs. Real, observed consequence: perception/semantic
        # understanding routinely failed to extract anything ("nam",
        # "gielfriend", "onnly", "crator", "hye", "tunhara"...) purely
        # because of typos a simple dictionary lookup already knew how
        # to fix. The corrected text is what flows into perception AND
        # retrieval AND semantic understanding now; self._last_user_input
        # (set by the caller) still keeps the user's literal original
        # words for history/display.
        typo_result = self._normalize_hinglish_typos(user_input)
        corrected_input = typo_result["normalized"] or user_input

        perception_input = validate_input("perception", {"raw_input": str(corrected_input)})
        context = self.build_context(query=perception_input["raw_input"], recent_limit=3) if self.memory is not None else {}
        result = self.perception.perceive(perception_input["raw_input"], context=context)
        perception_output = validate_output("perception", result.as_contract_payload())
        # Cost-minimization hint for semantic understanding's own LLM
        # fallback (see _configure_semantic_fallback below): if
        # perception ALREADY paid for an LLM call and got a usable
        # intent, semantic understanding can reuse it instead of making
        # a SECOND, separate LLM round-trip for essentially the same
        # "what does this sentence mean" question. This is the direct
        # answer to "kya ek API call do kaam handle kar sakta hai" --
        # yes, for the overlap between these two layers, when
        # perception's own result is good enough. Set fresh each turn
        # (not the previous turn's self.last_perception, which isn't
        # updated until after understand() runs below).
        self._current_perception_hint = perception_output
        # Carried alongside the strict contract payload (not part of
        # it -- see PerceptionResult.relations/events/references) so
        # semantic understanding's reuse check below can use REAL
        # relations/events/references instead of always leaving them
        # empty, which would silently lose extraction quality on reuse.
        self._current_perception_extended = {
            "relations": list(getattr(result, "relations", []) or []),
            "events": list(getattr(result, "events", []) or []),
            "references": list(getattr(result, "references", []) or []),
        }
        semantic_input = validate_input("semantic_understanding", {"perception": perception_output, "user_input": perception_input["raw_input"], "semantic_context": context})
        # Translator layer (blueprint Section T) -- Stage 1 (dictionary)
        # + Stage 2 (fuzzy match), zero LLM cost, runs on every turn
        # BEFORE semantic understanding's regex sees the text. This is
        # what turns individual typo/spelling-variant bugs (mera/meri,
        # naam/Name, and any future one) into something handled
        # structurally rather than patched one at a time.
        translator_input = semantic_input["perception"]["normalized_input"]
        try:
            translated_text, translator_corrections = translator_normalize(translator_input)
        except Exception:
            translated_text, translator_corrections = translator_input, []
        # UK's #1 recall/learning/memory proposal: track repeated fuzzy
        # corrections so his own recurring typos get permanently
        # learned instead of re-paying the fuzzy-match cost every turn.
        try:
            from ..cognition.translator import record_and_maybe_promote
            record_and_maybe_promote(translator_corrections, memory=self.memory)
        except Exception:
            pass
        integrated = self.semantic_understanding.understand(translated_text, context=semantic_input["semantic_context"], retrieve=True)
        semantic = dict(integrated.get("semantic") or {})
        intent = semantic.get("intent") if isinstance(semantic.get("intent"), dict) else {}
        semantic_output = validate_output("semantic_understanding", {"normalized_text": str(semantic.get("normalized", perception_output["normalized_input"])), "intent": intent, "entities": list(semantic.get("entities") or []), "relations": list(integrated.get("relations") or semantic.get("relations") or []), "events": list(semantic.get("events") or []), "references": list(semantic.get("references") or []), "confidence": float(semantic.get("confidence", 0.0) or 0.0), "provenance": dict(semantic.get("provenance") or {"source": "native"}), "inferences": list(semantic.get("inferences") or []), "unknowns": list(semantic.get("unknowns") or [])})

        # LAYER VALIDATION REPORT (see brain.py's last_layer_validations
        # docstring) -- WHY this turn's semantic understanding produced
        # what it produced, retained as real data on Brain, not just a
        # transient CLI line. Reuses the SAME provenance/relations data
        # already computed above -- never a second, possibly-
        # inconsistent guess about what happened.
        try:
            s_relations = semantic_output["relations"]
            s_provenance = dict(semantic_output.get("provenance") or {})
            if s_relations:
                first = s_relations[0] if isinstance(s_relations[0], dict) else {}
                validation_reason = first.get("reason") or f"extracted via {s_provenance.get('source', 'unknown')}"
                validation_succeeded = True
            elif s_provenance.get("degraded"):
                validation_reason = f"extraction degraded: {s_provenance.get('reason', 'unknown')}"
                validation_succeeded = False
            else:
                validation_reason = "no statement pattern matched this input (question/greeting/command, or genuinely no fact present)"
                validation_succeeded = False
            self.last_layer_validations.append({
                "timestamp": time.time(),
                "layer": "semantic_understanding",
                "input_text": perception_input.get("raw_input", ""),
                "succeeded": validation_succeeded,
                "reason": validation_reason,
                "relations_count": len(s_relations),
                "provenance": s_provenance.get("source", "unknown"),
            })
            if len(self.last_layer_validations) > 50:
                self.last_layer_validations = self.last_layer_validations[-50:]

            # THE OTHER HALF of wiring category_word_learner in (see
            # brain.py's constructor comment): if this turn's extraction
            # came from the LLM (not native) and produced a
            # favourite_<category> relation, that predicate's words are
            # genuine vocabulary-expansion candidates -- native's own
            # attempt in THIS turn evidently didn't already know them
            # (otherwise, per the learning_boundary.py fix earlier this
            # session, native's own relation would have been trusted
            # and the LLM never called at all).
            if s_relations and s_provenance.get("source") not in ("native", None):
                learner = getattr(self, "category_word_learner", None)
                if learner is not None:
                    for rel in s_relations:
                        if isinstance(rel, dict):
                            try:
                                learner.observe_llm_extraction(
                                    predicate=rel.get("predicate", ""),
                                    input_text=perception_input.get("raw_input", ""),
                                    native_relations=[],
                                )
                            except Exception:
                                pass
        except Exception:
            pass
        # Training data collection (see core/learning/
        # training_data_collector.py for the full honest scope note):
        # every extraction outcome -- successful or a confident native
        # negative -- becomes one labeled example a FUTURE locally-
        # trained model could learn from. This does not train anything
        # itself; it is step one of the sequence toward eventually
        # reducing reliance on the regex/native layer.
        try:
            get_training_data_collector().record_example(
                input_text=perception_input["raw_input"],
                relations=semantic_output["relations"],
                entities=semantic_output["entities"],
                source=dict(semantic_output.get("provenance") or {}).get("source", "unknown"),
                confidence=semantic_output["confidence"],
            )
        except Exception:
            pass
        enriched = result.as_dict()
        semantic_intent = semantic_output["intent"] if isinstance(semantic_output["intent"], dict) else {}
        enriched.update({"normalized_text": semantic_output["normalized_text"], "intent": semantic_intent, "entities": semantic_output["entities"], "goal": semantic.get("goal") or semantic_intent.get("goal"), "language": perception_output["language"], "confidence": semantic_output["confidence"], "uncertainty": 1.0 - semantic_output["confidence"], "semantic_understanding": semantic_output, "semantic_evidence": integrated.get("evidence", {}), "semantic_learning": integrated.get("learning", {})})
        # CROSS-TURN TASK/GOAL DIGEST, side-channel (2026-09-18, Priority
        # 1 continuation -- pronoun grounding alone (active_focus, see
        # response_brief.py) only tells the LLM what a "ye/wo/isse"
        # points to THIS turn; it says nothing about the ongoing
        # task/goal across several turns. SemanticUnderstandingEngine.
        # understand() ALREADY computes exactly that every turn as
        # semantic["context"] (self._build_context_snapshot(): last
        # intent, last_events -- e.g. a real "learning_started" event
        # with its object -- and a rolling recent_turns window) but it
        # was being silently dropped here: semantic_output (the
        # strict, contract-validated dict a few lines above) only
        # copies normalized_text/intent/entities/relations/events/
        # references/confidence/provenance/inferences/unknowns, never
        # "context". Kept OUT of the strict contract (additive,
        # guarded, same pattern as semantic_evidence/semantic_learning
        # just above) so this doesn't touch core/contracts/schemas.py
        # at all -- response_brief.py reads it directly off perception.
        try:
            enriched["semantic_context_snapshot"] = dict(semantic.get("context") or {})
        except Exception:
            enriched["semantic_context_snapshot"] = {}
        self.last_perception = enriched
        self.last_contracts.update({"perception.input": perception_input, "perception.output": perception_output, "semantic_understanding.input": semantic_input, "semantic_understanding.output": semantic_output})
        return enriched

    def _build_cognition_input(self, user_input: str, perception: Dict[str, Any]) -> Dict[str, Any]:
        semantic = dict(perception.get("semantic_understanding") or {})
        if not semantic: raise RuntimeError("Semantic Understanding result is required before Cognition")
        context = self.build_context(query=semantic.get("normalized_text") or user_input, recent_limit=3)
        goals = []
        if self.goal_manager is not None:
            current_goal = getattr(self.goal_manager, "current_goal", None)
            if current_goal is not None: goals = [current_goal]
        state = {}
        if self.state is not None:
            snapshot = getattr(self.state, "snapshot", None)
            if callable(snapshot):
                try: state = dict(snapshot() or {})
                except Exception: state = {}
        cognition_input = validate_input("cognition", {"semantic": semantic, "memory": context, "knowledge": {"relevant_knowledge": context.get("relevant_knowledge", [])}, "goals": goals, "state": state, "capabilities": {"skills": getattr(self.skill_registry, "skills", {})}, "experience": context.get("recent_experiences", [])})
        self.last_cognition_input = cognition_input
        self.last_cognition_output = validate_output("cognition", {"cognitive_context": cognition_input, "confidence": float(semantic.get("confidence", 0.0) or 0.0)})
        self.last_contracts["cognition.input"] = cognition_input; self.last_contracts["cognition.output"] = self.last_cognition_output
        return cognition_input

    def _route_cognition(self, user_input: str, perception: Dict[str, Any]) -> Dict[str, Any]:
        cognition_input = self._build_cognition_input(user_input, perception)
        router_input = validate_input("cognitive_router", {"cognitive_context": cognition_input})
        decision = self.cognitive_router.decide(user_input=user_input, cognition_input=router_input["cognitive_context"])
        requested_route = str(decision.mode).lower()
        if requested_route not in self._SUPPORTED_ROUTES: raise RuntimeError(f"Router selected unsupported execution mode: {requested_route}")
        router_output = validate_output("cognitive_router", {"route": requested_route, "confidence": decision.confidence, "fallback_allowed": decision.llm_required, "evidence": list((decision.evidence or {}).items())})
        payload = decision.as_dict(); payload.update({"route": router_output["route"], "fallback_allowed": router_output["fallback_allowed"]})
        self.last_router_input = router_input; self.last_router_output = router_output; self.last_cognitive_decision = payload
        self.last_brain_input = validate_input("brain", {"cognitive_context": cognition_input, "routing_decision": router_output})
        self.last_contracts.update({"cognitive_router.input": router_input, "cognitive_router.output": router_output, "brain.input": self.last_brain_input})
        self.last_route_authority = {"router_route": requested_route, "brain_input_route": router_output["route"], "fallback_allowed": router_output["fallback_allowed"], "status": "PASS"}
        return payload

    def _enqueue_learning(self, event_type: str, context: Dict[str, Any], action: Dict[str, Any], outcome: Dict[str, Any], source: Optional[str], importance: float) -> None:
        self.last_brain_output = validate_output("brain", {"decision": dict(self.last_brain_decision or action or {}), "action": outcome.get("action") if isinstance(outcome, dict) else None, "response": outcome.get("response") if isinstance(outcome, dict) else None})
        self.last_contracts["brain.output"] = self.last_brain_output
        super()._enqueue_learning(event_type, context, action, outcome, source, importance)

    def process_experience(self, event_type: str, context: Optional[Dict[str, Any]] = None, action: Optional[Dict[str, Any]] = None, outcome: Optional[Dict[str, Any]] = None, source: Optional[str] = None, importance: float = 0.5, build_knowledge: bool = True, auto_accept: Optional[bool] = None) -> Dict[str, Any]:
        experience_input = validate_input("experience", {"event_type": str(event_type), "context": dict(context or {}), "action": dict(action or {}), "outcome": dict(outcome or {}), "source": str(source or "unknown"), "importance": float(importance)})
        self.last_experience_input = experience_input; self.last_contracts["experience.input"] = experience_input
        result = super().process_experience(event_type=experience_input["event_type"], context=experience_input["context"], action=experience_input["action"], outcome=experience_input["outcome"], source=experience_input["source"], importance=experience_input["importance"], build_knowledge=build_knowledge, auto_accept=auto_accept)
        learning_result = result.get("learning") if isinstance(result, dict) else {}; experience_payload = result.get("experience") if isinstance(result, dict) else {}; evaluation = learning_result.get("evaluation") if isinstance(learning_result, dict) else {}
        self.last_experience_output = validate_output("experience", {"evaluation": dict(evaluation or {}), "experience": dict(experience_payload or {})}); self.last_contracts["experience.output"] = self.last_experience_output
        if isinstance(learning_result, dict):
            self.last_learning_input = validate_input("learning", {"experience": dict(experience_payload or {})}); knowledge = learning_result.get("knowledge"); updates = knowledge if isinstance(knowledge, list) else ([knowledge] if knowledge is not None else [])
            self.last_learning_output = validate_output("learning", {"learning_result": learning_result, "knowledge_updates": updates}); self.last_contracts["learning.input"] = self.last_learning_input; self.last_contracts["learning.output"] = self.last_learning_output
            if isinstance(evaluation, dict):
                self.last_self_evaluation_input = validate_input("self_evaluation", {"experience": dict(experience_payload or {})}); self.last_self_evaluation_output = validate_output("self_evaluation", {"evaluation": evaluation}); self.last_contracts["self_evaluation.input"] = self.last_self_evaluation_input; self.last_contracts["self_evaluation.output"] = self.last_self_evaluation_output

            # Controlled evolution boundary: evaluation produces a proposal only.
            # Nothing is applied automatically; ControlledEvolutionEngine keeps
            # validation/approval/application as separate explicit operations.
            evolution = self.evolution
            if isinstance(evaluation, dict) and evolution is not None:
                should_propose = bool(
                    evaluation.get("errors")
                    or evaluation.get("evolution_signal")
                    or learning_result.get("knowledge") is not None
                )
                if should_propose:
                    target = str(
                        evaluation.get("evolution_target")
                        or ("knowledge_policy" if learning_result.get("knowledge") is not None else "runtime_behavior")
                    )
                    reason = str(
                        evaluation.get("evolution_reason")
                        or "Create a controlled improvement proposal from the completed self-evaluation."
                    )
                    try:
                        proposal = evolution.propose(evaluation=evaluation, target=target, reason=reason)
                        evolution_input = validate_input("evolution", {"evolution_proposal": dict(proposal)})
                        self.last_evolution_input = evolution_input
                        change_record = {
                            "type": "EVOLUTION_PROPOSAL",
                            "proposal_id": proposal.get("id"),
                            "target": proposal.get("target"),
                            "status": proposal.get("status", "PROPOSED"),
                            "applied": False,
                        }
                        evolution_output = validate_output(
                            "evolution",
                            {
                                "updated_capabilities": {
                                    "status": proposal.get("status", "PROPOSED"),
                                    "proposal_id": proposal.get("id"),
                                    "target": proposal.get("target"),
                                },
                                "change_record": change_record,
                            },
                        )
                        self.last_evolution_output = evolution_output
                        self.last_contracts["evolution.input"] = evolution_input
                        self.last_contracts["evolution.output"] = evolution_output
                        result["evolution"] = {"proposal": proposal, "output": evolution_output}
                    except Exception as evolution_error:
                        self.last_evolution_input = None
                        self.last_evolution_output = None
                        self.last_contracts.pop("evolution.input", None)
                        self.last_contracts.pop("evolution.output", None)
                        result["evolution"] = {"status": "FAILED", "error": str(evolution_error)}

            self.last_memory_input = validate_input("memory", {"learning_result": learning_result}); memory_context = {}
            if self.memory is not None:
                stats = getattr(self.memory, "statistics", None)
                if callable(stats):
                    try: memory_context = dict(stats() or {})
                    except Exception: memory_context = {}
            self.last_memory_output = validate_output("memory", {"memory_context": memory_context}); self.last_contracts["memory.input"] = self.last_memory_input; self.last_contracts["memory.output"] = self.last_memory_output
        return result

    def learn(self, experience: Dict[str, Any], auto_accept: Optional[bool] = None) -> Dict[str, Any]:
        learning_input = validate_input("learning", {"experience": dict(experience)}); result = super().learn(learning_input["experience"], auto_accept=auto_accept); knowledge = result.get("knowledge") if isinstance(result, dict) else None; updates = knowledge if isinstance(knowledge, list) else ([knowledge] if knowledge is not None else [])
        self.last_learning_input = learning_input; self.last_learning_output = validate_output("learning", {"learning_result": dict(result or {}), "knowledge_updates": updates}); self.last_contracts["learning.input"] = learning_input; self.last_contracts["learning.output"] = self.last_learning_output; return result

    def evaluate(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        self_eval_input = validate_input("self_evaluation", {"experience": dict(experience)}); result = super().evaluate(self_eval_input["experience"]); self.last_self_evaluation_input = self_eval_input; self.last_self_evaluation_output = validate_output("self_evaluation", {"evaluation": dict(result or {})}); self.last_contracts["self_evaluation.input"] = self_eval_input; self.last_contracts["self_evaluation.output"] = self.last_self_evaluation_output; return result
