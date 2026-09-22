"""CONVERSATION CONTINUITY & ORCHESTRATION LAYER.

UK requirement (section 2): The layer must ORCHESTRATE WHICH INFORMATION
IS RELEVANT instead of blindly loading everything.

This layer:
1. Maintains ConversationState across turns
2. Retrieves relevant episodic memory (not everything)
3. Detects and applies user corrections
4. Tracks topic/entity/decision/action state
5. Determines current interaction mode
6. Makes this coherent state available to perception/routing
7. Bridges between persistent memory and conversational awareness
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .conversation_state import (
    ConversationState, InteractionMode, Decision, PendingAction,
    UserCorrection, Entity,
)


class ConversationContinuityLayer:
    """Orchestrates conversation intelligence and continuity."""
    
    def __init__(self, session_id: str, run_id: str, memory_manager: Any = None):
        self.state = ConversationState(
            session_id=session_id,
            run_id=run_id,
            start_time=time.time(),
        )
        self.memory_manager = memory_manager
        self._turn_history: List[Tuple[str, str]] = []  # (user_input, jarvis_response)
    
    def begin_turn(self, user_input: str) -> None:
        """Called at the start of each turn."""
        self.state.current_turn += 1
        self.state.previous_turn_input = user_input
        
        # Store previous response if we have one
        if self._turn_history:
            _, last_response = self._turn_history[-1]
            self.state.previous_turn_response = last_response
            self.state.previous_turn_number = self.state.current_turn - 1

    def set_retrieved_reference(self, formatted_matches: str) -> None:
        """Called by the backend layer (which owns the persisted
        chat_messages table and does the actual thread_search scan)
        after finding something relevant to a backward reference in
        THIS turn's message. See core/cognition/thread_search.py.

        ORDERING (2026-09-19, real bug caught before shipping): the
        backend route calls this BEFORE invoking think_and_respond()
        (it needs the search result ready before the brief gets
        built), and think_and_respond() calls begin_turn() internally
        as its own first step -- so clearing retrieved_reference in
        begin_turn() would wipe out a value set moments earlier by the
        caller, before it was ever read. Cleared in end_turn() instead
        (the previous turn's cleanup, run once that turn is fully
        done), which still guarantees a stale match never leaks into a
        LATER turn that made no backward reference, without racing the
        very call that's supposed to populate it for the CURRENT one.
        """
        self.state.retrieved_reference = formatted_matches or None
    
    def end_turn(self, user_input: str, jarvis_response: str) -> None:
        """Called at the end of each turn to save it."""
        self._turn_history.append((user_input, jarvis_response))
        # DEFERRED CLEAR (2026-09-19) -- see set_retrieved_reference()'s
        # docstring for exactly why this is cleared HERE (once this
        # turn is fully done) rather than in begin_turn() (which would
        # race the backend's own call to set it for THIS turn).
        self.state.retrieved_reference = None
    
    def detect_interaction_mode(self, user_input: str, user_intent: Optional[Dict[str, Any]] = None) -> InteractionMode:
        """
        Determine if user wants to DISCUSS, PLAN, or EXECUTE.
        UK requirement (section 5): Distinguish these modes logically.

        ROMANIZED HINDI GAP FOUND AND FIXED 2026-09-19 (UK: "conversation
        layer ko aur robust and accurate banao"). The marker lists only
        ever had Devanagari Hindi ("बना दो") or English ("build") --
        NOT romanized Hindi in Latin script ("bana do", "karo"), which is
        how UK actually writes essentially every message in this whole
        project's chat history. "PDF reader bana do abhi" matched ZERO
        markers before this fix and fell through to UNKNOWN every time --
        a real, silent accuracy gap in the single most common way this
        detector was ever actually going to be used.
        """
        text = user_input or ""
        lowered = text.lower()
        
        # Explicit discussion/planning markers -- English, Devanagari,
        # AND romanized Hindi (Latin script) for each category.
        discussion_markers = (
            "discuss", "talk about", "think about", "understand",
            "explain", "what is", "how does", "बात करते", "समझते", "सोचते",
            "discuss करते", "सवाल", "question",
            "baat karte", "samajhte", "discuss karte", "sochte",
        )
        
        planning_markers = (
            "plan", "design", "blueprint", "architecture", "spec",
            "requirement", "before coding", "before implementation",
            "पहले plan", "पहले design", "blueprint बनाते", "architecture",
            "अभी coding नहीं", "coding नहीं अभी",
            "pehle plan", "pahle plan", "pehle design", "pahle design",
            "abhi coding nahi", "coding nahi abhi", "blueprint banao",
            "plan banao", "plan bnao",
        )
        
        execution_markers = (
            "build", "make", "create", "code", "implement", "fix", "run",
            "execute", "do it", "carry out", "start now", "immediately",
            "बना दो", "करके दो", "coding करो", "लिख दो", "implementation",
            "banao", "bana do", "bnao", "bna do", "karo", "kar do", "krdo",
            "kardo", "likh do", "likhdo", "chalao", "abhi karo", "shuru karo",
        )
        
        mode = InteractionMode.UNKNOWN
        
        # Helper to check for marker (works for both English and Hindi)
        def has_marker(text: str, marker: str) -> bool:
            # For Hindi markers (contain Devanagari), use substring match
            if re.search(r'[\u0900-\u097F]', marker):  # Devanagari Unicode range
                return marker in text
            # For English, use word boundary
            return bool(re.search(r'\b' + re.escape(marker) + r'\b', text, re.IGNORECASE))
        
        # Check for explicit markers
        for marker in discussion_markers:
            if has_marker(lowered, marker):
                mode = InteractionMode.DISCUSSION
                break
        
        if mode == InteractionMode.UNKNOWN:
            for marker in planning_markers:
                if has_marker(lowered, marker):
                    mode = InteractionMode.PLANNING
                    break
        
        if mode == InteractionMode.UNKNOWN:
            for marker in execution_markers:
                if has_marker(lowered, marker):
                    mode = InteractionMode.EXECUTION
                    break
        
        # If we have user intent from perception, use it too
        if user_intent and isinstance(user_intent, dict):
            intent_name = user_intent.get("name", "").lower()
            if intent_name == "question" and mode == InteractionMode.UNKNOWN:
                mode = InteractionMode.DISCUSSION
        
        self.state.update_mode(mode)
        return mode
    
    def detect_topic_change(self, user_input: str) -> Optional[str]:
        """Detect if the user has shifted to a new topic."""
        # Simple heuristic: look for explicit topic markers
        topic_markers = (
            "about", "regarding", "on the topic", "next topic", "another thing",
            "बारे में", "विषय", "अब", "अगला", "दूसरी बात",
        )
        
        for marker in topic_markers:
            if marker in user_input.lower():
                # Extract what comes after the marker
                pattern = r'{}\s+(.+?)(?:[\.\,\?]|$)'.format(re.escape(marker))
                match = re.search(pattern, user_input, re.IGNORECASE)
                if match:
                    new_topic = match.group(1).strip()
                    if new_topic and new_topic != self.state.current_topic:
                        self.state.topic_history.append((self.state.current_turn, new_topic))
                        self.state.current_topic = new_topic
                        return new_topic
        
        return None
    
    def detect_correction(self, user_input: str) -> Optional[Tuple[str, str]]:
        """
        Detect when user is correcting prior behavior.
        UK requirement (section 4): A correction MUST change behavior.

        HARDENED 2026-09-19 (UK: "conversation layer intelligence ko
        aur robust and accurate banao"). The previous version had two
        real accuracy bugs:
          1. English negation was a bare substring check ("not" in
             text.lower()) -- matched inside "cannot", "note",
             "notification", producing false-positive corrections on
             messages that never negated anything.
          2. The split point was found by searching the LOWER-CASED
             text, then reused as a character offset into the
             ORIGINAL text (`text[:len(parts[0])]`) -- correct only
             when lower-casing never changes string length, which
             is not guaranteed for all Unicode text, and was fragile
             reasoning even where it happened to work.
        Fixed: English markers now use \\b word-boundary regex
        (won't match inside other words), and the split point is
        found by searching the ORIGINAL text directly with
        re.IGNORECASE, never a separately-lowered copy.
        """
        text = user_input or ""
        if not text.strip():
            return None

        # Devanagari markers: substring match is correct here (word-
        # boundary regex doesn't apply the same way to this script,
        # and these tokens are distinctive enough to have low
        # collision risk as bare substrings). ROMANIZED Hindi (Latin
        # script) added 2026-09-19 -- same gap class found and fixed
        # in detect_interaction_mode(): "Termux nahi, Kali Linux use
        # karo instead" has zero Devanagari characters at all, and was
        # silently invisible to this detector despite being the exact
        # correction UK gave, repeatedly, in his own chat log.
        has_hindi_negation = any(m in text.lower() for m in ("नहीं", "मत", "गलत", "nahi", "nahin", "mat ", "galat"))
        has_hindi_alt = any(m in text.lower() for m in ("चाहिए", "बजाय", "बल्कि", "लेकिन", "chahiye", "bajaye", "bajay", "balki", "lekin"))

        # English markers: \b word boundaries so "not" doesn't match
        # inside "cannot"/"note", "but" doesn't match inside "button".
        has_english_negation = bool(re.search(r"\b(not|no|don't|doesn't|isn't|wasn't|wrong)\b", text, re.IGNORECASE))
        has_english_alt = bool(re.search(r"\b(instead|but|should|rather)\b", text, re.IGNORECASE))

        has_negation = has_hindi_negation or has_english_negation
        has_alternative = has_hindi_alt or has_english_alt or (";" in text)

        if not (has_negation and has_alternative):
            return None

        # SPLIT (2026-09-19, hardened). Prefer a comma or semicolon --
        # most real correction phrasing naturally has one ("not X,
        # use Y instead" / "X nahi, Y chahiye") -- but comma is ONLY
        # used as a split point here, never as its own has_alternative
        # trigger above, so "not sure, can you help?" still correctly
        # returns None rather than being misread as a correction.
        # A trailing "instead" (very common: "...use Y instead", where
        # "instead" modifies backward, not a middle connector like
        # "but") is stripped from the second half rather than used as
        # the split point itself -- splitting ON "instead" when it's
        # the LAST word left an empty second half and silently failed
        # to detect the correction at all (found by this fix's own
        # test against UK's real phrasing).
        for sep_char in (";", ","):
            if sep_char in text:
                parts = text.split(sep_char, 1)
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    before = parts[0].strip()
                    after = re.sub(r"\s*\binstead\b\s*$", "", parts[1].strip(), flags=re.IGNORECASE).strip()
                    if before and after:
                        return (before, after)

        # Otherwise split on the FIRST separator word, located directly
        # in the original text (no lower-then-reslice fragility).
        sep_match = re.search(
            r"\b(instead|but|rather|बल्कि|लेकिन|बजाय|bajaye|bajay|balki|lekin)\b",
            text, re.IGNORECASE,
        )
        if sep_match:
            before = text[:sep_match.start()].strip()
            after = text[sep_match.end():].strip()
            if before and after:
                return (before, after)

        return None
    
    def update_from_turn(
        self,
        user_input: str,
        user_intent: Optional[Dict[str, Any]] = None,
        perception_entities: Optional[List[str]] = None,
    ) -> None:
        """
        Update conversation state based on the current turn's input and
        perception results.

        BUG FOUND AND FIXED 2026-09-19 (UK: "conversation layer
        intelligence ko aur robust and accurate banao"): this method
        never actually assigned self.state.user_intent or
        self.state.stated_goal -- a codebase-wide grep confirms NEITHER
        was ever assigned anywhere outside this fix. should_invoke_
        coding_agent()'s EXECUTION-mode branch requires one of them to
        be truthy before returning True, so that check was permanently
        unreachable in real usage -- the only place it ever returned
        True was tests/test_continuity_layer.py, which manually pokes
        state.stated_goal in its own setup, masking that the real
        wiring never did. Concretely: since pass 6 wired
        should_invoke_coding_agent() as routes_codebox.py's second gate
        on FULL_BUILD, this meant that gate ALWAYS failed and every
        full_build classification was silently downgraded to
        "planning" -- JARVIS could never actually execute a build
        through this path, only ever plan one, regardless of how
        clearly the user asked. Fixed below.
        """
        # Update mode
        mode = self.detect_interaction_mode(user_input, user_intent)

        # RECORD WHAT WAS ACTUALLY DECIDED (the fix above). user_intent
        # is stored whenever perception supplied one, since it's real
        # evidence about what this turn is regardless of mode.
        # stated_goal is set specifically when this turn reads as
        # EXECUTION -- the user's own words ARE the goal in that case,
        # not something to invent or infer beyond what they typed.
        if user_intent:
            self.state.user_intent = user_intent
        if mode == InteractionMode.EXECUTION and user_input:
            self.state.stated_goal = user_input.strip()
            # SESSION GOAL (2026-09-19, UK: "session goal clear ho").
            # The FIRST real stated_goal of a session becomes the
            # session_goal automatically -- it does not change on every
            # later EXECUTION turn the way stated_goal does, so it
            # survives being asked to also plan/discuss/fix things
            # around that same overarching task. Explicit correction to
            # THIS is still possible via set_session_goal(force=True),
            # called separately, never inferred here.
            self.state.set_session_goal(user_input.strip())

        # Detect topic change
        self.detect_topic_change(user_input)
        
        # Detect correction
        correction = self.detect_correction(user_input)
        if correction:
            what_wrong, should_be = correction
            self.state.record_correction(what_wrong, should_be, user_input)
        
        # Register entities mentioned (from perception)
        if perception_entities:
            for entity_name in perception_entities:
                if entity_name.lower() not in self.state.entities:
                    self.state.add_entity(entity_name, "unknown")
    
    def bootstrap_from_history(self, turns: List[Dict[str, Any]], max_turns: int = 5) -> None:
        """Reconstruct enough continuity to feel coherent right after a
        restart, from REAL persisted history -- not a guess.

        UK's explicit ask: "continuity aur coherent nature stops jab
        restart karta hoon" -- a brand-new ConversationState is correct
        for a genuinely new conversation, but wrong for "the process
        just restarted, the person is still mid-task". `turns` is the
        exact shape Brain.get_conversation_history() already returns
        (which itself reads episodic memory WITHOUT same_run_only, so
        it naturally spans restarts) -- {"user_said", "jarvis_replied",
        "timestamp"} per turn, most recent last.

        Deliberately does NOT try to re-derive session_goal/
        current_topic from the old text via keyword heuristics -- that
        risks confidently inventing the wrong thing (this project's own
        romanized-Hindi detector bugs earlier this session are exactly
        why that risk is real). Instead: the real prior turns go
        straight into prior_session_context, verbatim, the same way any
        other grounding context reaches the LLM -- it can read what
        actually happened and use it correctly, rather than trust a
        second-hand summary that might be wrong.

        One exception, using EXISTING hardened logic rather than new
        heuristics: if the most recent prior turn reads as EXECUTION
        mode (detect_interaction_mode(), already covers English/
        Devanagari/romanized Hindi), it's reasonable to seed
        session_goal from it -- set_session_goal() only ever sets it
        ONCE anyway, so a real turn-1 stated_goal later in THIS session
        still overrides it if this guess was wrong.
        """
        if not turns:
            return

        recent = turns[-max_turns:]
        lines = []
        for t in recent:
            user_said = t.get("user_said")
            jarvis_replied = t.get("jarvis_replied")
            if user_said:
                lines.append(f"UK: {user_said}")
            if jarvis_replied:
                lines.append(f"JARVIS: {jarvis_replied}")
        if lines:
            self.state.prior_session_context = "\n".join(lines)

        last_user_said = None
        for t in reversed(recent):
            if t.get("user_said"):
                last_user_said = t["user_said"]
                break
        if last_user_said:
            mode = self.detect_interaction_mode(last_user_said)
            if mode == InteractionMode.EXECUTION:
                self.state.set_session_goal(last_user_said.strip())

    def get_relevant_context(self, max_turns_back: int = 5) -> Dict[str, Any]:
        """
        Return only the relevant context for THIS turn.
        UK requirement (section 2): Orchestrate which information is relevant,
        don't blindly load everything.
        """
        return {
            "current_topic": self.state.current_topic,
            "current_subtopic": self.state.current_subtopic,
            "active_project": self.state.active_project,
            "active_tool": self.state.active_tool,
            "interaction_mode": self.state.interaction_mode.value,
            "user_intent": self.state.user_intent,
            # GOAL HIERARCHY (2026-09-19) -- see ConversationState.
            # get_goal_hierarchy()'s docstring for what each tier means.
            "current_turn_goal": self.state.stated_goal,
            "session_goal": self.state.session_goal,
            # CROSS-SESSION (2026-09-19) -- see bootstrap_from_history()'s
            # docstring. Only non-None right after a restart with real
            # prior history; a session that's been continuously running
            # never needed this.
            "prior_session_context": self.state.prior_session_context,
            "retrieved_reference": self.state.retrieved_reference,
            "long_term_goals": list(self.state.long_term_goals),
            "pending_actions": [
                {"what": a.what, "turn": a.turn_number, "blocked_by": a.blocked_by}
                for a in self.state.pending_actions
            ],
            "recent_decisions": [
                {"what": d.what, "turn": d.turn_number}
                for d in self.state.decisions_this_session[-3:]
            ],
            "unresolved_questions": self.state.unresolved_questions,
            "last_question_asked": self.state.last_question_asked,
            "last_named_entity": self.state.last_named_entity,
            "awaiting_user_response": self.state.awaiting_user_response,
            "recent_corrections": [
                {"was": c.what_was_wrong, "now": c.correct_behavior}
                for c in self.state.corrections_this_session[-2:]
            ],
            "created_tools": list(self.state.created_tools.keys()),
            "available_capabilities": list(self.state.available_capabilities),
        }
    
    def format_relevant_context_text(self) -> str:
        """Single source of truth for turning get_relevant_context()
        into the plain-text block an LLM call's context/system prompt
        actually reads.

        FACTORED OUT 2026-09-20 (root-cause pass, UK's chat-log audit):
        this exact formatting used to be hand-duplicated inline inside
        backend/routes_codebox.py's think_stream_route (continuity_ctx
        block) -- the precise "two reasoning paths quietly drift apart"
        bug class this whole project keeps re-discovering (TaskLoop
        context bug, session_goal/prior_session_context gap, etc, all
        logged in CHANGELOG_this_pass.md). Any NEW caller that needs
        continuity text in a prompt -- ordinary chat's tool-calling
        loop included -- calls this ONE method instead of re-deriving
        its own copy that can silently go stale. routes_codebox.py's
        continuity_ctx is now a thin call-site of this same method.
        """
        relevant = self.get_relevant_context()
        lines: List[str] = []
        if relevant.get("session_goal"):
            lines.append(f"Session goal (what this whole session is working toward): {relevant['session_goal']}")
        if relevant.get("prior_session_context"):
            lines.append(f"Context from before this session restarted:\n{relevant['prior_session_context']}")
        if relevant.get("current_topic"):
            lines.append(f"Current topic: {relevant['current_topic']}")
        if relevant.get("last_named_entity"):
            lines.append(f"Last thing discussed: {relevant['last_named_entity']}")
        if relevant.get("interaction_mode") and relevant["interaction_mode"] != "unknown":
            lines.append(f"Interaction mode so far: {relevant['interaction_mode']}")
        if relevant.get("pending_actions"):
            lines.append("Pending: " + "; ".join(a["what"] for a in relevant["pending_actions"][:3]))
        if relevant.get("recent_decisions"):
            lines.append("Recent decisions: " + "; ".join(d["what"] for d in relevant["recent_decisions"]))
        if relevant.get("recent_corrections"):
            lines.append("Recent correction (a STANDING constraint, not a one-off mention): " + "; ".join(
                f"not {c['was']}, now {c['now']}" for c in relevant["recent_corrections"]
            ))
        if not lines:
            return ""
        return "Conversation so far:\n" + "\n".join(lines)

    def resolve_pronoun(self, pronoun: str, user_input: str) -> Optional[str]:
        """
        Resolve pronouns like "this", "that", "it", "previous" to actual entities.
        UK requirement (section 1): JARVIS must understand what references mean.
        """
        pronoun_lower = pronoun.lower()
        
        # Check pronoun_referents map
        if pronoun_lower in self.state.pronoun_referents:
            return self.state.pronoun_referents[pronoun_lower]
        
        # Check conversation history for context
        if pronoun_lower in ("this", "it", "that") and self.state.last_named_entity:
            return self.state.last_named_entity
        
        if pronoun_lower in ("previous", "last", "earlier"):
            if self.state.previous_turn_input:
                # Try to extract main entity from previous turn
                return self.state.previous_turn_input[:50]  # First 50 chars as context
        
        return None
    
    def should_invoke_coding_agent(self) -> bool:
        """
        Decide if the coding agent should be invoked.
        UK requirement (section 7): JARVIS decides, not the LLM alone.

        BUG FOUND BY tests/test_e2e_scenarios.py (2026-09-18): the
        EXECUTION-mode check used to `return True` immediately, before
        the correction guard below it ever ran -- so "don't invoke
        right after a correction" was dead code whenever mode was
        already EXECUTION, which is exactly the situation a mid-build
        correction happens in. Order matters here: the correction
        guard must run FIRST, since it's an override on top of an
        otherwise-affirmative decision, not an alternative path.
        """
        # GUARD FIRST: never invoke immediately after a correction on
        # THIS turn -- the user just changed what they want, and
        # launching a build off the old (or an unconfirmed new) plan
        # is exactly the "correction acknowledged but not applied"
        # failure UK described (section 4).
        if self.state.corrections_this_session and self.state.corrections_this_session[-1].turn_number == self.state.current_turn:
            return False

        # Only invoke if mode is EXECUTION AND there's a clear task to build.
        if self.state.interaction_mode == InteractionMode.EXECUTION:
            if self.state.stated_goal or self.state.user_intent:
                return True

        return False
    
    def apply_learned_correction(self, pattern: str) -> bool:
        """Apply a learned behavioral correction if relevant."""
        if pattern in self.state.learned_corrections:
            # This correction should be applied
            return True
        return False
