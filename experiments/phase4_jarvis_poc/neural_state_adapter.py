import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
SIMULATOR = ROOT / "experiments" / "phase3_connectome" / "simulator"
GRAPH = ROOT / "experiments" / "phase3_connectome" / "connectome" / "selected_subgraph.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase4_adapter",
)

operator_module = load_module(
    SIMULATOR / "normalized_operator.py",
    "phase4_operator",
)


class NeuralStateAdapter:
    """
    Phase 4 experimental bridge.

    This does NOT replace Jarvis reasoning or the LLM.
    It converts an external scalar workflow signal into a
    deterministic connectome state and exposes measurements.
    """

    def __init__(self):
        circuit = adapter.load_connectome_circuit(GRAPH)
        self.operator = operator_module.NormalizedConnectomeOperator(
            circuit
        )

        self.state = {
            node_id: 0.0
            for node_id in circuit.nodes
        }

    def reset(self):
        for node_id in self.state:
            self.state[node_id] = 0.0

    def process(self, signal):
        signal = max(0.0, min(1.0, float(signal)))

        seed = "0"
        self.state[seed] = signal

        self.state = self.operator.step(self.state)

        values = [
            abs(float(value))
            for value in self.state.values()
        ]

        return {
            "mean_activity": sum(values) / len(values),
            "total_activity": sum(values),
            "max_activity": max(values),
            "active_nodes": sum(
                1 for value in values
                if value > 0.0
            ),
            "input_signal": signal,
        }
