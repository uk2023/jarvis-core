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
    "phase3_normalized_adapter",
)

normalized = load_module(
    SIMULATOR / "normalized_dynamics.py",
    "phase3_normalized_dynamics",
)


def main():
    circuit = adapter.load_connectome_circuit(GRAPH)

    model = normalized.NormalizedNeuralCircuit(
        circuit,
        normalized.NormalizedDynamicsConfig(
            gain=0.25,
            decay=0.25,
            max_state=1.0,
        ),
    )

    print("NORMALIZED DIAGNOSTIC")
    print("Nodes:", len(circuit.nodes))
    print("Edges:", len(circuit.edges))
    print()

    inputs = {"0": 1.0}

    for step in range(12):
        states = model.step(inputs)

        values = [
            abs(float(v))
            for v in states.values()
        ]

        print(
            f"step={step:2d} "
            f"mean={sum(values) / len(values):.8f} "
            f"max={max(values):.8f} "
            f"nonzero={sum(v != 0.0 for v in values):2d}"
        )

        inputs = {}


if __name__ == "__main__":
    main()
