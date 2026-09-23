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
        "=" * 58,
        "",
        f"Trials per case: {data['trials_per_case']}",
        "A = Current Jarvis",
        "B = Current Jarvis + Phase-5B bounded neural feedback",
        f"Controller: {data['controller_scope']} (threshold={data['controller_threshold']})",
        "Brain remains authoritative; neural action execution is disabled.",
        "",
    ]

    latency_deltas = []
    call_deltas = []
    token_deltas = []
    behavior_matches = []

    for row in data["results"]:
        lines += [f"{row['id']} {row['name']}", f"  expected thinking: {row.get('expected_thinking')}"]
        for trial in row["trials"]:
            a = trial["A_aggregate"]
            b = trial["B_aggregate"]
            d = trial["behavioral_delta"]
            latency_deltas.append(float(d["latency_delta_B_minus_A_ms"]))
            call_deltas.append(int(d["llm_calls_delta_B_minus_A"]))
            token_deltas.append(int(d["total_tokens_delta_B_minus_A"]))
            for side in (a, b):
                if side.get("thinking_expectation_matches") is not None:
                    behavior_matches.append((side.get("thinking_expectation_matches", 0), side.get("thinking_expectation_total", 0)))
            lines += [
                f"  trial {trial['trial']}: ",
                f"    thinking used A/B: {a['thinking_used_turns']} / {b['thinking_used_turns']}",
                f"    thinking stages A/B: {a['thinking_stage_count']} / {b['thinking_stage_count']}",
                f"    thinking expectation matches A/B: {a.get('thinking_expectation_matches')} / {b.get('thinking_expectation_matches')}",
                f"    LLM calls A/B: {a['llm_calls']} / {b['llm_calls']}",
                f"    prompt tokens A/B: {a['prompt_tokens']} / {b['prompt_tokens']}",
                f"    completion tokens A/B: {a['completion_tokens']} / {b['completion_tokens']}",
                f"    total tokens A/B: {a['total_tokens']} / {b['total_tokens']}",
                f"    latency delta B-A: {d['latency_delta_B_minus_A_ms']:+.2f} ms",
                f"    errors A/B: {a['errors']} / {b['errors']}",
            ]
        lines.append("")

    lines += [
        "OVERALL BEHAVIORAL/USAGE MEASUREMENT",
        "--------------------------------------",
        f"Mean latency delta B-A: {statistics.mean(latency_deltas):+.2f} ms" if latency_deltas else "Mean latency delta: unavailable",
        f"Mean LLM-call delta B-A: {statistics.mean(call_deltas):+.2f}" if call_deltas else "Mean LLM-call delta: unavailable",
        f"Mean total-token delta B-A: {statistics.mean(token_deltas):+.2f}" if token_deltas else "Mean total-token delta: unavailable",
        "",
        "DECISION GATE",
        "------------",
        "Phase 5D measures whether bounded neural feedback changes the actual Brain thinking behavior and what real provider usage it causes.",
        "LLM calls/tokens are counted only from the persistent real-usage ledger; local token estimates are excluded.",
        "Latency alone must not be used to promote the neural layer.",
        "Use thinking correctness, response correctness, context behavior, errors, real LLM usage, and latency together for the next decision.",
    ]

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
