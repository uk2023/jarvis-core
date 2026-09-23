import json
from pathlib import Path

import scipy.io


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/connectome.mat"
OUT = ROOT / "connectome/selected_subgraph.json"

SOURCE_DATASET = "FlyWire-derived connectome"
SOURCE_RELEASE = "FAFB v783"

# Small deterministic seed. We deliberately keep this tiny for the first POC.
SEED_NODE = 0
MAX_NODES = 32
MIN_WEIGHT = 1.0


def main():
    print("Loading connectome...")
    data = scipy.io.loadmat(RAW)

    W = data["W"]
    total = W["TOT"][0, 0].tocsr()

    print("Matrix shape:", total.shape)
    print("Stored connections:", total.nnz)

    # Start from one deterministic neuron and collect its strongest
    # outgoing connections. This avoids copying the whole connectome.
    row = total[SEED_NODE].tocsr()

    candidates = []
    for target, weight in zip(row.indices, row.data):
        if weight >= MIN_WEIGHT:
            candidates.append((int(target), float(weight)))

    candidates.sort(key=lambda x: (-x[1], x[0]))

    selected = [SEED_NODE]

    for target, _weight in candidates:
        if target not in selected:
            selected.append(target)
        if len(selected) >= MAX_NODES:
            break

    selected_set = set(selected)

    neurons = [
        {
            "neuron_id": str(node_id),
            "source_index": node_id,
        }
        for node_id in selected
    ]

    synapses = []

    # Extract only edges completely inside the selected subgraph.
    for source in selected:
        row = total[source].tocsr()

        for target, weight in zip(row.indices, row.data):
            target = int(target)
            weight = float(weight)

            if target in selected_set and weight >= MIN_WEIGHT:
                synapses.append(
                    {
                        "source": str(source),
                        "target": str(target),
                        "weight": weight,
                    }
                )

    result = {
        "source_dataset": SOURCE_DATASET,
        "source_release": SOURCE_RELEASE,
        "selection": {
            "method": "deterministic strongest-outgoing-neighbors",
            "seed_node": SEED_NODE,
            "max_nodes": MAX_NODES,
            "min_weight": MIN_WEIGHT,
        },
        "neurons": neurons,
        "synapses": synapses,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print()
    print("Selected neurons:", len(neurons))
    print("Selected synapses:", len(synapses))
    print("Output:", OUT)


if __name__ == "__main__":
    main()
