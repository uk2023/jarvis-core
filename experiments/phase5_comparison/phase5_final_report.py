import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = ROOT / "experiments"

V3 = BASE / "phase3_connectome" / "benchmarks" / "closed_loop_v7_result.json"
REC = BASE / "phase3_connectome" / "benchmarks" / "disturbance_recovery_result.json"
AB = BASE / "phase5_comparison" / "ab_comparison_result.json"
REAL = BASE / "phase5_comparison" / "runtime_bridge" / "real_runtime_probe_result.json"

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
    lines.append("The neural experiment is not treated as a replacement for the existing Jarvis brain.")
    lines.append("")

    lines.append("PHASE 3 VALIDATION")
    lines.append("-" * 30)
    lines.append("Connectome nodes: 32")
    lines.append("Connectome edges: 364")
    lines.append(f"Closed-loop settling window: {v3['metrics']['last_50_inside_deadband']}")
    lines.append(f"Tail mean activity: {v3['metrics']['tail_mean_activity']:.9f}")
    lines.append(f"Tail target error: {v3['metrics']['tail_target_error']:.9f}")
    lines.append(f"Disturbance recovery steps: {rec['metrics']['recovery_steps']}")
    lines.append("")

    lines.append("PHASE 5 COMPUTATIONAL MEASUREMENT")
    lines.append("-" * 40)
    for item in ab["results"]:
        a = item["A_current_jarvis"]
        b = item["B_jarvis_plus_neural"]
        lines.append(
            f"{item['name']}: A={a['mean_ms']:.6f} ms, "
            f"B={b['mean_ms']:.6f} ms, "
            f"neural overhead={item['neural_overhead_ms']:+.6f} ms"
        )
    lines.append("")

    if REAL.exists():
        real = load(REAL)
        lines.append("PHASE 5 REAL JARVIS RUNTIME A/B SHADOW MEASUREMENT")
        lines.append("-" * 55)
        lines.append("Neural role: shadow_only")
        lines.append("Behavioral feedback enabled: False")
        lines.append("")
        for item in real.get("results", []):
            a = item.get("A_current_jarvis", [])
            b = item.get("B_jarvis_plus_neural_shadow", [])
            lines.append(f"{item['id']} {item['name']}: A turns={len(a)}, B turns={len(b)}")
            for index, (at, bt) in enumerate(zip(a, b), start=1):
                lines.append(
                    f"  turn {index}: A={at.get('latency_ms', 0):.3f} ms, "
                    f"B={bt.get('latency_ms', 0):.3f} ms, "
                    f"A_nonempty={at.get('response_nonempty')}, "
                    f"B_nonempty={bt.get('response_nonempty')}"
                )
            cc = item.get("context_carryover", {})
            if cc.get("expected"):
                lines.append(f"  context: A={cc.get('A_pass')} B={cc.get('B_pass')}")
        lines.append("")
    else:
        lines.append("REAL RUNTIME MEASUREMENT: NOT YET RUN")
        lines.append("Run experiments/phase5_comparison/runtime_bridge/real_runtime_probe.py")
        lines.append("")

    lines.append("OBSERVATIONS")
    lines.append("-" * 30)
    lines.append("1. Phase 3 neural controller has a bounded operating regime and measurable recovery behavior.")
    lines.append("2. The computational Phase 5 benchmark measures neural overhead only.")
    lines.append("3. The real-runtime bridge is shadow-only: it does not alter Brain decisions or execute actions.")
    lines.append("4. No end-to-end neural improvement is claimed until a controlled feedback experiment changes a bounded workflow and the same real tests are repeated.")
    lines.append("")

    lines.append("DECISION GATE")
    lines.append("-" * 30)
    lines.append("Keep the neural layer experimental and non-authoritative until real A/B evidence demonstrates a measurable benefit.")
    lines.append("Only after the shadow baseline is verified should a bounded neural feedback variant be enabled.")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("Result:", OUT)


if __name__ == "__main__":
    main()
