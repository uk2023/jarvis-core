import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "runtime_bridge" / "phase5b_feedback_probe_result.json"
OUTPUT = ROOT / "PHASE5B_FINAL_REPORT.txt"


def pct(value):
    return f"{value * 100:.1f}%"


def main():
    if not INPUT.exists():
        raise SystemExit(f"Missing runtime result: {INPUT}\nRun phase5b_feedback_probe.py first.")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    lines = [
        "PHASE 5B — BOUNDED NEURAL FEEDBACK A/B REPORT",
        "=" * 58,
        "",
        "A = Current Jarvis",
        "B = Current Jarvis + Phase-4 neural state as a bounded feedback controller",
        "",
        "CONTROL BOUNDARY",
        "------------------------------",
        f"Neural controller threshold: {data.get('controller_threshold')}",
        f"Controlled Brain knob: {data.get('feedback_control')}",
        f"Brain remains authoritative: {data.get('brain_authority_preserved')}",
        f"Neural action execution: {data.get('behavioral_actions')}",
        "",
    ]

    total_a_lat = []
    total_b_lat = []
    total_a_calls = total_b_calls = 0
    total_a_tokens = total_b_tokens = 0
    context_rows = []

    for row in data.get("results", []):
        a = row["A_aggregate"]
        b = row["B_aggregate"]
        total_a_lat.extend(x["latency_ms"] for x in row["A_current_jarvis"])
        total_b_lat.extend(x["latency_ms"] for x in row["B_jarvis_plus_neural_feedback"])
        total_a_calls += a["llm_calls"]
        total_b_calls += b["llm_calls"]
        total_a_tokens += a["llm_tokens"]
        total_b_tokens += b["llm_tokens"]
        context_rows.append(row["context_carryover"])

        lines += [
            f"{row['id']} {row['name']}",
            f"  A mean latency: {a['mean_latency_ms']:.2f} ms",
            f"  B mean latency: {b['mean_latency_ms']:.2f} ms",
            f"  Delta: {b['mean_latency_ms'] - a['mean_latency_ms']:+.2f} ms",
            f"  A success: {pct(a['response_success_rate'])}",
            f"  B success: {pct(b['response_success_rate'])}",
            f"  A LLM calls/tokens: {a['llm_calls']} / {a['llm_tokens']}",
            f"  B LLM calls/tokens: {b['llm_calls']} / {b['llm_tokens']}",
            f"  Context A/B: {row['context_carryover']['A_pass']} / {row['context_carryover']['B_pass']}",
            "  Neural feedback decisions:",
        ]
        for turn in row["B_jarvis_plus_neural_feedback"]:
            feedback = turn.get("feedback") or {}
            neural = turn.get("neural") or {}
            lines.append(
                f"    turn {turn['turn']}: activity={float(neural.get('mean_activity', 0.0)):.8f}, "
                f"mode={turn.get('brain_thinking_mode')}, enabled={feedback.get('enabled')}"
            )
        lines.append("")

    overall_a = statistics.mean(total_a_lat) if total_a_lat else 0.0
    overall_b = statistics.mean(total_b_lat) if total_b_lat else 0.0
    lines += [
        "OVERALL REAL-RUNTIME MEASUREMENT",
        "------------------------------",
        f"A mean turn latency: {overall_a:.2f} ms",
        f"B mean turn latency: {overall_b:.2f} ms",
        f"Latency delta: {overall_b - overall_a:+.2f} ms",
        f"A total LLM calls/tokens: {total_a_calls} / {total_a_tokens}",
        f"B total LLM calls/tokens: {total_b_calls} / {total_b_tokens}",
        "",
        "DECISION GATE",
        "------------------------------",
        "Phase 5B does not assume the neural controller is useful.",
        "Keep it experimental unless the same real tests show a measurable behavioral benefit that justifies its cost.",
        "If B only adds latency/calls without improving a target metric, modify or discard this controller rather than scaling it.",
        "",
        "RESULT",
        "------------------------------",
        "The JSON file is the machine-readable source of truth; this report is only its human-readable summary.",
    ]

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
