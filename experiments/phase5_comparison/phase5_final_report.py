import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = ROOT / "experiments"

V3 = BASE / "phase3_connectome" / "benchmarks" / "closed_loop_v7_result.json"
REC = BASE / "phase3_connectome" / "benchmarks" / "disturbance_recovery_result.json"
AB = BASE / "phase5_comparison" / "ab_comparison_result.json"

OUT = BASE / "phase5_comparison" / "PHASE5_FINAL_REPORT.txt"


def load(path):
    return json.loads(path.read_text())


def main():
    v3 = load(V3)
    rec = load(REC)
    ab = load(AB)

    lines = []

    lines.append("PHASE 5 — JARVIS A/B COMPARISON FINAL REPORT")
    lines.append("=" * 55)
    lines.append("")
    lines.append("A = Current Jarvis")
    lines.append("B = Current Jarvis + experimental neural layer")
    lines.append("")
    lines.append("IMPORTANT:")
    lines.append(
        "The neural experiment is not treated as a replacement "
        "for the existing Jarvis brain."
    )
    lines.append("")

    lines.append("PHASE 3 VALIDATION")
    lines.append("-" * 30)
    lines.append(f"Connectome nodes: 32")
    lines.append(f"Connectome edges: 364")
    lines.append(
        f"Closed-loop settling window: "
        f"{v3['metrics']['last_50_inside_deadband']}"
    )
    lines.append(
        f"Tail mean activity: "
        f"{v3['metrics']['tail_mean_activity']:.9f}"
    )
    lines.append(
        f"Tail target error: "
        f"{v3['metrics']['tail_target_error']:.9f}"
    )
    lines.append(
        f"Disturbance recovery steps: "
        f"{rec['metrics']['recovery_steps']}"
    )
    lines.append("")

    lines.append("PHASE 5 A/B COMPUTATIONAL MEASUREMENT")
    lines.append("-" * 40)

    for item in ab["results"]:
        a = item["A_current_jarvis"]
        b = item["B_jarvis_plus_neural"]

        lines.append(
            f"{item['name']}: "
            f"A={a['mean_ms']:.6f} ms, "
            f"B={b['mean_ms']:.6f} ms, "
            f"neural overhead={item['neural_overhead_ms']:+.6f} ms"
        )

    lines.append("")
    lines.append("OBSERVATIONS")
    lines.append("-" * 30)
    lines.append(
        "1. The Phase 3 neural controller reaches a stable bounded "
        "operating regime."
    )
    lines.append(
        "2. Disturbance/recovery testing shows measurable recovery "
        "behavior."
    )
    lines.append(
        "3. Phase 4 neural adapter is deterministic and bounded."
    )
    lines.append(
        "4. Phase 5 currently demonstrates neural computational "
        "overhead, not an end-to-end Jarvis performance improvement."
    )
    lines.append(
        "5. No claim of improved response quality, context carryover, "
        "interruption handling, or action success is made because those "
        "real Jarvis measurements have not yet been connected."
    )
    lines.append("")

    lines.append("DECISION GATE")
    lines.append("-" * 30)
    lines.append(
        "The neural layer remains an experimental POC. "
        "It should not replace or override the existing Jarvis brain."
    )
    lines.append(
        "Further scaling requires real Jarvis workflow measurements "
        "showing a measurable benefit."
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print("Result:", OUT)


if __name__ == "__main__":
    main()
