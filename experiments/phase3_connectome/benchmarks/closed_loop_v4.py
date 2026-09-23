import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "closed_loop_v4_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_v4_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase3_v4_operator",
)


def measure(state):
    values = [
        abs(float(v))
        for v in state.values()
    ]

    return {
        "mean_activity": sum(values) / len(values),
        "total_activity": sum(values),
        "max_activity": max(values),
        "active_nodes": sum(
            1 for value in values
            if value > 0.0
        ),
    }


def normalize_l1(state, target_total=1.0):
    total = sum(
        abs(float(v))
        for v in state.values()
    )

    if total == 0.0:
        return dict(state)

    scale = target_total / total

    return {
        node_id: float(value) * scale
        for node_id, value in state.items()
    }


def run(steps=30):
    circuit = adapter.load_connectome_circuit(GRAPH)

    operator = operator_module.NormalizedConnectomeOperator(
        circuit
    )

    seed = "0"

    # Diagnostic target.
    target_activity = 0.02

    # Smaller controller gain so the diagnostic
    # does not immediately saturate.
    gain = 0.50

    min_input = 0.0
    max_input = 0.25

    state = {
        node_id: 0.0
        for node_id in circuit.nodes
    }

    state[seed] = 1.0

    history = []

    for step in range(steps):
        metrics = measure(state)

        error = (
            target_activity
            - metrics["mean_activity"]
        )

        correction = gain * error

        seed_input = max(
            min_input,
            min(
                max_input,
                correction,
            ),
        )

        history.append({
            "step": step,
            **metrics,
            "target_activity": target_activity,
            "error": error,
            "seed_input": seed_input,
        })

        propagated = operator.step(state)

        # Inject only the controller correction.
        propagated[seed] += seed_input

        # Normalize the resulting state so the
        # controller operates on a bounded L1 state.
        state = normalize_l1(
            propagated,
            target_total=1.0,
        )

    activities = [
        item["mean_activity"]
        for item in history
    ]

    errors = [
        abs(item["error"])
        for item in history
    ]

    result = {
        "experiment": "phase3_connectome_closed_loop_v4",
        "model": "experimental_computational_model",
        "controller": "bounded_correction_with_l1_normalization",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "steps": steps,
        "target_activity": target_activity,
        "metrics": {
            "initial_activity": activities[0],
            "peak_activity": max(activities),
            "final_activity": activities[-1],
            "mean_activity": mean(activities),
            "activity_variance": pvariance(activities),
            "activity_range": (
                max(activities)
                - min(activities)
            ),
            "initial_target_error": errors[0],
            "final_target_error": errors[-1],
            "minimum_target_error": min(errors),
            "final_active_nodes": history[-1]["active_nodes"],
            "max_seed_input": max(
                item["seed_input"]
                for item in history
            ),
            "min_seed_input": min(
                item["seed_input"]
                for item in history
            ),
        },
        "history": history,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return result


if __name__ == "__main__":
    result = run()

    print("Phase 3 closed-loop v4 benchmark complete")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])
    print("Target activity:", result["target_activity"])

    print("\nMETRICS")
    for key, value in result["metrics"].items():
        print(f"{key}: {value}")

    print("\nResult:", OUT)
