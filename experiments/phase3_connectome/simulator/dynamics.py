from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicsConfig:
    decay: float = 0.25
    gain: float = 0.05
    threshold: float = 1.0
    max_state: float = 1.0


class ControlledNeuralCircuit:
    """
    Experimental bounded dynamics layer.

    The underlying connectome circuit remains unchanged.
    This layer maintains its own controlled state so that:
      - propagation is deterministic
      - decay is measurable
      - activation remains bounded
      - the original simulator is not modified
    """

    def __init__(self, circuit, config=None):
        self.circuit = circuit
        self.config = config or DynamicsConfig()
        self.state = {
            node_id: 0.0
            for node_id in circuit.nodes
        }

    def step(self, inputs=None):
        inputs = inputs or {}

        # Use the underlying graph only to calculate propagation.
        raw = self.circuit.step(inputs)

        next_state = {}

        for node_id in self.circuit.nodes:
            propagated = float(raw.get(node_id, 0.0))

            # Normalize connectome weights.
            signal = propagated * self.config.gain

            previous = self.state[node_id]

            # Leaky integration.
            value = (
                previous * (1.0 - self.config.decay)
                + signal * self.config.decay
            )

            # Bound state.
            value = max(
                -self.config.max_state,
                min(self.config.max_state, value),
            )

            next_state[node_id] = value

        self.state = next_state

        return dict(self.state)

    def active_nodes(self):
        threshold = self.config.threshold

        return {
            node_id: value
            for node_id, value in self.state.items()
            if abs(value) >= threshold
        }

    def reset(self):
        self.state = {
            node_id: 0.0
            for node_id in self.circuit.nodes
        }
