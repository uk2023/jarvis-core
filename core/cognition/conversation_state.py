"""CONVERSATION STATE MANAGEMENT.

UK requirement (section 2): JARVIS must continuously maintain coherent
conversational state tracking:
  - current conversation/session
  - current topic
  - current sub-topic
  - active user goal
  - user intent
  - entities/projects/tools
  - references to previous turns
  - previous decisions
  - user corrections
  - unresolved questions
  - pending actions
  - completed actions
  - current interaction mode
  - relevant historical context
  - tool/project state

This module manages that state as a real persistent object, not a
keyword-matching heuristic or a hallucinated guess.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class InteractionMode(Enum):
    """UK requirement (section 5): Distinguish discussion/planning/execution modes."""
    DISCUSSION = "discussion"
    PLANNING = "planning"
    EXECUTION = "execution"
    RESEARCH = "research"
    UNKNOWN = "unknown"


@dataclass
class Decision:
    """A decision made during the conversation."""
    what: str  # what was decided
    when: float  # timestamp
    turn_number: int
    user_requested: bool = True
    evidence: Optional[str] = None  # what the user said that led to this


@dataclass
class PendingAction:
    """An action that hasn't been completed yet."""
    what: str
    when_started: float
    turn_number: int
    blocked_by: Optional[str] = None  # why it's not complete
    requires_user_input: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserCorrection:
    """A correction the user made to prior behavior."""
    what_was_wrong: str
    correct_behavior: str
    when: float
    turn_number: int
    evidence: str  # what the user said
    apply_to_future: bool = True


@dataclass
class Entity:
    """An entity being discussed (tool, project, concept, etc.)."""
    name: str
    type: str  # "tool", "project", "concept", "file", etc.
    first_mentioned: int  # turn number
    last_mentioned: int  # turn number
    properties: Dict[str, Any] = field(default_factory=dict)
    references: List[str] = field(default_factory=list)  # "this", "it", "that", etc.


