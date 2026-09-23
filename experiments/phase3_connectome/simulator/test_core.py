import importlib.util
from pathlib import Path


SIMULATOR_DIR = Path(__file__).resolve().parent
CORE_PATH = SIMULATOR_DIR / "core.py"

spec = importlib.util.spec_from_file_location(
    "phase3_test_core",
    CORE_PATH,
)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

NeuralCircuit = core.NeuralCircuit
NeuralNode = core.NeuralNode
NeuralEdge = core.NeuralEdge


def test_signal_propagation():
    circuit = NeuralCircuit(
        nodes={
            "A": NeuralNode("A"),
            "B": NeuralNode("B"),
            "C": NeuralNode("C"),
        },
        edges=[
            NeuralEdge("A", "B", 1.0),
            NeuralEdge("B", "C", 1.0),
        ],
    )

    first = circuit.step({"A": 1.0})

    assert first["A"] == 1.0
    assert first["B"] == 0.0

    second = circuit.step({})

    assert second["B"] == 1.0
    assert second["C"] == 0.0

    third = circuit.step({})

    assert third["C"] == 1.0
