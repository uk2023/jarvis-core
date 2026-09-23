import json
import sys
import time
from pathlib import Path
from statistics import mean, pvariance

ROOT = Path(__file__).resolve().parent.parent.parent
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
CASES_FILE = ROOT / "experiments" / "phase5_comparison" / "test_cases.json"
OUT = ROOT / "experiments" / "phase5_comparison" / "ab_comparison_result.json"

sys.path.insert(0, str(PHASE4))

from neural_state_adapter import NeuralStateAdapter


def load_cases():
    return json.loads(CASES_FILE.read_text())["cases"]


def baseline_case(case):
    start = time.perf_counter()

    # A = existing Jarvis path.
    # No neural processing is performed.
    signal = float(case["workflow_signal"])

    elapsed = time.perf_counter() - start

    return {
        "latency_ms": elapsed * 1000,
        "signal": signal,
    }


def neural_case(adapter, case):
    start = time.perf_counter()

    result = adapter.process(
        float(case["workflow_signal"])
    )

    elapsed = time.perf_counter() - start

    return {
        "latency_ms": elapsed * 1000,
        "signal": float(case["workflow_signal"]),
        "neural_activity": result["mean_activity"],
        "neural_max_activity": result["max_activity"],
        "active_nodes": result["active_nodes"],
    }


def summarize(values):
    return {
        "mean_ms": mean(values),
        "min_ms": min(values),
        "max_ms": max(values),
        "variance": pvariance(values),
    }


def main(repeats=50):
    cases = load_cases()

    all_results = []

    for case in cases:
        a_latencies = []
        b_latencies = []
        activities = []

        for _ in range(repeats):
            a = baseline_case(case)

            adapter = NeuralStateAdapter()
            b = neural_case(adapter, case)

            a_latencies.append(a["latency_ms"])
            b_latencies.append(b["latency_ms"])
            activities.append(b["neural_activity"])

        a_summary = summarize(a_latencies)
        b_summary = summarize(b_latencies)

        overhead = (
            b_summary["mean_ms"] -
            a_summary["mean_ms"]
        )

        all_results.append({
            "id": case["id"],
            "name": case["name"],
            "workflow_signal": case["workflow_signal"],
            "repeats": repeats,
            "A_current_jarvis": a_summary,
            "B_jarvis_plus_neural": {
                **b_summary,
                "mean_neural_activity": mean(activities),
                "neural_activity_variance": pvariance(activities),
            },
            "neural_overhead_ms": overhead,
        })

    result = {
        "experiment": "phase5_current_vs_neural_ab",
        "model": "experimental_computational_model",
        "A": "current_jarvis",
        "B": "current_jarvis_plus_experimental_neural_layer",
        "repeats": repeats,
        "results": all_results,
        "interpretation": (
            "This benchmark measures computational overhead and "
            "neural-state behavior only. It does not claim "
            "end-to-end Jarvis improvement."
        ),
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 5 A/B COMPARISON")
    print("A = Current Jarvis")
    print("B = Current Jarvis + neural layer")
    print()

    for item in all_results:
        a = item["A_current_jarvis"]
        b = item["B_jarvis_plus_neural"]

        print(
            f"{item['name']:<16} "
            f"A={a['mean_ms']:.6f}ms "
            f"B={b['mean_ms']:.6f}ms "
            f"overhead={item['neural_overhead_ms']:+.6f}ms "
            f"activity={b['mean_neural_activity']:.8f}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    main()
