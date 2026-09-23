from dataclasses import dataclass, field


@dataclass
class NeuralNode:
    node_id: str
    state: float = 0.0
    threshold: float = 1.0


@dataclass
class NeuralEdge:
    source: str
    target: str
    weight: float = 1.0


@dataclass
class NeuralCircuit:
    nodes: dict[str, NeuralNode] = field(default_factory=dict)
    edges: list[NeuralEdge] = field(default_factory=list)

    def step(self, inputs: dict[str, float]) -> dict[str, float]:
        incoming = {node_id: 0.0 for node_id in self.nodes}

        for node_id, value in inputs.items():
            if node_id in incoming:
                incoming[node_id] += value

        for edge in self.edges:
            source = self.nodes[edge.source]
            incoming[edge.target] += source.state * edge.weight

        outputs = {}

        for node_id, node in self.nodes.items():
            node.state = incoming[node_id]
            outputs[node_id] = node.state

        return outputs
