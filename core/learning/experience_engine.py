from __future__ import annotations

import time
from typing import Any, Dict, Optional


class ExperienceEngine:
    """
    Experience processing organ of JARVIS.

    Converts completed experiences into structured learning signals.

    Flow:

        Experience
            ↓
        Evaluation
            ↓
        Learning Signal
            ↓
        Memory / SelfEvaluator / EvolutionEngine

    This organ does NOT:
        - generate arbitrary knowledge
        - modify personality directly
        - modify system code
        - make unsafe autonomous changes
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        memory_manager=None,
        event_bus=None,
        internal_state=None,
    ):
        self.memory = memory_manager
        self.events = event_bus
        self.state = internal_state

        self.processed_count = 0
        self.success_count = 0
        self.failure_count = 0

        self.last_experience: Optional[Dict[str, Any]] = None
        self.last_learning_signal: Optional[Dict[str, Any]] = None
        self.last_processed_at: Optional[float] = None

    # =============================================================
    # PROCESS EXPERIENCE
    # =============================================================

    def process(
        self,
        event_type: str,
        context: Optional[Dict[str, Any]] = None,
        action: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        importance: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Process one completed experience.
        """

        context = context or {}
        action = action or {}
        outcome = outcome or {}

        success = self._determine_success(
            outcome
        )

        confidence = self._calculate_confidence(
            outcome=outcome,
            success=success,
        )

        learning_signal = self._build_learning_signal(
            event_type=event_type,
            context=context,
            action=action,
            outcome=outcome,
            success=success,
            confidence=confidence,
            importance=importance,
            source=source,
        )

        # ---------------------------------------------------------
        # Remember experience
        # ---------------------------------------------------------

        episode = None

        if self.memory is not None:

            episode = self.memory.remember_experience(
                event_type=event_type,
                context=context,
                action=action,
                outcome=outcome,
                importance=importance,
                confidence=confidence,
                source=source,
                tags=learning_signal["tags"],
            )

        # ---------------------------------------------------------
        # Runtime counters
        # ---------------------------------------------------------

        self.processed_count += 1

        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        self.last_experience = {
            "event_type": event_type,
            "context": context,
            "action": action,
            "outcome": outcome,
            "success": success,
        }

        self.last_learning_signal = learning_signal
        self.last_processed_at = time.time()

        # ---------------------------------------------------------
        # Update InternalState
        # ---------------------------------------------------------

        self._update_state(
            learning_signal
        )

        # ---------------------------------------------------------
        # Event
        # ---------------------------------------------------------

        self._emit(
            "EXPERIENCE_PROCESSED",
            {
                "event_type": event_type,
                "success": success,
                "confidence": confidence,
                "episode_id": (
                    episode.episode_id
                    if episode is not None
                    else None
                ),
            },
        )

        return {
            "experience": self.last_experience,
            "learning_signal": learning_signal,
            "episode_id": (
                episode.episode_id
                if episode is not None
                else None
            ),
        }

    # =============================================================
    # SUCCESS DETECTION
    # =============================================================

    @staticmethod
    def _determine_success(
        outcome: Dict[str, Any],
    ) -> bool:
        """
        Determine whether an experience succeeded.

        Explicit outcome fields take priority.
        """

        if not outcome:
            return True

        if "success" in outcome:
            return bool(
                outcome["success"]
            )

        status = outcome.get(
            "status"
        )

        if isinstance(
            status,
            str,
        ):

            status = status.upper()

            if status in (
                "FAILED",
                "FAILURE",
                "ERROR",
            ):
                return False

            if status in (
                "SUCCESS",
                "COMPLETED",
                "DONE",
            ):
                return True

        return True

    # =============================================================
    # CONFIDENCE
    # =============================================================

    @staticmethod
    def _calculate_confidence(
        outcome: Dict[str, Any],
        success: bool,
    ) -> float:
        """
        Calculate confidence in the experience evaluation.
        """

        explicit = outcome.get(
            "confidence"
        )

        if explicit is not None:

            try:
                return max(
                    0.0,
                    min(
                        1.0,
                        float(explicit),
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        # Explicit success/failure is stronger
        # than an unknown outcome.
        return 0.85 if success else 0.80

    # =============================================================
    # LEARNING SIGNAL
    # =============================================================

    def _build_learning_signal(
        self,
        event_type: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: Dict[str, Any],
        success: bool,
        confidence: float,
        importance: float,
        source: Optional[str],
    ) -> Dict[str, Any]:
        """
        Build structured learning information.

        This signal can later be consumed by:
            SelfEvaluator
            EvolutionEngine
            KnowledgeBuilder
        """

        tags = [
            "experience",
            event_type.lower(),
        ]

        if success:
            tags.append("success")
        else:
            tags.append("failure")

        if importance >= 0.7:
            tags.append("important")

        return {
            "type": "LEARNING_SIGNAL",

            "event_type": event_type,

            "success": success,

            "confidence": confidence,

            "importance": max(
                0.0,
                min(
                    1.0,
                    float(importance),
                ),
            ),

            "source": source,

            "context": context,

            "action": action,

            "outcome": outcome,

            "tags": tags,

            "timestamp": time.time(),
        }

    # =============================================================
    # STATE UPDATE
    # =============================================================

    def _update_state(
        self,
        learning_signal: Dict[str, Any],
    ) -> None:

        if self.state is None:
            return

        try:

            begin_learning = getattr(
                self.state,
                "begin_learning",
                None,
            )

            if callable(begin_learning):
                begin_learning()

            record_learning = getattr(
                self.state,
                "record_learning",
                None,
            )

            if callable(record_learning):

                record_learning(
                    learning_signal
                )

            finish_learning = getattr(
                self.state,
                "finish_learning",
                None,
            )

            if callable(finish_learning):
                finish_learning()

        except Exception as exc:

            print(
                f"[ExperienceEngine State Error] "
                f"{exc}"
            )

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:

        success_rate = 0.0

        if self.processed_count > 0:

            success_rate = (
                self.success_count
                / self.processed_count
            )

        return {
            "version": self.VERSION,
            "processed": self.processed_count,
            "successes": self.success_count,
            "failures": self.failure_count,
            "success_rate": success_rate,
            "last_processed_at": (
                self.last_processed_at
            ),
        }

    # =============================================================
    # RESET
    # =============================================================

    def reset_statistics(self) -> None:

        self.processed_count = 0
        self.success_count = 0
        self.failure_count = 0

        self.last_experience = None
        self.last_learning_signal = None
        self.last_processed_at = None

    # =============================================================
    # EVENT BUS
    # =============================================================

    def _emit(
        self,
        event_name: str,
        payload: Any = None,
    ) -> None:

        if self.events is None:
            return

        safe_emit = getattr(
            self.events,
            "safe_emit",
            None,
        )

        if callable(safe_emit):

            safe_emit(
                event_name,
                payload,
                source="experience_engine",
            )