@dataclass
class ConversationState:
    """The coherent state of the current conversation.
    
    This is NOT the entire memory system; it's the **relevant right now**
    slice of it. Perception and routing use this to understand the
    current context, not raw memory dumps.
    """
    
    session_id: str
    run_id: str
    start_time: float
    current_turn: int = 0
    
    # Topic tracking
    current_topic: Optional[str] = None
    current_subtopic: Optional[str] = None
    topic_history: List[tuple[int, str]] = field(default_factory=list)  # (turn, topic)
    
    # Entity/project/tool tracking
    entities: Dict[str, Entity] = field(default_factory=dict)  # name -> Entity
    active_project: Optional[str] = None
    active_tool: Optional[str] = None
    
    # User intent and goal
    user_intent: Optional[str] = None  # what the user is trying to accomplish
    stated_goal: Optional[str] = None  # what they explicitly said they want THIS TURN

    # GOAL HIERARCHY (2026-09-19, UK: "session goal, current goal, long
    # term goal sab clear ho"). Three distinct scopes, deliberately kept
    # separate rather than collapsed into one field, because they answer
    # different questions and get overwritten at different rates:
    #   stated_goal    -- what THIS turn is asking for (already existed,
    #                      overwritten every EXECUTION-mode turn).
    #   session_goal   -- the overarching thing this whole session is
    #                      working toward (set once, from the first real
    #                      stated_goal of the session; survives many
    #                      turns of discussion/planning/correction around
    #                      it without being overwritten by each one).
    #   long_term_goals -- goals that outlive this session entirely,
    #                      loaded from persistent storage at startup
    #                      (see core/cognition/goal_store.py) and only
    #                      added to explicitly, never silently inferred.
    session_goal: Optional[str] = None
    session_goal_set_at_turn: Optional[int] = None
    long_term_goals: List[str] = field(default_factory=list)

    # CROSS-SESSION CONTINUITY (2026-09-19, UK: "continuity aur coherent
    # nature stops jab restart karta hoon"). Everything above this line
    # resets to blank on a fresh ConversationState -- correct for
    # brand-new session state, but it meant restarting lost ALL
    # awareness of what was happening before, even though episodic
    # memory itself survives restarts fine. bootstrap_from_history()
    # (see ConversationContinuityLayer) fills this ONE field from real
    # persisted history at startup -- deliberately not auto-deriving
    # session_goal/current_topic from raw historical text via
    # heuristics that could misfire; the LLM gets the real prior turns
    # verbatim instead and can use them directly, exactly the way it
    # would use any other grounding context.
    prior_session_context: Optional[str] = None

    # THREAD-WIDE SEARCH RESULT (2026-09-19). Set per-turn (see
    # ConversationContinuityLayer.begin_turn(), which clears it fresh
    # every turn -- a stale match from a PREVIOUS turn's backward
    # reference must never leak into a turn that didn't ask for one)
    # when core.cognition.thread_search finds something relevant to a
    # backward reference the user made with NO time hint. Distinct
    # from prior_session_context (that's specifically "right before a
    # restart"; this is "found anywhere in this thread's full history,
    # triggered by what the user just said").
    retrieved_reference: Optional[str] = None
    
    # Decision tracking
    decisions_this_session: List[Decision] = field(default_factory=list)
    pending_decisions: List[str] = field(default_factory=list)
    
    # Action tracking
    pending_actions: List[PendingAction] = field(default_factory=list)
    completed_actions: List[str] = field(default_factory=list)
    
    # Correction tracking
    corrections_this_session: List[UserCorrection] = field(default_factory=list)
    learned_corrections: Dict[str, str] = field(default_factory=dict)  # pattern -> correct_behavior
    
    # Mode tracking
    interaction_mode: InteractionMode = InteractionMode.UNKNOWN
    mode_changed_at_turn: int = 0
    
    # References/pronouns
    pronoun_referents: Dict[str, str] = field(default_factory=dict)  # "this" -> "PDF reader", "it" -> "project_x"
    last_topic_introduced: Optional[str] = None
    last_named_entity: Optional[str] = None
    
    # Tool/capability state
    created_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # name -> {path, created_at, verified, registered}
    available_capabilities: Set[str] = field(default_factory=set)
    
    # Communication with user
    last_question_asked: Optional[str] = None
    awaiting_user_response: bool = False
    unresolved_questions: List[str] = field(default_factory=list)
    
    # Previous turn info (for "last response", "you said", etc.)
    previous_turn_input: Optional[str] = None
    previous_turn_response: Optional[str] = None
    previous_turn_number: Optional[int] = None
    
    def update_mode(self, new_mode: InteractionMode) -> bool:
        """Update interaction mode if it changed."""
        if new_mode != self.interaction_mode:
            self.interaction_mode = new_mode
            self.mode_changed_at_turn = self.current_turn
            return True
        return False
    
    def add_entity(self, name: str, type_: str, properties: Optional[Dict[str, Any]] = None) -> Entity:
        """Register an entity being discussed."""
        entity = Entity(
            name=name,
            type=type_,
            first_mentioned=self.current_turn,
            last_mentioned=self.current_turn,
            properties=properties or {},
        )
        self.entities[name.lower()] = entity
        self.last_named_entity = name
        return entity
    
    def reference_entity(self, reference: str, entity_name: str) -> None:
        """Link a pronoun/reference to an entity."""
        key = reference.lower()
        self.pronoun_referents[key] = entity_name
        if entity_name.lower() in self.entities:
            self.entities[entity_name.lower()].references.append(reference)
            self.entities[entity_name.lower()].last_mentioned = self.current_turn
    
    def set_session_goal(self, goal: str, force: bool = False) -> bool:
        """Set the session's overarching goal -- once, unless force=True.

        Called automatically (see ConversationContinuityLayer.update_
        from_turn()) the first time a real stated_goal appears in a
        session, and callable directly for an explicit correction to
        the session goal itself ("nahi, hum PDF reader nahi, OCR solver
        bana rahe hain" -- a correction to what the whole session is
        about, not just this turn). Returns True if it was actually
        set/changed, False if a goal already existed and force=False.
        """
        if self.session_goal is not None and not force:
            return False
        self.session_goal = goal
        self.session_goal_set_at_turn = self.current_turn
        return True

    def add_long_term_goal(self, goal: str) -> None:
        """Add a goal that should outlive this session. Deliberately
        never called automatically from turn content -- see goal_store.py
        for the explicit, auditable path a goal takes to become
        long-term (this only updates the in-memory list for THIS
        session's context; persistence is the caller's job)."""
        if goal not in self.long_term_goals:
            self.long_term_goals.append(goal)

    def get_goal_hierarchy(self) -> Dict[str, Any]:
        """The clean, three-tier view UK asked for: what THIS turn
        wants, what the whole SESSION is working toward, and what
        outlives this session entirely. Never returns invented content
        -- any tier that hasn't been set is None/empty, not guessed."""
        return {
            "current_turn_goal": self.stated_goal,
            "session_goal": self.session_goal,
            "long_term_goals": list(self.long_term_goals),
        }

    def record_decision(self, what: str, evidence: str, user_requested: bool = True) -> Decision:
        """Record a decision made during this conversation."""
        decision = Decision(
            what=what,
            when=time.time(),
            turn_number=self.current_turn,
            evidence=evidence,
            user_requested=user_requested,
        )
        self.decisions_this_session.append(decision)
        return decision
    
    def record_correction(self, was_wrong: str, should_be: str, evidence: str) -> UserCorrection:
        """Record a user correction that should influence future behavior."""
        correction = UserCorrection(
            what_was_wrong=was_wrong,
            correct_behavior=should_be,
            when=time.time(),
            turn_number=self.current_turn,
            evidence=evidence,
        )
        self.corrections_this_session.append(correction)
        return correction
    
    def add_pending_action(self, what: str, details: Optional[Dict[str, Any]] = None) -> PendingAction:
        """Register an action that still needs to happen."""
        action = PendingAction(
            what=what,
            when_started=time.time(),
            turn_number=self.current_turn,
            details=details or {},
        )
        self.pending_actions.append(action)
        return action
    
    def complete_pending_action(self, index_or_what: int | str) -> bool:
        """Mark a pending action as completed."""
        if isinstance(index_or_what, int):
            if 0 <= index_or_what < len(self.pending_actions):
                action = self.pending_actions.pop(index_or_what)
                self.completed_actions.append(action.what)
                return True
        else:
            for i, action in enumerate(self.pending_actions):
                if action.what.lower() == index_or_what.lower():
                    action_what = self.pending_actions.pop(i).what
                    self.completed_actions.append(action_what)
                    return True
        return False
    
    def register_tool(self, name: str, path: str, verified: bool = False, registered: bool = False) -> None:
        """Record a tool that was created."""
        self.created_tools[name] = {
            "path": path,
            "created_at": time.time(),
            "verified": verified,
            "registered": registered,
            "created_turn": self.current_turn,
        }
        self.add_entity(name, "tool", {"path": path})
    
    def resolve_pronoun(self, pronoun: str) -> Optional[str]:
        """Resolve 'this', 'that', 'it', 'previous' to actual entity."""
        key = pronoun.lower()
        if key in self.pronoun_referents:
            return self.pronoun_referents[key]
        if key in ("this", "it", "that"):
            return self.last_named_entity
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/storage."""
        d = asdict(self)
        d["interaction_mode"] = self.interaction_mode.value
        return d
