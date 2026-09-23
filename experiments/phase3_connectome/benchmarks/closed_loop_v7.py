import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance

ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "closed_loop_v7_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_v7_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase3_v7_operator",
)


def measure(state):
    values = [abs(float(v)) for v in state.values()]
    return {
        "mean_activity": sum(values) / len(values),
        "total_activity": sum(values),
        "max_activity": max(values),
        "active_nodes": sum(v > 0.0 for v in values),
    }


def run(steps=500):
    circuit = adapter.load_connectome_circuit(GRAPH)
    operator = operator_module.NormalizedConnectomeOperator(circuit)

    seed = "0"

    target = 0.0200
    deadband = 0.0005

    input_value = 0.0155

    min_input = 0.012
    max_input = 0.019

    max_step_change = 0.00025
    correction_gain = 0.05

    state = {node_id: 0.0 for node_id in circuit.nodes}
    state[seed] = 1.0

    history = []

    for step in range(steps):
        metrics = measure(state)
        activity = metrics["mean_activity"]
        error = target - activity

        previous_input = input_value

        if error > deadband:
            desired = input_value + correction_gain * error
        elif error < -deadband:
            desired = input_value + correction_gain * error
        else:
            desired = input_value

        delta = desired - input_value

        delta = max(
            -max_step_change,
            min(max_step_change, delta),
        )

        input_value += delta

        input_value = max(
            min_input,
            min(max_input, input_value),
        )

        history.append({
            "step": step,
            **metrics,
            "target_activity": target,
            "error": error,
            "previous_input": previous_input,
            "seed_input": input_value,
            "input_delta": input_value - previous_input,
            "inside_deadband": abs(error) <= deadband,
        })

        propagated = operator.step(state)
        propagated[seed] += input_value

        state = {
            node_id: max(-1.0, min(1.0, float(value)))
            for node_id, value in propagated.items()
        }

    activities = [x["mean_activity"] for x in history]
    errors = [abs(x["error"]) for x in history]

    tail = history[-50:]
    tail_activities = [x["mean_activity"] for x in tail]
    tail_errors = [abs(x["error"]) for x in tail]

    settled = all(
        abs(x["error"]) <= deadband
        for x in tail
    )

    result = {
        "experiment": "phase3_connectome_closed_loop_v7",
        "model": "experimental_computational_model",
        "controller": "hysteresis_rate_limited_proportional",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "steps": steps,
        "target_activity": target,
        "deadband": deadband,
        "baseline_input": 0.0155,
        "input_bounds": {
            "min": min_input,
            "max": max_input,
        },
        "max_step_change": max_step_change,
        "correction_gain": correction_gain,
        "metrics": {
            "initial_activity": activities[0],
            "peak_activity": max(activities),
            "final_activity": activities[-1],
            "mean_activity": mean(activities),
            "activity_variance": pvariance(activities),
            "activity_range": max(activities) - min(activities),
            "initial_target_error": errors[0],
            "final_target_error": errors[-1],
            "minimum_target_error": min(errors),
            "tail_mean_activity": mean(tail_activities),
            "tail_target_error": abs(
                mean(tail_activities) - target
            ),
            "tail_range": max(tail_activities) - min(tail_activities),
            "tail_mean_abs_error": mean(tail_errors),
            "deadband_hits": sum(
                x["inside_deadband"] for x in history
            ),
            "deadband_fraction": (
                sum(x["inside_deadband"] for x in history)
                / len(history)
            ),
            "last_50_inside_deadband": settled,
            "final_active_nodes": history[-1]["active_nodes"],
            "max_seed_input": max(x["seed_input"] for x in history),
            "min_seed_input": min(x["seed_input"] for x in history),
            "max_abs_input_delta": max(
                abs(x["input_delta"]) for x in history
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

    print("Phase 3 closed-loop v7 benchmark complete")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])
    print("Target:", result["target_activity"])

    print("\nMETRICS")
    for key, value in result["metrics"].items():
        print(f"{key}: {value}")

    print("\nResult:", OUT)
