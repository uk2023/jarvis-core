from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedOperatorConfig:
    max_state: float = 1.0


class NormalizedConnectomeOperator:
    """
    Row-normalized connectome propagation.

    Each source node distributes its activity across outgoing
    edges according to normalized absolute edge weight.

    Experimental computational model only.
    """

    def __init__(self, circuit, config=None):
        self.circuit = circuit
        self.config = config or NormalizedOperatorConfig()

        self.operator = self._build_operator()

    def _build_operator(self):
        outgoing = {
            node_id: []
            for node_id in self.circuit.nodes
        }

        for edge in self.circuit.edges:
            outgoing[edge.source].append(edge)

        operator = {}

        for source, edges in outgoing.items():
            total = sum(
                abs(float(edge.weight))
                for edge in edges
            )

            if total == 0.0:
                operator[source] = []
                continue

            operator[source] = [
                (
                    edge.target,
                    float(edge.weight) / total,
                )
                for edge in edges
            ]

        return operator

    def step(self, state):
        next_state = {
            node_id: 0.0
            for node_id in self.circuit.nodes
        }

        for source, value in state.items():
            value = float(value)

            if value == 0.0:
                continue

            for target, weight in self.operator.get(source, []):
                next_state[target] += value * weight

        limit = self.config.max_state

        return {
            node_id: max(
                -limit,
                min(limit, value),
            )
            for node_id, value in next_state.items()
        }

    def reset_state(self):
        return {
            node_id: 0.0
            for node_id in self.circuit.nodes
        }
