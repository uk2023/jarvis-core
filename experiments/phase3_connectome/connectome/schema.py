from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class Neuron:
    neuron_id: str
    label: Optional[str] = None
    cell_type: Optional[str] = None


@dataclass(frozen=True)
class Synapse:
    source: str
    target: str
    weight: float = 1.0
    synapse_type: Optional[str] = None


@dataclass
class ConnectomeSubgraph:
    neurons: list[Neuron]
    synapses: list[Synapse]
    source_dataset: str
    source_release: str

    def validate(self) -> None:
        neuron_ids = {n.neuron_id for n in self.neurons}

        if not neuron_ids:
            raise ValueError("Connectome subgraph contains no neurons")

        for synapse in self.synapses:
            if synapse.source not in neuron_ids:
                raise ValueError(
                    f"Unknown source neuron: {synapse.source}"
                )
            if synapse.target not in neuron_ids:
                raise ValueError(
                    f"Unknown target neuron: {synapse.target}"
                )
            if synapse.weight < 0:
                raise ValueError(
                    f"Negative synapse weight: {synapse.weight}"
                )

    def to_dict(self) -> dict:
        return {
            "source_dataset": self.source_dataset,
            "source_release": self.source_release,
            "neurons": [asdict(n) for n in self.neurons],
            "synapses": [asdict(s) for s in self.synapses],
        }
