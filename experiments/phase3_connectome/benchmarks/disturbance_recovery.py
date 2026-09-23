import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "disturbance_recovery_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_disturbance_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase3_disturbance_operator",
)


def measure(state):
    values = [abs(float(v)) for v in state.values()]
    return {
        "mean_activity": sum(values) / len(values),
        "total_activity": sum(values),
        "max_activity": max(values),
        "active_nodes": sum(1 for v in values if v > 0.0),
    }


def run(steps=500, disturbance_step=250, disturbance=0.05):
    circuit = adapter.load_connectome_circuit(GRAPH)
    operator = operator_module.NormalizedConnectomeOperator(circuit)

    seed = "0"
    target = 0.02

    state = {
        node_id: 0.0
        for node_id in circuit.nodes
    }
    state[seed] = 1.0

    history = []

    for step in range(steps):
        metrics = measure(state)

        error = target - metrics["mean_activity"]

        # Same bounded actuator operating region established by V6/V7.
        seed_input = max(
            0.012,
            min(
                0.0178,
                0.0149 + error,
            ),
        )

        if step == disturbance_step:
            seed_input += disturbance

        propagated = operator.step(state)
        propagated[seed] += seed_input

        state = {
            node_id: max(
                -1.0,
                min(1.0, float(value)),
            )
            for node_id, value in propagated.items()
        }

        history.append({
            "step": step,
            **metrics,
            "error": error,
            "seed_input": seed_input,
            "disturbance": disturbance if step == disturbance_step else 0.0,
        })

    baseline = history[disturbance_step - 1]["mean_activity"]
    post = history[disturbance_step]["mean_activity"]

    recovery_window = history[disturbance_step + 1:]

    recovery_step = None
    for item in recovery_window:
        if abs(item["mean_activity"] - target) <= 0.0005:
            recovery_step = item["step"]
            break

    tail = history[-50:]
    tail_activities = [x["mean_activity"] for x in tail]

    result = {
        "experiment": "phase3_connectome_disturbance_recovery",
        "model": "experimental_computational_model",
        "controller": "bounded_seed_actuator_v7_operating_region",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "steps": steps,
        "target_activity": target,
        "disturbance_step": disturbance_step,
        "disturbance": disturbance,
        "metrics": {
            "baseline_activity": baseline,
            "post_disturbance_activity": post,
            "disturbance_delta": post - baseline,
            "recovery_step": recovery_step,
            "recovery_steps": (
                None
                if recovery_step is None
                else recovery_step - disturbance_step
            ),
            "final_activity": history[-1]["mean_activity"],
            "final_target_error": abs(
                history[-1]["mean_activity"] - target
            ),
            "tail_mean_activity": mean(tail_activities),
            "tail_mean_abs_error": mean(
                abs(x - target)
                for x in tail_activities
            ),
            "tail_range": max(tail_activities) - min(tail_activities),
            "tail_variance": pvariance(tail_activities),
            "final_active_nodes": history[-1]["active_nodes"],
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

    print("PHASE 3 DISTURBANCE / RECOVERY BENCHMARK")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])
    print("Target:", result["target_activity"])

    print("\nMETRICS")
    for key, value in result["metrics"].items():
        print(f"{key}: {value}")

    print("\nResult:", OUT)
