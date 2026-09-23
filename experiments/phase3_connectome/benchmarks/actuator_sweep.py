import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "actuator_sweep_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_actuator_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase3_actuator_operator",
)


INPUTS = [
    0.0,
    0.01,
    0.05,
    0.10,
    0.20,
    0.40,
    0.60,
    0.80,
    1.00,
]


def measure(state):
    values = [abs(float(v)) for v in state.values()]

    return {
        "mean_activity": sum(values) / len(values),
        "total_activity": sum(values),
        "max_activity": max(values),
        "active_nodes": sum(
            1 for value in values if value > 0.0
        ),
    }


def run(input_value, steps=30):
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

    for step_index in range(steps):
        metrics = measure(state)

        history.append({
            "step": step_index,
            **metrics,
        })

        propagated = operator.step(state)

        # Fixed external actuator.
        propagated[seed] += input_value

        state = {
            node_id: max(
                -1.0,
                min(1.0, float(value)),
            )
            for node_id, value in propagated.items()
        }

    return {
        "input": input_value,
        "initial_activity": history[0]["mean_activity"],
        "peak_activity": max(
            x["mean_activity"] for x in history
        ),
        "final_activity": history[-1]["mean_activity"],
        "final_total_activity": history[-1]["total_activity"],
        "final_max_activity": history[-1]["max_activity"],
        "final_active_nodes": history[-1]["active_nodes"],
        "history": history,
    }


def main():
    results = [
        run(value)
        for value in INPUTS
    ]

    result = {
        "experiment": "phase3_connectome_actuator_sweep",
        "model": "experimental_computational_model",
        "nodes": 32,
        "edges": 364,
        "steps": 30,
        "seed": "0",
        "inputs": INPUTS,
        "results": results,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("PHASE 3 ACTUATOR SWEEP")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])
    print()

    for item in results:
        print(
            f"input={item['input']:<5g} "
            f"initial={item['initial_activity']:.8f} "
            f"peak={item['peak_activity']:.8f} "
            f"final={item['final_activity']:.8f} "
            f"total={item['final_total_activity']:.8f} "
            f"max={item['final_max_activity']:.8f} "
            f"active={item['final_active_nodes']}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    main()
