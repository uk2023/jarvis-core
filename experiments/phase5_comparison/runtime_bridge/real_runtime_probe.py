import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = ROOT / "experiments" / "phase5_comparison" / "runtime_bridge" / "real_runtime_probe_result.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PHASE4))

from neural_state_adapter import NeuralStateAdapter


CASES = [
    ("simple_query", "Hello Jarvis"),
    ("context_query", "What did we just discuss?"),
    ("complex_query", "Analyze this task and explain the required steps."),
]


def call_real_jarvis(text):
    """
    Probe the existing Jarvis runtime without changing its authority.

    This deliberately uses the public CLI runtime entrypoint when
    available. No neural decision is injected into the Brain.
    """
    import cli

    start = time.perf_counter()

    result = cli.process_query(
        text,
        source="phase5_runtime_probe",
    )

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "response": str(result),
        "latency_ms": elapsed,
    }


def main():
    neural = NeuralStateAdapter()
    results = []

    for case_id, prompt in CASES:
        print(f"\n[{case_id}] {prompt}")

        # A: untouched real Jarvis.
        a = call_real_jarvis(prompt)

        # B: same real Jarvis path, with neural state observed
        # externally. Neural output is NOT fed back into Brain.
        start = time.perf_counter()
        n = neural.process(
            0.2 if case_id == "simple_query"
            else 0.5 if case_id == "context_query"
            else 1.0
        )
        neural_overhead_ms = (time.perf_counter() - start) * 1000

        results.append({
            "id": case_id,
            "prompt": prompt,
            "A_current_jarvis": a,
            "B_neural_observation": {
                "neural_activity": n["mean_activity"],
                "neural_max_activity": n["max_activity"],
                "active_nodes": n["active_nodes"],
                "neural_overhead_ms": neural_overhead_ms,
            },
        })

        print(
            f"A latency={a['latency_ms']:.3f}ms "
            f"neural={n['mean_activity']:.8f} "
            f"overhead={neural_overhead_ms:.3f}ms"
        )

    OUT.write_text(
        json.dumps(
            {
                "experiment": "phase5_real_runtime_probe",
                "brain_authority": "existing_jarvis_brain",
                "neural_role": "observation_only",
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nRESULT:", OUT)


if __name__ == "__main__":
    main()
