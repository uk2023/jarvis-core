import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_core_diag_adapter",
)


def summarize(states):
    values = [abs(float(v)) for v in states.values()]

    return {
        "mean": sum(values) / len(values),
        "max": max(values),
        "active_nonzero": sum(v != 0.0 for v in values),
        "active_ge_1": sum(v >= 1.0 for v in values),
    }


def main():
    circuit = adapter.load_connectome_circuit(GRAPH)

    print("CORE DIAGNOSTIC")
    print("Nodes:", len(circuit.nodes))
    print("Edges:", len(circuit.edges))
    print()

    inputs = {"0": 1.0}

    for step in range(12):
        states = circuit.step(inputs)

        metrics = summarize(states)

        print(
            f"step={step:2d} "
            f"mean={metrics['mean']:.6g} "
            f"max={metrics['max']:.6g} "
            f"nonzero={metrics['active_nonzero']:2d} "
            f">=1={metrics['active_ge_1']:2d}"
        )

        inputs = {}


if __name__ == "__main__":
    main()
