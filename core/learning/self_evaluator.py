from __future__ import annotations

import time
from typing import Any, Dict, Optional


class SelfEvaluator:
    """
    Self-evaluation organ of JARVIS.

    Responsibilities:
        - evaluate completed experiences
        - measure outcome quality
        - detect obvious mistakes
        - produce feedback for learning
        - track performance over time

    It does NOT:
        - directly modify system code
        - modify personality
        - invent knowledge
        - autonomously execute actions
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        memory_manager=None,
        event_bus=None,
        internal_state=None,
    ):
        self.memory_manager = memory_manager
        self.events = event_bus
        self.state = internal_state

        self.evaluation_count = 0
        self.success_count = 0
        self.failure_count = 0

        self.total_score = 0.0

        self.last_evaluation: Optional[
            Dict[str, Any]
        ] = None

        self.last_evaluated_at: Optional[
            float
        ] = None

    # =============================================================
    # EVALUATE
    # =============================================================

    def evaluate(
        self,
        experience: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Evaluate one experience.

        Expected structure:

            {
                "event_type": "...",
                "context": {...},
                "action": {...},
                "outcome": {...},
                "success": True
            }
        """

        if not isinstance(
            experience,
            dict,
        ):
            raise TypeError(
                "experience must be a dictionary"
            )

        outcome = experience.get(
            "outcome"
        ) or {}

        action = experience.get(
            "action"
        ) or {}

        success = self._determine_success(
            experience,
            outcome,
        )

        score = self._calculate_score(
            success=success,
            outcome=outcome,
        )

        errors = self._detect_errors(
            success=success,
            outcome=outcome,
        )

        strengths = self._detect_strengths(
            success=success,
            outcome=outcome,
            action=action,
        )

        feedback = self._build_feedback(
            score=score,
            success=success,
            errors=errors,
            strengths=strengths,
        )

        evaluation = {
            "type": "SELF_EVALUATION",

            "event_type": experience.get(
                "event_type"
            ),

            "success": success,

            "score": score,

            "errors": errors,

            "strengths": strengths,

            "feedback": feedback,

            "timestamp": time.time(),
        }

        self.evaluation_count += 1

        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        self.total_score += score

        self.last_evaluation = evaluation
        self.last_evaluated_at = time.time()

        self._emit(
            "SELF_EVALUATION_COMPLETED",
            evaluation,
        )

        return evaluation

    # =============================================================
    # SUCCESS
    # =============================================================

    @staticmethod
    def _determine_success(
        experience: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> bool:

        if "success" in experience:

            return bool(
                experience["success"]
            )

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
    # SCORE
    # =============================================================

    @staticmethod
    def _calculate_score(
        success: bool,
        outcome: Dict[str, Any],
    ) -> float:
        """
        Produce a normalized quality score [0, 1].

        Explicit score takes priority.
        """

        explicit_score = outcome.get(
            "score"
        )

        if explicit_score is not None:

            try:

                return max(
                    0.0,
                    min(
                        1.0,
                        float(
                            explicit_score
                        ),
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        if success:
            return 1.0

        return 0.0

    # =============================================================
    # ERROR DETECTION
    # =============================================================

    @staticmethod
    def _detect_errors(
        success: bool,
        outcome: Dict[str, Any],
    ) -> list:

        errors = []

        if not success:

            errors.append(
                "OUTCOME_FAILURE"
            )

        explicit_error = outcome.get(
            "error"
        )

        if explicit_error:

            errors.append(
                str(explicit_error)
            )

        errors_list = outcome.get(
            "errors"
        )

        if isinstance(
            errors_list,
            list,
        ):

            errors.extend(
                str(item)
                for item in errors_list
            )

        return errors

    # =============================================================
    # STRENGTH DETECTION
    # =============================================================

    @staticmethod
    def _detect_strengths(
        success: bool,
        outcome: Dict[str, Any],
        action: Dict[str, Any],
    ) -> list:

        strengths = []

        if success:

            strengths.append(
                "SUCCESSFUL_OUTCOME"
            )

        if action:

            strengths.append(
                "ACTION_WAS_EXECUTED"
            )

        explicit_strengths = outcome.get(
            "strengths"
        )

        if isinstance(
            explicit_strengths,
            list,
        ):

            strengths.extend(
                str(item)
                for item in explicit_strengths
            )

        return strengths

    # =============================================================
    # FEEDBACK
    # =============================================================

    @staticmethod
    def _build_feedback(
        score: float,
        success: bool,
        errors: list,
        strengths: list,
    ) -> Dict[str, Any]:

        if score >= 0.8:

            quality = "GOOD"

        elif score >= 0.5:

            quality = "ACCEPTABLE"

        else:

            quality = "POOR"

        return {
            "quality": quality,
            "score": score,
            "success": success,
            "errors": errors,
            "strengths": strengths,
        }

    # =============================================================
    # COMPARISON
    # =============================================================

    def compare(
        self,
        current: Dict[str, Any],
        previous: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compare two evaluations.
        """

        current_score = float(
            current.get(
                "score",
                0.0,
            )
        )

        previous_score = float(
            previous.get(
                "score",
                0.0,
            )
        )

        delta = (
            current_score
            - previous_score
        )

        if delta > 0:
            trend = "IMPROVING"

        elif delta < 0:
            trend = "DEGRADING"

        else:
            trend = "STABLE"

        return {
            "current_score": current_score,
            "previous_score": previous_score,
            "delta": delta,
            "trend": trend,
        }

    # =============================================================
    # STATISTICS
    # =============================================================

    def statistics(self) -> Dict[str, Any]:

        average_score = 0.0

        if self.evaluation_count:

            average_score = (
                self.total_score
                / self.evaluation_count
            )

        success_rate = 0.0

        if self.evaluation_count:

            success_rate = (
                self.success_count
                / self.evaluation_count
            )

        return {
            "version": self.VERSION,
            "evaluations": self.evaluation_count,
            "successes": self.success_count,
            "failures": self.failure_count,
            "success_rate": success_rate,
            "average_score": average_score,
            "last_evaluated_at": (
                self.last_evaluated_at
            ),
        }

    # =============================================================
    # RESET
    # =============================================================

    def reset_statistics(self) -> None:

        self.evaluation_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_score = 0.0

        self.last_evaluation = None
        self.last_evaluated_at = None

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
                source="self_evaluator",
            )
