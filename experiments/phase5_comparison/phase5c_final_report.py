import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "runtime_bridge" / "phase5c_repeated_feedback_probe_result.json"
OUTPUT = ROOT / "PHASE5C_FINAL_REPORT.txt"


def main():
    if not INPUT.exists():
        raise SystemExit(f"Missing runtime result: {INPUT}\nRun phase5c_repeated_feedback_probe.py first.")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    lines = [
        "PHASE 5C — REPEATED REAL-RUNTIME A/B REPORT",
        "=" * 58,
        "",
        f"Trials per case: {data['trials_per_case']}",
        "A = Current Jarvis",
        "B = Current Jarvis + Phase-5B bounded neural feedback",
        f"Controller: {data['controller_scope']} (threshold={data['controller_threshold']})",
        "Brain remains authoritative; neural action execution is disabled.",
        "",
    ]
    all_deltas = []
    for row in data["results"]:
        r = row["repeatability"]
        deltas = [t["mean_latency_delta_B_minus_A_ms"] for t in row["trials"]]
        all_deltas.extend(deltas)
        lines += [
            f"{row['id']} {row['name']}",
            f"  delta mean: {r['delta_mean_ms']:+.2f} ms",
            f"  delta median: {r['delta_median_ms']:+.2f} ms",
            f"  delta stdev: {r['delta_stdev_ms']:.2f} ms",
            f"  improved trials: {r['improved_trials']}/{len(deltas)}",
            f"  slower trials: {r['slower_trials']}/{len(deltas)}",
        ]
        for t in row["trials"]:
            lines.append(
                f"    trial {t['trial']}: A={t['A_aggregate']['mean_latency_ms']:.2f} ms, "
                f"B={t['B_aggregate']['mean_latency_ms']:.2f} ms, "
                f"delta={t['mean_latency_delta_B_minus_A_ms']:+.2f} ms, "
                f"A_success={t['A_aggregate']['success_rate']:.2f}, "
                f"B_success={t['B_aggregate']['success_rate']:.2f}, "
                f"A_tokens={t['A_aggregate']['llm_tokens']}, B_tokens={t['B_aggregate']['llm_tokens']}"
            )
        lines.append("")

    lines += [
        "OVERALL REPEATABILITY",
        "------------------------------",
        f"All-trial mean delta (B-A): {statistics.mean(all_deltas):+.2f} ms" if all_deltas else "No deltas recorded.",
        f"All-trial median delta (B-A): {statistics.median(all_deltas):+.2f} ms" if all_deltas else "",
        "",
        "DECISION GATE",
        "------------------------------",
        "This report does not declare statistical significance or biological validity.",
        "Use the machine-readable JSON plus the real-runtime outputs to decide whether the bounded controller is reproducible enough for the next experiment.",
        "Do not scale the neural layer from latency alone; behavioral correctness, context carryover, errors, and LLM cost must also be considered.",
    ]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
