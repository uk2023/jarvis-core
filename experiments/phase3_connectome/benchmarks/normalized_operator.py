import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SIMULATOR = ROOT / "simulator"
GRAPH = ROOT / "connectome" / "selected_subgraph.json"
OUT = ROOT / "benchmarks" / "normalized_operator_result.json"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_module(
    SIMULATOR / "connectome_adapter.py",
    "phase3_operator_adapter",
)


def build_normalized_operator(circuit):
    outgoing = {node_id: [] for node_id in circuit.nodes}

    for edge in circuit.edges:
        outgoing[edge.source].append(edge)

    operator = {}

    for source, edges in outgoing.items():
        total = sum(abs(float(edge.weight)) for edge in edges)

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


def step(operator, state):
    next_state = {
        node_id: 0.0
        for node_id in operator
    }

    for source, value in state.items():
        if value == 0.0:
            continue

        for target, weight in operator.get(source, []):
            next_state[target] += value * weight

    return next_state


def run(steps=20):
    circuit = adapter.load_connectome_circuit(GRAPH)
    operator = build_normalized_operator(circuit)

    seed = "0"

    state = {
        node_id: 0.0
        for node_id in circuit.nodes
    }
    state[seed] = 1.0

    history = []

    for step_index in range(steps):
        total = sum(abs(v) for v in state.values())
        mean_activity = total / len(state)
        max_activity = max(abs(v) for v in state.values())

        history.append({
            "step": step_index,
            "mean_activity": mean_activity,
            "total_activity": total,
            "max_activity": max_activity,
            "nonzero_nodes": sum(
                1 for v in state.values()
                if abs(v) > 0.0
            ),
        })

        state = step(operator, state)

    result = {
        "experiment": "phase3_connectome_normalized_operator",
        "model": "experimental_computational_model",
        "nodes": len(circuit.nodes),
        "edges": len(circuit.edges),
        "steps": steps,
        "seed": seed,
        "history": history,
    }

    OUT.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    return result


if __name__ == "__main__":
    result = run()

    print("NORMALIZED OPERATOR DIAGNOSTIC")
    print("Nodes:", result["nodes"])
    print("Edges:", result["edges"])

    for item in result["history"]:
        print(
            f"step={item['step']:2d} "
            f"mean={item['mean_activity']:.8f} "
            f"max={item['max_activity']:.8f} "
            f"nonzero={item['nonzero_nodes']:2d}"
        )

    print("Result:", OUT)
