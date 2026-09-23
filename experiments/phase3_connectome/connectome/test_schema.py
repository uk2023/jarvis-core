from schema import (
    Neuron,
    Synapse,
    ConnectomeSubgraph,
)


def test_valid_subgraph():
    graph = ConnectomeSubgraph(
        neurons=[
            Neuron("N1", label="input"),
            Neuron("N2", label="relay"),
            Neuron("N3", label="output"),
        ],
        synapses=[
            Synapse("N1", "N2", 0.8),
            Synapse("N2", "N3", 1.2),
        ],
        source_dataset="FlyWire",
        source_release="FAFB v783",
    )

    graph.validate()


def test_unknown_neuron_rejected():
    graph = ConnectomeSubgraph(
        neurons=[Neuron("N1")],
        synapses=[Synapse("N1", "UNKNOWN", 1.0)],
        source_dataset="FlyWire",
        source_release="FAFB v783",
    )

    try:
        graph.validate()
    except ValueError:
        return

    raise AssertionError("Unknown neuron was accepted")


def test_negative_weight_rejected():
    graph = ConnectomeSubgraph(
        neurons=[Neuron("N1"), Neuron("N2")],
        synapses=[Synapse("N1", "N2", -1.0)],
        source_dataset="FlyWire",
        source_release="FAFB v783",
    )

    try:
        graph.validate()
    except ValueError:
        return

    raise AssertionError("Negative weight was accepted")
