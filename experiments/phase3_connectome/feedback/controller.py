from dataclasses import dataclass


@dataclass(frozen=True)
class FeedbackConfig:
    target_activity: float = 0.20
    correction_gain: float = 0.25
    max_correction: float = 0.25


class FeedbackController:
    """
    Experimental closed-loop controller.

    Measures circuit activity and applies a bounded correction.
    This is a computational experiment, not a biological claim.
    """

    def __init__(self, config=None):
        self.config = config or FeedbackConfig()

    def measure(self, states):
        if not states:
            return 0.0

        return sum(abs(v) for v in states.values()) / len(states)

    def correction(self, states):
        activity = self.measure(states)

        error = self.config.target_activity - activity

        correction = error * self.config.correction_gain

        correction = max(
            -self.config.max_correction,
            min(self.config.max_correction, correction),
        )

        return {
            "activity": activity,
            "error": error,
            "correction": correction,
        }
