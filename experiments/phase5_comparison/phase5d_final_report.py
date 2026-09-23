from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "runtime_bridge" / "phase5d_behavioral_feedback_probe_result.json"
OUTPUT = ROOT / "PHASE5D_FINAL_REPORT.txt"


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"Missing runtime result: {INPUT}\nRun phase5d_behavioral_feedback_probe.py first.")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    lines = [
        "PHASE 5D — REAL BEHAVIORAL FEEDBACK A/B REPORT",
        "=" * 58, "",
        f"Trials per case: {data['trials_per_case']}",
        "A = Current Jarvis with controlled thinking OFF/ON by case",
        "B = Current Jarvis + Phase-5B bounded neural feedback",
        f"Controller: {data['controller_scope']} (threshold={data['controller_threshold']})",
        "Brain remains authoritative; neural action execution is disabled.",
        "Behavioral correctness is deterministic and case-specific; no evaluator LLM call is added.", "",
    ]
    latency_deltas, provider_latency_deltas, call_deltas, token_deltas, accuracy_deltas = [], [], [], [], []
    for row in data["results"]:
        lines += [f"{row['id']} {row['name']}", f"  expected thinking for B: {row.get('expected_thinking')}"]
        for trial in row["trials"]:
            a, b, d = trial["A_aggregate"], trial["B_aggregate"], trial["behavioral_delta"]
            latency_deltas.append(float(d["latency_delta_B_minus_A_ms"]))
            provider_latency_deltas.append(float(d["provider_latency_delta_B_minus_A_ms"]))
            call_deltas.append(int(d["llm_calls_delta_B_minus_A"]))
            token_deltas.append(int(d["total_tokens_delta_B_minus_A"]))
            accuracy_deltas.append(float(d["behavioral_correctness_delta_B_minus_A"]))
            lines += [
                f"  trial {trial['trial']}:",
                f"    thinking used A/B: {a['thinking_used_turns']} / {b['thinking_used_turns']}",
                f"    thinking stages A/B: {a['thinking_stage_count']} / {b['thinking_stage_count']}",
                f"    behavioral correctness mean A/B: {a['behavioral_correctness_mean']:.3f} / {b['behavioral_correctness_mean']:.3f}",
                f"    behavioral correctness passes A/B: {a['behavioral_correctness_passes']} / {b['behavioral_correctness_passes']}",
                f"    LLM calls A/B: {a['llm_calls']} / {b['llm_calls']}",
                f"    prompt tokens A/B: {a['prompt_tokens']} / {b['prompt_tokens']}",
                f"    completion tokens A/B: {a['completion_tokens']} / {b['completion_tokens']}",
                f"    total tokens A/B: {a['total_tokens']} / {b['total_tokens']}",
                f"    real provider response latency A/B: {a['provider_response_latency_ms']:.3f} / {b['provider_response_latency_ms']:.3f} ms",
                f"    provider-timed calls A/B: {a.get('provider_timing_calls', 0)} / {b.get('provider_timing_calls', 0)}",
                f"    turn latency A/B: {a['mean_latency_ms']:.2f} / {b['mean_latency_ms']:.2f} ms",
                f"    behavioral correctness delta B-A: {d['behavioral_correctness_delta_B_minus_A']:+.3f}",
                f"    provider latency delta B-A: {d['provider_latency_delta_B_minus_A_ms']:+.3f} ms",
                f"    total token delta B-A: {d['total_tokens_delta_B_minus_A']:+d}",
                f"    errors A/B: {a['errors']} / {b['errors']}",
            ]
        lines.append("")
    lines += [
        "OVERALL BEHAVIORAL/USAGE MEASUREMENT", "--------------------------------------",
        f"Mean behavioral-correctness delta B-A: {statistics.mean(accuracy_deltas):+.3f}" if accuracy_deltas else "Mean behavioral-correctness delta: unavailable",
        f"Mean turn-latency delta B-A: {statistics.mean(latency_deltas):+.2f} ms" if latency_deltas else "Mean turn-latency delta: unavailable",
        f"Mean real-provider-latency delta B-A: {statistics.mean(provider_latency_deltas):+.3f} ms" if provider_latency_deltas else "Mean provider-latency delta: unavailable",
        f"Mean LLM-call delta B-A: {statistics.mean(call_deltas):+.2f}" if call_deltas else "Mean LLM-call delta: unavailable",
        f"Mean total-token delta B-A: {statistics.mean(token_deltas):+.2f}" if token_deltas else "Mean total-token delta: unavailable", "",
        "DECISION GATE", "------------",
        "FruitFly/Phase-5B passes this gate only if repeated real-runtime A/B evidence shows a meaningful behavioral improvement, not merely lower latency or lower token cost.",
        "Thinking activation is taken from the authoritative Brain decision field `think`; the previous 0/0 measurement bug is removed.",
        "LLM calls/tokens are counted only from the persistent real-usage ledger; local token estimates are excluded.",
        "Provider latency is counted from real Groq server-reported inference timing (queue/prompt/completion/total), never client wall-clock time.",
        "T02 directly checks exact context carryover. T03 checks required reasoning structure, trade-offs, verification, and absence of an execution claim.",
        "Do not promote the neural layer from latency alone; compare behavioral correctness, thinking activation, context, errors, real usage, and latency together.",
    ]
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
