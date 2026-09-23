import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.phase3_connectome.simulator.connectome_adapter import (
    load_connectome_circuit,
)


GRAPH = ROOT / "experiments/phase3_connectome/connectome/selected_subgraph.json"
OUT = ROOT / "experiments/phase3_connectome/signals/propagation_result.json"


def run_propagation(steps: int = 6):
    data = json.loads(GRAPH.read_text(encoding="utf-8"))
    circuit = load_connectome_circuit(GRAPH)

    seed = str(data["selection"]["seed_node"])
    history = []
    inputs = {seed: 1.0}

    for step in range(steps):
        states = circuit.step(inputs)

        active = {
            node_id: value
            for node_id, value in states.items()
            if value != 0.0
        }

        history.append(
            {
                "step": step,
                "active_nodes": len(active),
                "total_activity": sum(abs(v) for v in states.values()),
                "max_activity": (
                    max(abs(v) for v in states.values())
                    if states
                    else 0.0
                ),
                "states": states,
            }
        )

        inputs = {}

    active_counts = [x["active_nodes"] for x in history]
    total_activity = [x["total_activity"] for x in history]

    result = {
        "experiment": "phase3_connectome_signal_propagation",
        "source_dataset": data["source_dataset"],
        "source_release": data["source_release"],
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "seed_node": seed,
        "steps": steps,
        "metrics": {
            "peak_active_nodes": max(active_counts),
            "peak_total_activity": max(total_activity),
            "final_active_nodes": active_counts[-1],
            "final_total_activity": total_activity[-1],
            "mean_active_nodes": mean(active_counts),
        },
        "history": history,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return result


def main():
    result = run_propagation()

    print("Signal propagation complete")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Seed:", result["seed_node"])
    print("Steps:", result["steps"])
    print("Peak active nodes:", result["metrics"]["peak_active_nodes"])
    print("Peak total activity:", result["metrics"]["peak_total_activity"])
    print("Final active nodes:", result["metrics"]["final_active_nodes"])
    print("Final total activity:", result["metrics"]["final_total_activity"])
    print("Mean active nodes:", result["metrics"]["mean_active_nodes"])
    print("Result:", OUT)


if __name__ == "__main__":
    main()
