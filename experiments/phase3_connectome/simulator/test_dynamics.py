import importlib.util
from pathlib import Path


SIMULATOR_DIR = Path(__file__).resolve().parent


def load_module(filename, module_name):
    path = SIMULATOR_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)

    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load_module("core.py", "phase3_test_dynamics_core")
dynamics = load_module("dynamics.py", "phase3_test_dynamics")

NeuralCircuit = core.NeuralCircuit
NeuralNode = core.NeuralNode
NeuralEdge = core.NeuralEdge

ControlledNeuralCircuit = dynamics.ControlledNeuralCircuit
DynamicsConfig = dynamics.DynamicsConfig


def make_circuit():
    return NeuralCircuit(
        nodes={
            "A": NeuralNode("A"),
            "B": NeuralNode("B"),
            "C": NeuralNode("C"),
        },
        edges=[
            NeuralEdge("A", "B", 2.0),
            NeuralEdge("B", "C", 2.0),
        ],
    )


def test_output_is_bounded():
    controlled = ControlledNeuralCircuit(
        make_circuit(),
        DynamicsConfig(gain=0.05, decay=0.25, max_state=1.0),
    )

    states = controlled.step({"A": 1.0})

    assert all(abs(value) <= 1.0 for value in states.values())


def test_decay_reduces_persistent_state():
    controlled = ControlledNeuralCircuit(
        make_circuit(),
        DynamicsConfig(gain=0.01, decay=0.5, max_state=1.0),
    )

    first = controlled.step({"A": 1.0})
    second = controlled.step({})

    assert abs(second["A"]) < abs(first["A"])


def test_dynamics_are_deterministic():
    a = ControlledNeuralCircuit(make_circuit())
    b = ControlledNeuralCircuit(make_circuit())

    history_a = [
        a.step({"A": 1.0}),
        a.step({}),
        a.step({}),
    ]

    history_b = [
        b.step({"A": 1.0}),
        b.step({}),
        b.step({}),
    ]

    assert history_a == history_b


def test_reset_clears_state():
    controlled = ControlledNeuralCircuit(make_circuit())

    controlled.step({"A": 1.0})
    assert any(value != 0.0 for value in controlled.state.values())

    controlled.reset()

    assert all(value == 0.0 for value in controlled.state.values())
