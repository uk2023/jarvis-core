import json
import sys
from pathlib import Path
from statistics import mean, pvariance

ROOT = Path(__file__).resolve().parents[2]
POC = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = POC / "ab_harness_result.json"

sys.path.insert(0, str(POC))

from neural_state_adapter import NeuralStateAdapter


CASES = [
    {"name": "idle", "signal": 0.0},
    {"name": "simple_query", "signal": 0.2},
    {"name": "complex_query", "signal": 0.5},
    {"name": "high_load", "signal": 1.0},
]


def current_jarvis_case(case):
    # Baseline placeholder.
    # Phase 4 does not alter the existing Jarvis brain.
    return {
        "workflow_signal": case["signal"],
        "neural_activity": None,
        "neural_active_nodes": None,
    }


def neural_jarvis_case(adapter, case):
    adapter.reset()
    neural = adapter.process(case["signal"])

    return {
        "workflow_signal": case["signal"],
        "neural_activity": neural["mean_activity"],
        "neural_max_activity": neural["max_activity"],
        "neural_active_nodes": neural["active_nodes"],
    }


def run():
    adapter = NeuralStateAdapter()

    baseline = []
    neural = []

    for case in CASES:
        baseline.append({
            "case": case["name"],
            **current_jarvis_case(case),
        })

        neural.append({
            "case": case["name"],
            **neural_jarvis_case(adapter, case),
        })

    activities = [
        item["neural_activity"]
        for item in neural
        if item["neural_activity"] is not None
    ]

    result = {
        "experiment": "phase4_jarvis_ab_harness",
        "model": "experimental_computational_model",
        "brain_authority": "existing_jarvis_brain",
        "neural_role": "experimental_state_feedback_only",
        "autonomous_action": False,
        "cases": CASES,
        "A_current_jarvis": baseline,
        "B_jarvis_plus_neural_layer": neural,
        "neural_summary": {
            "mean_activity": mean(activities),
            "activity_variance": pvariance(activities),
            "min_activity": min(activities),
            "max_activity": max(activities),
        },
        "comparison_status": "baseline_and_neural_paths_recorded",
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 4 A/B HARNESS")
    print("A = Current Jarvis")
    print("B = Jarvis + experimental neural layer")
    print()

    for a, b in zip(baseline, neural):
        print(
            f"{a['case']:14s} "
            f"A_signal={a['workflow_signal']:.2f} "
            f"B_activity={b['neural_activity']:.8f} "
            f"B_active={b['neural_active_nodes']}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    run()
