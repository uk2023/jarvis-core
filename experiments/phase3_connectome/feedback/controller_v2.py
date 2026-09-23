from dataclasses import dataclass


@dataclass(frozen=True)
class FeedbackConfigV2:
    target_activity: float = 0.20
    correction_gain: float = 0.50
    max_scale: float = 1.0
    min_scale: float = 0.0


class AdaptiveFeedbackController:
    """
    Experimental computational feedback controller.

    Instead of injecting an additive correction, this controller
    computes a bounded input scale from the measured activity error.
    """

    def __init__(self, config=None):
        self.config = config or FeedbackConfigV2()

    def measure(self, states):
        if not states:
            return 0.0

        return sum(abs(float(v)) for v in states.values()) / len(states)

    def control(self, states):
        activity = self.measure(states)

        error = self.config.target_activity - activity

        scale = 1.0 + (
            self.config.correction_gain * error
        )

        scale = max(
            self.config.min_scale,
            min(self.config.max_scale, scale),
        )

        return {
            "activity": activity,
            "error": error,
            "input_scale": scale,
        }
