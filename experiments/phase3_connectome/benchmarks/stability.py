import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "stability_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_module(
    SIMULATOR / "core.py",
    "phase3_stability_core",
)

dynamics = load_module(
    SIMULATOR / "dynamics.py",
    "phase3_stability_dynamics",
)

adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_stability_adapter",
)

feedback = load_module(
    ROOT / "feedback" / "controller.py",
    "phase3_stability_feedback",
)


def run(steps=12):
    circuit = adapter.load_connectome_circuit(GRAPH)

    controlled = dynamics.ControlledNeuralCircuit(
        circuit,
        dynamics.DynamicsConfig(
            gain=0.000001,
            decay=0.25,
            threshold=0.01,
            max_state=1.0,
        ),
    )

    controller = feedback.FeedbackController()

    seed = "0"
    history = []

    inputs = {seed: 1.0}

    for step in range(steps):
        states = controlled.step(inputs)

        fb = controller.correction(states)

        history.append({
            "step": step,
            "mean_activity": fb["activity"],
            "feedback_error": fb["error"],
            "correction": fb["correction"],
            "active_nodes": sum(
                1
                for value in states.values()
                if abs(value) >= controlled.config.threshold
            ),
        })

        inputs = {}

    activities = [
        item["mean_activity"]
        for item in history
    ]

    result = {
        "experiment": "phase3_connectome_stability",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "steps": steps,
        "metrics": {
            "initial_activity": activities[0],
            "peak_activity": max(activities),
            "final_activity": activities[-1],
            "mean_activity": mean(activities),
            "activity_variance": pvariance(activities),
            "activity_range": max(activities) - min(activities),
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

    print("Phase 3 stability benchmark complete")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])
    print("Initial activity:", result["metrics"]["initial_activity"])
    print("Peak activity:", result["metrics"]["peak_activity"])
    print("Final activity:", result["metrics"]["final_activity"])
    print("Activity variance:", result["metrics"]["activity_variance"])
    print("Activity range:", result["metrics"]["activity_range"])
    print("Final active nodes:", result["metrics"]["final_active_nodes"])
    print("Result:", OUT)
