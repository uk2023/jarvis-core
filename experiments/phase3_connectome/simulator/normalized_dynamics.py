from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedDynamicsConfig:
    gain: float = 0.25
    decay: float = 0.25
    max_state: float = 1.0


class NormalizedNeuralCircuit:
    """
    Experimental bounded propagation model.

    Raw connectome edge weights are normalized before propagation.
    The original NeuralCircuit is not modified.
    """

    def __init__(self, circuit, config=None):
        self.circuit = circuit
        self.config = config or NormalizedDynamicsConfig()

        self.state = {
            node_id: 0.0
            for node_id in circuit.nodes
        }

        self.incoming = {
            node_id: []
            for node_id in circuit.nodes
        }

        for edge in circuit.edges:
            self.incoming[edge.target].append(edge)

        # Normalize each target's incoming weights.
        self.normalized_weights = {}

        for target, edges in self.incoming.items():
            total = sum(abs(float(edge.weight)) for edge in edges)

            if total == 0.0:
                self.normalized_weights[target] = {}
                continue

            self.normalized_weights[target] = {
                edge.source: float(edge.weight) / total
                for edge in edges
            }

    def step(self, inputs=None):
        inputs = inputs or {}

        next_state = {}

        for node_id in self.circuit.nodes:
            propagated = 0.0

            for source, weight in self.normalized_weights[node_id].items():
                propagated += self.state[source] * weight

            external = float(inputs.get(node_id, 0.0))

            signal = (
                propagated + external
            ) * self.config.gain

            value = (
                self.state[node_id] * (1.0 - self.config.decay)
                + signal * self.config.decay
            )

            value = max(
                -self.config.max_state,
                min(self.config.max_state, value),
            )

            next_state[node_id] = value

        self.state = next_state

        return dict(self.state)

    def reset(self):
        self.state = {
            node_id: 0.0
            for node_id in self.circuit.nodes
        }
