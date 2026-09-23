import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "open_vs_closed_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dynamics = load_module(
    SIMULATOR / "dynamics.py",
    "phase3_compare_dynamics",
)

adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_compare_adapter",
)

feedback = load_module(
    ROOT / "feedback" / "controller.py",
    "phase3_compare_feedback",
)


CONFIG = dynamics.DynamicsConfig(
    gain=0.000001,
    decay=0.25,
    threshold=0.01,
    max_state=1.0,
)


def run_open_loop(steps=12):
    circuit = adapter.load_connectome_circuit(GRAPH)
    model = dynamics.ControlledNeuralCircuit(circuit, CONFIG)

    history = []
    inputs = {"0": 1.0}

    for step in range(steps):
        states = model.step(inputs)

        history.append({
            "step": step,
            "mean_activity": mean(abs(v) for v in states.values()),
            "active_nodes": sum(
                abs(v) >= CONFIG.threshold
                for v in states.values()
            ),
        })

        inputs = {}

    return history


def run_closed_loop(steps=12):
    circuit = adapter.load_connectome_circuit(GRAPH)
    model = dynamics.ControlledNeuralCircuit(circuit, CONFIG)

    controller = feedback.FeedbackController(
        feedback.FeedbackConfig(
            target_activity=0.20,
            correction_gain=0.25,
            max_correction=0.25,
        )
    )

    history = []
    inputs = {"0": 1.0}

    for step in range(steps):
        states = model.step(inputs)

        fb = controller.correction(states)

        history.append({
            "step": step,
            "mean_activity": fb["activity"],
            "active_nodes": sum(
                abs(v) >= CONFIG.threshold
                for v in states.values()
            ),
            "correction": fb["correction"],
        })

        inputs = {"0": fb["correction"]}

    return history


def summarize(history):
    activities = [
        x["mean_activity"]
        for x in history
    ]

    return {
        "initial_activity": activities[0],
        "peak_activity": max(activities),
        "final_activity": activities[-1],
        "mean_activity": mean(activities),
        "activity_variance": pvariance(activities),
        "activity_range": max(activities) - min(activities),
        "final_active_nodes": history[-1]["active_nodes"],
    }


def main():
    open_loop = run_open_loop()
    closed_loop = run_closed_loop()

    result = {
        "experiment": "phase3_open_vs_closed_loop",
        "model": "experimental_computational_model",
        "nodes": 32,
        "edges": 364,
        "steps": 12,
        "open_loop": {
            "metrics": summarize(open_loop),
            "history": open_loop,
        },
        "closed_loop": {
            "metrics": summarize(closed_loop),
            "history": closed_loop,
        },
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Open vs closed-loop comparison complete")
    print("Result:", OUT)

    for name in ("open_loop", "closed_loop"):
        print(f"\n{name.upper()}")
        for key, value in result[name]["metrics"].items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
