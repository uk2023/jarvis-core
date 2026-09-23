import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POC = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = POC / "workflow_poc_result.json"

sys.path.insert(0, str(POC))

from neural_state_adapter import NeuralStateAdapter


def run():
    adapter = NeuralStateAdapter()

    # Simulated Jarvis workflow signals.
    # Phase 4 does NOT replace Jarvis reasoning/LLM.
    cases = [
        {"name": "idle", "signal": 0.0},
        {"name": "simple_query", "signal": 0.2},
        {"name": "complex_query", "signal": 0.5},
        {"name": "high_load", "signal": 1.0},
    ]

    results = []

    for case in cases:
        adapter.reset()
        neural = adapter.process(case["signal"])

        results.append({
            "case": case["name"],
            "workflow_signal": case["signal"],
            "neural": neural,
        })

    result = {
        "experiment": "phase4_jarvis_workflow_poc",
        "model": "experimental_computational_model",
        "brain_authority": "existing_jarvis_brain",
        "neural_role": "experimental_state_feedback_only",
        "autonomous_action": False,
        "results": results,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 4 JARVIS WORKFLOW POC")
    print("Brain authority: existing Jarvis brain")
    print("Neural role: state/feedback only")
    print()

    for item in results:
        n = item["neural"]
        print(
            f"{item['case']:14s} "
            f"input={item['workflow_signal']:.2f} "
            f"mean={n['mean_activity']:.8f} "
            f"max={n['max_activity']:.8f} "
            f"active={n['active_nodes']}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    run()
