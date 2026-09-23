import importlib.util
import json
from pathlib import Path
from statistics import mean, pvariance


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "open_vs_closed_v2_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dynamics = load_module(
    SIMULATOR / "dynamics.py",
    "phase3_v2_dynamics",
)

adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_v2_adapter",
)

feedback = load_module(
    ROOT / "feedback" / "controller_v2.py",
    "phase3_v2_feedback",
)


def make_circuit():
    circuit = adapter.load_connectome_circuit(GRAPH)

    return dynamics.ControlledNeuralCircuit(
        circuit,
        dynamics.DynamicsConfig(
            gain=0.000001,
            decay=0.25,
            threshold=0.01,
            max_state=1.0,
        ),
    )


def summarize(history):
    activities = [x["mean_activity"] for x in history]

    return {
        "initial_activity": activities[0],
        "peak_activity": max(activities),
        "final_activity": activities[-1],
        "mean_activity": mean(activities),
        "activity_variance": pvariance(activities),
        "activity_range": max(activities) - min(activities),
        "final_target_error": abs(activities[-1] - 0.20),
        "final_active_nodes": history[-1]["active_nodes"],
    }


def run(steps=12):
    seed = "0"

    # -------------------------
    # OPEN LOOP
    # -------------------------
    open_circuit = make_circuit()
    open_history = []

    inputs = {seed: 1.0}

    for step in range(steps):
        states = open_circuit.step(inputs)

        activity = sum(
            abs(float(v))
            for v in states.values()
        ) / len(states)

        open_history.append({
            "step": step,
            "mean_activity": activity,
            "active_nodes": sum(
                1
                for v in states.values()
                if abs(v) >= open_circuit.config.threshold
            ),
        })

        inputs = {}

    # -------------------------
    # CLOSED LOOP V2
    # -------------------------
    closed_circuit = make_circuit()

    controller = feedback.AdaptiveFeedbackController(
        feedback.FeedbackConfigV2(
            target_activity=0.20,
            correction_gain=0.50,
            max_scale=1.0,
            min_scale=0.0,
        )
    )

    closed_history = []

    inputs = {seed: 1.0}

    for step in range(steps):
        states = closed_circuit.step(inputs)

        fb = controller.control(states)

        closed_history.append({
            "step": step,
            "mean_activity": fb["activity"],
            "target_error": fb["error"],
            "input_scale": fb["input_scale"],
            "active_nodes": sum(
                1
                for v in states.values()
                if abs(v) >= closed_circuit.config.threshold
            ),
        })

        inputs = {
            seed: fb["input_scale"]
        }

    result = {
        "experiment": "phase3_open_vs_closed_loop_v2",
        "model": "experimental_computational_model",
        "nodes": len(open_circuit.circuit.nodes),
        "edges": len(open_circuit.circuit.edges),
        "steps": steps,
        "target_activity": 0.20,
        "open_loop": {
            "metrics": summarize(open_history),
            "history": open_history,
        },
        "closed_loop_v2": {
            "metrics": summarize(closed_history),
            "history": closed_history,
        },
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return result


if __name__ == "__main__":
    result = run()

    print("Phase 3 open vs closed-loop v2 comparison complete")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])
    print("Steps:", result["steps"])

    print("\nOPEN_LOOP")
    for k, v in result["open_loop"]["metrics"].items():
        print(f"{k}: {v}")

    print("\nCLOSED_LOOP_V2")
    for k, v in result["closed_loop_v2"]["metrics"].items():
        print(f"{k}: {v}")

    print("\nResult:", OUT)
