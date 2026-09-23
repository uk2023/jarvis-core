import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "actuator_fine_sweep_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_fine_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase3_fine_operator",
)


INPUTS = [
    0.013,
    0.014,
    0.015,
    0.0155,
    0.016,
    0.0165,
    0.017,
    0.018,
]


def run_input(input_value, steps=100):
    circuit = adapter.load_connectome_circuit(GRAPH)

    operator = operator_module.NormalizedConnectomeOperator(
        circuit
    )

    seed = "0"

    state = {
        node_id: 0.0
        for node_id in circuit.nodes
    }

    state[seed] = 1.0

    history = []

    for step in range(steps):
        values = [
            abs(float(v))
            for v in state.values()
        ]

        activity = sum(values) / len(values)

        history.append({
            "step": step,
            "activity": activity,
        })

        propagated = operator.step(state)
        propagated[seed] += input_value

        state = {
            node_id: max(
                -1.0,
                min(1.0, float(value)),
            )
            for node_id, value in propagated.items()
        }

    activities = [
        item["activity"]
        for item in history
    ]

    tail = activities[-20:]

    return {
        "input": input_value,
        "initial_activity": activities[0],
        "peak_activity": max(activities),
        "final_activity": activities[-1],
        "tail_mean": sum(tail) / len(tail),
        "tail_min": min(tail),
        "tail_max": max(tail),
        "tail_range": max(tail) - min(tail),
        "target_error": abs(
            (sum(tail) / len(tail)) - 0.02
        ),
    }


def main():
    circuit = adapter.load_connectome_circuit(GRAPH)

    results = [
        run_input(value)
        for value in INPUTS
    ]

    result = {
        "experiment": "phase3_connectome_actuator_fine_sweep",
        "model": "experimental_computational_model",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "target_activity": 0.02,
        "steps": 100,
        "results": results,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 3 ACTUATOR FINE SWEEP")
    print(
        "Nodes:", result["nodes"],
        "Edges:", result["edges"],
        "Steps:", result["steps"],
    )
    print()

    for item in results:
        print(
            f"input={item['input']:<5.3f} "
            f"final={item['final_activity']:.9f} "
            f"tail_mean={item['tail_mean']:.9f} "
            f"tail_range={item['tail_range']:.9f} "
            f"error={item['target_error']:.9f}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    main()
