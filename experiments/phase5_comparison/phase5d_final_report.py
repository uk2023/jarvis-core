from __future__ import annotations

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "runtime_bridge" / "phase5d_behavioral_feedback_probe_result.json"
OUTPUT = ROOT / "PHASE5D_FINAL_REPORT.txt"


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def workflow_summary(result: dict) -> dict[str, object]:
    """Extract workflow evidence already captured by the real Brain/Deep Inspector path.

    This is deliberately observational: it never invents a missing workflow field and
    never calls an evaluator LLM.
    """
    turns = result.get("turns", []) if isinstance(result, dict) else []
    routes: list[str] = []
    trace_success = 0
    nonempty = 0
    execution_claims = 0
    for turn in turns:
        behavior = turn.get("behavior", {}) if isinstance(turn, dict) else {}
        if behavior.get("route"):
            routes.append(str(behavior["route"]))
        if behavior.get("trace_pipeline_success"):
            trace_success += 1
        if behavior.get("response_nonempty"):
            nonempty += 1
        checks = (behavior.get("behavioral_correctness") or {}).get("checks", {})
        if checks.get("no_execution_claim") is False:
            execution_claims += 1
    return {
        "turns": len(turns),
        "trace_pipeline_success": trace_success,
        "nonempty_responses": nonempty,
        "false_execution_claims": execution_claims,
        "routes": routes,
    }


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"Missing runtime result: {INPUT}\nRun phase5d_behavioral_feedback_probe.py first.")

    data = json.loads(INPUT.read_text(encoding="utf-8"))
    lines = [
        "PHASE 5D — FINAL FRUITFLY BEHAVIORAL A/B AUDIT",
        "=" * 58,
        "",
        f"Trials per case: {data['trials_per_case']}",
        "A = Same Jarvis with FruitFly/neural feedback OFF",
        "B = Same Jarvis with FruitFly/neural feedback ON",
        f"Controller: {data['controller_scope']} (threshold={data['controller_threshold']})",
        "Brain remains authoritative; neural action execution is disabled.",
        "No evaluator LLM call is added.",
        "Provider latency/TPM/key-rotation telemetry is EXCLUDED from the FruitFly decision.",
        "Deep-Inspector workflow evidence and existing real usage/thinking telemetry are retained.",
        "",
    ]

    accuracy_deltas: list[float] = []
    latency_deltas: list[float] = []
    call_deltas: list[int] = []
    token_deltas: list[int] = []
    thinking_deltas: list[int] = []
    stage_deltas: list[int] = []
    error_deltas: list[int] = []
    workflow_a = workflow_b = 0

    for row in data["results"]:
        lines += [
            f"{row['id']} {row['name']}",
            f"  expected thinking for B: {row.get('expected_thinking')}",
        ]
        for trial in row["trials"]:
            a, b, d = trial["A_aggregate"], trial["B_aggregate"], trial["behavioral_delta"]
            accuracy_deltas.append(safe_float(d["behavioral_correctness_delta_B_minus_A"]))
            latency_deltas.append(safe_float(d["latency_delta_B_minus_A_ms"]))
            call_deltas.append(int(d["llm_calls_delta_B_minus_A"]))
            token_deltas.append(int(d["total_tokens_delta_B_minus_A"]))
            thinking_deltas.append(int(d["thinking_used_delta_B_minus_A"]))
            stage_deltas.append(int(d["thinking_stage_delta_B_minus_A"]))
            error_deltas.append(int(b.get("errors", 0)) - int(a.get("errors", 0)))
            workflow_a += int(a.get("turns", 0))
            workflow_b += int(b.get("turns", 0))

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
                f"    turn latency A/B: {a['mean_latency_ms']:.2f} / {b['mean_latency_ms']:.2f} ms",
                f"    behavioral correctness delta B-A: {d['behavioral_correctness_delta_B_minus_A']:+.3f}",
                f"    thinking delta B-A: {d['thinking_used_delta_B_minus_A']:+d}",
                f"    thinking-stage delta B-A: {d['thinking_stage_delta_B_minus_A']:+d}",
                f"    total token delta B-A: {d['total_tokens_delta_B_minus_A']:+d}",
                f"    turn latency delta B-A: {d['latency_delta_B_minus_A_ms']:+.2f} ms",
                f"    errors A/B: {a['errors']} / {b['errors']}",
            ]

            # Preserve workflow evidence captured inside each real turn. This is
            # deliberately summarized without treating provider data as evidence.
            for variant_name, variant in (("A", trial.get("A", {})), ("B", trial.get("B", {}))):
                summary = workflow_summary(variant)
                lines.append(
                    f"    workflow {variant_name}: turns={summary['turns']} "
                    f"trace_success={summary['trace_pipeline_success']} "
                    f"nonempty={summary['nonempty_responses']} "
                    f"false_execution_claims={summary['false_execution_claims']}"
                )
        lines.append("")

    # Current deterministic audit uses the observed behavioral delta as its primary gate.
    # Do not manufacture a positive result from latency or token changes.
    overall_delta = mean(accuracy_deltas)
    if overall_delta > 0.05:
        conclusion = "BENEFIT DEMONSTRATED"
        conclusion_detail = "The observed behavioral-correctness delta clears the final audit threshold (> +0.05)."
    elif overall_delta < -0.05:
        conclusion = "BEHAVIORAL REGRESSION"
        conclusion_detail = "The observed behavioral-correctness delta is below the final regression threshold (< -0.05)."
    else:
        conclusion = "NO MEANINGFUL BENEFIT DEMONSTRATED"
        conclusion_detail = "The observed behavioral-correctness delta remains within the neutral band (−0.05 to +0.05)."

    lines += [
        "OVERALL FINAL AUDIT",
        "-------------------",
        f"Mean behavioral-correctness delta B-A: {overall_delta:+.3f}",
        f"Mean turn-latency delta B-A: {mean(latency_deltas):+.2f} ms",
        f"Mean thinking-activation delta B-A: {mean([float(x) for x in thinking_deltas]):+.2f} turns",
        f"Mean thinking-stage delta B-A: {mean([float(x) for x in stage_deltas]):+.2f}",
        f"Mean LLM-call delta B-A: {mean([float(x) for x in call_deltas]):+.2f}",
        f"Mean total-token delta B-A: {mean([float(x) for x in token_deltas]):+.2f}",
        f"Mean error delta B-A: {mean([float(x) for x in error_deltas]):+.2f}",
        f"Observed workflow turns A/B: {workflow_a} / {workflow_b}",
        "Provider latency/TPM/key rotation: excluded by design.",
        "",
        "FINAL CONCLUSION",
        "-----------------",
        conclusion,
        conclusion_detail,
        "Behavioral evidence is the decision authority; latency and token usage are supporting telemetry only.",
        "No additional Phase-5D evidence loop is required after this audit. Proceed to verify → full fix → commit → git pull → local Python 3 test.",
    ]

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUTPUT)
    print("CONCLUSION:", conclusion)


if __name__ == "__main__":
    main()
