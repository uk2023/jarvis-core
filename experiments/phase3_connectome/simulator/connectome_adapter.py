import importlib.util
import json
from pathlib import Path


SIMULATOR_DIR = Path(__file__).resolve().parent
CORE_PATH = SIMULATOR_DIR / "core.py"

_spec = importlib.util.spec_from_file_location(
    "phase3_neural_core",
    CORE_PATH,
)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load simulator core: {CORE_PATH}")

_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

NeuralCircuit = _core.NeuralCircuit
NeuralNode = _core.NeuralNode
NeuralEdge = _core.NeuralEdge


def load_connectome_circuit(path: str | Path) -> NeuralCircuit:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    neuron_ids = [n["neuron_id"] for n in data["neurons"]]

    circuit = NeuralCircuit(
        nodes={
            neuron_id: NeuralNode(node_id=neuron_id)
            for neuron_id in neuron_ids
        },
        edges=[
            NeuralEdge(
                source=edge["source"],
                target=edge["target"],
                weight=float(edge["weight"]),
            )
            for edge in data["synapses"]
        ],
    )

    return circuit


def main():
    path = (
        SIMULATOR_DIR.parent
        / "connectome"
        / "selected_subgraph.json"
    )

    circuit = load_connectome_circuit(path)

    print("Connectome circuit loaded")
    print("Nodes:", len(circuit.nodes))
    print("Edges:", len(circuit.edges))


if __name__ == "__main__":
    main()
