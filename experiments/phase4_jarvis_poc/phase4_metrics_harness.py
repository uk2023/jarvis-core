import json
import sys
import time
from pathlib import Path
from statistics import mean, pvariance

ROOT = Path(__file__).resolve().parent.parent.parent
POC = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = POC / "phase4_metrics_result.json"

sys.path.insert(0, str(POC))

from neural_state_adapter import NeuralStateAdapter


CASES = [
    ("idle", 0.0),
    ("simple_query", 0.2),
    ("complex_query", 0.5),
    ("high_load", 1.0),
]


def run_case(name, signal, repeats=20):
    latencies = []
    activities = []

    for _ in range(repeats):
        adapter = NeuralStateAdapter()

        start = time.perf_counter()
        result = adapter.process(signal)
        elapsed = time.perf_counter() - start

        latencies.append(elapsed)
        activities.append(result["mean_activity"])

    return {
        "case": name,
        "input_signal": signal,
        "repeats": repeats,
        "latency_mean_ms": mean(latencies) * 1000,
        "latency_min_ms": min(latencies) * 1000,
        "latency_max_ms": max(latencies) * 1000,
        "latency_variance": pvariance(latencies),
        "activity_mean": mean(activities),
        "activity_variance": pvariance(activities),
        "deterministic": len(set(activities)) == 1,
    }


def main():
    results = [
        run_case(name, signal)
        for name, signal in CASES
    ]

    result = {
        "experiment": "phase4_jarvis_metrics_harness",
        "model": "experimental_computational_model",
        "brain_authority": "existing_jarvis_brain",
        "neural_role": "state_feedback_only",
        "results": results,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 4 METRICS HARNESS")
    print("Brain authority: existing Jarvis brain")
    print()

    for item in results:
        print(
            f"{item['case']:<14} "
            f"latency={item['latency_mean_ms']:.4f}ms "
            f"activity={item['activity_mean']:.8f} "
            f"variance={item['activity_variance']:.3e} "
            f"deterministic={item['deterministic']}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    main()
