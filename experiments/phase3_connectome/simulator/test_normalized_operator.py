import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE_PATH = ROOT / "core.py"
OPERATOR_PATH = ROOT / "normalized_operator.py"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_module(
    CORE_PATH,
    "phase3_normalized_test_core",
)

operator_module = load_module(
    OPERATOR_PATH,
    "phase3_normalized_operator",
)

NeuralCircuit = core.NeuralCircuit
NeuralNode = core.NeuralNode
NeuralEdge = core.NeuralEdge

NormalizedConnectomeOperator = (
    operator_module.NormalizedConnectomeOperator
)


def make_circuit():
    return NeuralCircuit(
        nodes={
            "A": NeuralNode("A"),
            "B": NeuralNode("B"),
            "C": NeuralNode("C"),
        },
        edges=[
            NeuralEdge("A", "B", 2.0),
            NeuralEdge("A", "C", 1.0),
            NeuralEdge("B", "C", 1.0),
        ],
    )


def test_operator_normalizes_outgoing_weights():
    operator = NormalizedConnectomeOperator(
        make_circuit()
    )

    weights = dict(operator.operator["A"])

    assert abs(weights["B"] - (2.0 / 3.0)) < 1e-12
    assert abs(weights["C"] - (1.0 / 3.0)) < 1e-12


def test_signal_propagates():
    operator = NormalizedConnectomeOperator(
        make_circuit()
    )

    first = operator.step({
        "A": 1.0,
        "B": 0.0,
        "C": 0.0,
    })

    assert first["B"] > 0.0
    assert first["C"] > 0.0


def test_state_is_bounded():
    operator = NormalizedConnectomeOperator(
        make_circuit()
    )

    state = operator.step({
        "A": 100.0,
        "B": 0.0,
        "C": 0.0,
    })

    assert all(
        abs(value) <= 1.0
        for value in state.values()
    )


def test_deterministic():
    a = NormalizedConnectomeOperator(make_circuit())
    b = NormalizedConnectomeOperator(make_circuit())

    state_a = {
        "A": 1.0,
        "B": 0.0,
        "C": 0.0,
    }

    state_b = dict(state_a)

    for _ in range(5):
        state_a = a.step(state_a)
        state_b = b.step(state_b)

    assert state_a == state_b
