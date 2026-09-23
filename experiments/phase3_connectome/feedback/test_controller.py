import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "feedback" / "controller.py"

spec = importlib.util.spec_from_file_location(
    "phase3_feedback_controller",
    PATH,
)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FeedbackController = module.FeedbackController
FeedbackConfig = module.FeedbackConfig


def test_activity_measurement():
    controller = FeedbackController()

    result = controller.measure({
        "A": 0.2,
        "B": 0.4,
        "C": 0.0,
    })

    assert abs(result - 0.2) < 1e-12


def test_correction_is_bounded():
    controller = FeedbackController(
        FeedbackConfig(
            target_activity=0.2,
            correction_gain=10.0,
            max_correction=0.25,
        )
    )

    result = controller.correction({
        "A": 10.0,
        "B": 10.0,
    })

    assert abs(result["correction"]) <= 0.25


def test_zero_state_requests_positive_correction():
    controller = FeedbackController()

    result = controller.correction({
        "A": 0.0,
        "B": 0.0,
    })

    assert result["correction"] > 0.0
