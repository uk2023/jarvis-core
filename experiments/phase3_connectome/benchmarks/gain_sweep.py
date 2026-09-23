import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "gain_sweep_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dynamics = load_module(
    SIMULATOR / "dynamics.py",
    "phase3_gain_dynamics",
)

adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_gain_adapter",
)


GAINS = [
    1e-9,
    1e-8,
    1e-7,
    1e-6,
    1e-5,
    1e-4,
    1e-3,
]


def run_gain(gain, steps=12):
    circuit = adapter.load_connectome_circuit(GRAPH)

    controlled = dynamics.ControlledNeuralCircuit(
        circuit,
        dynamics.DynamicsConfig(
            gain=gain,
            decay=0.25,
            threshold=0.01,
            max_state=1.0,
        ),
    )

    seed = "0"
    inputs = {seed: 1.0}

    history = []

    for step in range(steps):
        states = controlled.step(inputs)

        activity = (
            sum(abs(float(v)) for v in states.values())
            / len(states)
        )

        active_nodes = sum(
            1
            for value in states.values()
            if abs(value) >= controlled.config.threshold
        )

        history.append({
            "step": step,
            "mean_activity": activity,
            "active_nodes": active_nodes,
            "max_state": max(
                abs(float(v))
                for v in states.values()
            ),
        })

        inputs = {}

    activities = [
        item["mean_activity"]
        for item in history
    ]

    return {
        "gain": gain,
        "initial_activity": activities[0],
        "peak_activity": max(activities),
        "final_activity": activities[-1],
        "final_target_error": abs(activities[-1] - 0.20),
        "final_active_nodes": history[-1]["active_nodes"],
        "history": history,
    }


def main():
    results = [
        run_gain(gain)
        for gain in GAINS
    ]

    result = {
        "experiment": "phase3_connectome_gain_sweep",
        "model": "experimental_computational_model",
        "nodes": 32,
        "edges": 364,
        "target_activity": 0.20,
        "results": results,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Phase 3 gain sweep complete")
    print()

    for item in results:
        print(
            f"gain={item['gain']:<8g} "
            f"initial={item['initial_activity']:.6g} "
            f"peak={item['peak_activity']:.6g} "
            f"final={item['final_activity']:.6g} "
            f"error={item['final_target_error']:.6g} "
            f"active={item['final_active_nodes']}"
        )

    print()
    print("Result:", OUT)


if __name__ == "__main__":
    main()
