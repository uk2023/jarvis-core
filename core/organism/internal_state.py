from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class InternalState:
    """
    Runtime state of the JARVIS organism.

    This is NOT personality and NOT memory.

    Memory answers:
        "What happened before?"

    InternalState answers:
        "What is happening inside the organism RIGHT NOW?"

    The state is intentionally model-independent.
    """

    VERSION = "0.1.0"

    def __init__(self):
        # ---------------------------------------------------------
        # Lifecycle
        # ---------------------------------------------------------
        self.mode = "BOOT"
        self.running = False

        # ---------------------------------------------------------
        # Attention / cognition
        # ---------------------------------------------------------
        self.attention: Optional[str] = None
        self.focus: Optional[str] = None
        self.cognitive_load = 0.0
        self.uncertainty = 0.0
        self.confidence = 0.0

        # ---------------------------------------------------------
        # Current activity
        # ---------------------------------------------------------
        self.active_task: Optional[Dict[str, Any]] = None
        self.current_goal: Optional[Dict[str, Any]] = None
        self.pending_tasks: List[Dict[str, Any]] = []

        # ---------------------------------------------------------
        # Learning
        # ---------------------------------------------------------
        self.learning_state = "IDLE"
        self.last_learning_result: Optional[Dict[str, Any]] = None
        self.learning_count = 0

        # ---------------------------------------------------------
        # Conversation
        # ---------------------------------------------------------
        self.conversation_active = False
        self.last_user_input: Optional[str] = None
        self.last_response: Optional[str] = None

        # ---------------------------------------------------------
        # Perception / routing
        # ---------------------------------------------------------
        self.last_intent: Optional[str] = None
        self.last_route: Optional[str] = None
        self.last_perception: Optional[Dict[str, Any]] = None

        # ---------------------------------------------------------
        # Organism events
        # ---------------------------------------------------------
        self.last_event: Optional[Dict[str, Any]] = None
        self.event_count = 0

        # ---------------------------------------------------------
        # Autonomy
        # ---------------------------------------------------------
        self.autonomy_enabled = False
        self.autonomy_state = "DORMANT"
        self.last_autonomous_action: Optional[Dict[str, Any]] = None

        # ---------------------------------------------------------
        # Runtime timestamps
        # ---------------------------------------------------------
        now = time.time()

        self.created_at = now
        self.updated_at = now
        self.last_activity_at = now

    # =============================================================
    # GENERIC UPDATE
    # =============================================================

    def update(self, **changes) -> None:
        """
        Update known state fields.

        Unknown fields are intentionally rejected rather than silently
        creating random state variables.
        """

        for key, value in changes.items():

            if not hasattr(self, key):
                raise AttributeError(
                    f"InternalState has no field '{key}'"
                )

            setattr(self, key, value)

        now = time.time()

        self.updated_at = now
        # THE ACTUAL IDLE-DETECTION BUG: this used to touch
        # last_activity_at unconditionally on EVERY call to update(),
        # regardless of what was actually being changed. Perception
        # (last_perception=...) and Brain (last_route=...) both call
        # update() as part of ordinary internal bookkeeping on every
        # single turn -- that's real engineering telemetry, not a
        # signal that "the USER is active right now". Because those
        # calls kept re-stamping last_activity_at to "now", Heartbeat's
        # idle detection (inactive_for = now - last_activity_at) almost
        # never crossed the idle_threshold even when the person hadn't
        # typed anything in a long time, so IdleLoop rarely got a real
        # chance to run. Only touch last_activity_at when the caller
        # explicitly means it (i.e. it's one of the changed keys) --
        # cli.py's `jarvis.state.update(last_activity_at=now)` on every
        # real user message is exactly that explicit signal; internal
        # bookkeeping calls that don't mention it no longer smuggle in
        # a side effect that resets the idle clock.
        if "last_activity_at" not in changes:
            return
        self.last_activity_at = now

    # =============================================================
    # EVENT
    # =============================================================

    def record_event(
        self,
        event_name: str,
        payload: Any = None,
        source: Optional[str] = None,
    ) -> None:
        """
        Record the latest organism event.
        """

        self.last_event = {
            "name": event_name,
            "payload": payload,
            "source": source,
            "timestamp": time.time(),
        }

        self.event_count += 1

        self.updated_at = time.time()
        # THE ROOT CAUSE of idle_loop never running, ever, including
        # across a full idle overnight session: EventBus.emit() calls
        # record_event() for EVERY event on the bus, and Heartbeat
        # itself emits a "HEARTBEAT" event every 5 seconds (its own
        # `interval`) as part of just staying alive -- completely
        # independent of whether the user has done anything. With the
        # previous unconditional `self.last_activity_at = self.updated_at`
        # here, the heartbeat's own self-emission re-stamped
        # last_activity_at to "now" every single beat, so
        # `inactive_for = now - last_activity_at` could never exceed
        # one heartbeat interval (~5s) -- it could NEVER reach the 30s
        # idle_threshold, so `is_idle` could never become True, so
        # IdleLoop.step() was never reachable, structurally, regardless
        # of how long the process actually sat with no user input.
        # "USER_INPUT" (see cli.py's jarvis.receive_event("USER_INPUT",
        # ...)) is the one event name that genuinely means "a person
        # just did something" -- only that should reset the idle clock;
        # every other event here is internal engineering telemetry.
        if event_name == "USER_INPUT":
            self.last_activity_at = self.updated_at

    # =============================================================
    # USER INTERACTION
    # =============================================================

    def record_user_input(
        self,
        text: str,
        intent: Optional[str] = None,
        route: Optional[str] = None,
    ) -> None:

        self.last_user_input = text
        self.last_intent = intent
        self.last_route = route
        self.conversation_active = True

        self.updated_at = time.time()
        self.last_activity_at = self.updated_at

    def record_response(self, response: str) -> None:

        self.last_response = response

        self.updated_at = time.time()
        self.last_activity_at = self.updated_at

    # =============================================================
    # COGNITIVE STATE
    # =============================================================

    def set_attention(
        self,
        attention: Optional[str],
        confidence: float = 0.0,
    ) -> None:

        self.attention = attention
        self.confidence = self._clamp(confidence)

        self.updated_at = time.time()

    def set_uncertainty(self, value: float) -> None:
        self.uncertainty = self._clamp(value)

        self.updated_at = time.time()

    def set_cognitive_load(self, value: float) -> None:
        self.cognitive_load = self._clamp(value)

        self.updated_at = time.time()

    # =============================================================
    # TASK STATE
    # =============================================================

    def start_task(
        self,
        task_id: str,
        description: str,
        source: str = "USER",
    ) -> None:

        self.active_task = {
            "id": task_id,
            "description": description,
            "source": source,
            "started_at": time.time(),
            "status": "RUNNING",
        }

        self.updated_at = time.time()

    def finish_task(
        self,
        success: bool,
        result: Any = None,
    ) -> None:

        if self.active_task is None:
            return

        self.active_task["status"] = (
            "COMPLETED" if success else "FAILED"
        )

        self.active_task["success"] = success
        self.active_task["result"] = result
        self.active_task["finished_at"] = time.time()

        self.updated_at = time.time()

    def clear_active_task(self) -> None:
        self.active_task = None
        self.updated_at = time.time()

    # =============================================================
    # GOALS
    # =============================================================

    def set_goal(
        self,
        goal_id: str,
        description: str,
        source: str = "AUTONOMOUS",
    ) -> None:

        self.current_goal = {
            "id": goal_id,
            "description": description,
            "source": source,
            "status": "ACTIVE",
            "created_at": time.time(),
        }

        self.updated_at = time.time()

    def clear_goal(self) -> None:
        self.current_goal = None
        self.updated_at = time.time()

    # =============================================================
    # LEARNING
    # =============================================================

    def begin_learning(self) -> None:
        self.learning_state = "LEARNING"
        self.updated_at = time.time()

    def record_learning(
        self,
        result: Dict[str, Any],
    ) -> None:

        self.learning_state = "UPDATED"
        self.last_learning_result = result
        self.learning_count += 1

        self.updated_at = time.time()

    def finish_learning(self) -> None:
        self.learning_state = "IDLE"
        self.updated_at = time.time()

    # =============================================================
    # AUTONOMY
    # =============================================================

    def enable_autonomy(self) -> None:
        self.autonomy_enabled = True
        self.autonomy_state = "READY"

        self.updated_at = time.time()

    def disable_autonomy(self) -> None:
        self.autonomy_enabled = False
        self.autonomy_state = "DORMANT"

        self.updated_at = time.time()

    def record_autonomous_action(
        self,
        action: Dict[str, Any],
    ) -> None:

        self.last_autonomous_action = action
        self.autonomy_state = "ACTIVE"

        self.updated_at = time.time()

    # =============================================================
    # PERCEPTION
    # =============================================================

    def record_perception(
        self,
        perception: Dict[str, Any],
    ) -> None:

        self.last_perception = perception

        self.updated_at = time.time()

    # =============================================================
    # SNAPSHOT
    # =============================================================

    def snapshot(self) -> Dict[str, Any]:
        """
        Return serializable state.

        This snapshot will later be persisted to SQLite so that
        JARVIS can restore important state after Android restart.
        """

        return {
            "version": self.VERSION,

            "lifecycle": {
                "mode": self.mode,
                "running": self.running,
            },

            "cognition": {
                "attention": self.attention,
                "focus": self.focus,
                "cognitive_load": self.cognitive_load,
                "uncertainty": self.uncertainty,
                "confidence": self.confidence,
            },

            "activity": {
                "active_task": self.active_task,
                "current_goal": self.current_goal,
                "pending_tasks": list(self.pending_tasks),
            },

            "learning": {
                "state": self.learning_state,
                "last_result": self.last_learning_result,
                "count": self.learning_count,
            },

            "conversation": {
                "active": self.conversation_active,
                "last_user_input": self.last_user_input,
                "last_response": self.last_response,
            },

            "perception": {
                "last_intent": self.last_intent,
                "last_route": self.last_route,
                "last_perception": self.last_perception,
            },

            "events": {
                "last_event": self.last_event,
                "count": self.event_count,
            },

            "autonomy": {
                "enabled": self.autonomy_enabled,
                "state": self.autonomy_state,
                "last_action": self.last_autonomous_action,
            },

            "timestamps": {
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "last_activity_at": self.last_activity_at,
            },
        }

    # =============================================================
    # RESTORE
    # =============================================================

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """
        Restore state from a previously persisted snapshot.

        This is intentionally conservative: only known fields are
        restored.
        """

        if not isinstance(snapshot, dict):
            return

        lifecycle = snapshot.get("lifecycle", {})
        cognition = snapshot.get("cognition", {})
        activity = snapshot.get("activity", {})
        learning = snapshot.get("learning", {})
        conversation = snapshot.get("conversation", {})
        perception = snapshot.get("perception", {})
        events = snapshot.get("events", {})
        autonomy = snapshot.get("autonomy", {})
        timestamps = snapshot.get("timestamps", {})

        self._restore_fields(
            lifecycle,
            ["mode", "running"],
        )

        self._restore_fields(
            cognition,
            [
                "attention",
                "focus",
                "cognitive_load",
                "uncertainty",
                "confidence",
            ],
        )

        self._restore_fields(
            activity,
            [
                "active_task",
                "current_goal",
                "pending_tasks",
            ],
        )

        self._restore_fields(
            learning,
            [
                "learning_state",
                "last_learning_result",
                "learning_count",
            ],
        )

        self._restore_fields(
            conversation,
            [
                "conversation_active",
                "last_user_input",
                "last_response",
            ],
        )

        self._restore_fields(
            perception,
            [
                "last_intent",
                "last_route",
                "last_perception",
            ],
        )

        self._restore_fields(
            events,
            [
                "last_event",
                "event_count",
            ],
        )

        self._restore_fields(
            autonomy,
            [
                "autonomy_enabled",
                "autonomy_state",
                "last_autonomous_action",
            ],
        )

        self._restore_fields(
            timestamps,
            [
                "created_at",
                "updated_at",
                "last_activity_at",
            ],
        )

        self.updated_at = time.time()

    # =============================================================
    # INTERNAL HELPERS
    # =============================================================

    def _restore_fields(
        self,
        source: Dict[str, Any],
        fields: List[str],
    ) -> None:

        for field in fields:
            if field in source and hasattr(self, field):
                setattr(self, field, source[field])

    @staticmethod
    def _clamp(value: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(1.0, value))