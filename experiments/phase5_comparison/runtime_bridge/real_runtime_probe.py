import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = ROOT / "experiments" / "phase5_comparison" / "runtime_bridge" / "real_runtime_probe_result.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PHASE4))

from neural_state_adapter import NeuralStateAdapter
from core.organism.bootstrap import start_jarvis, stop_jarvis


CASES = [
    {
        "id": "T01",
        "name": "simple_query",
        "turns": ["Hello Jarvis"],
        "workflow_signal": 0.20,
    },
    {
        "id": "T02",
        "name": "context_carryover",
        "turns": [
            "Remember this exact test phrase: NEURAL-CONTEXT-42.",
            "What exact test phrase did I just ask you to remember?",
        ],
        "expected": "NEURAL-CONTEXT-42",
        "workflow_signal": 0.50,
    },
    {
        "id": "T03",
        "name": "complex_query",
        "turns": ["Analyze this task and explain the required steps without executing anything."],
        "workflow_signal": 1.00,
    },
]


def _trace_metrics(brain):
    trace = getattr(brain, "last_turn_trace", None)
    if not isinstance(trace, dict):
        return {"trace_available": False, "trace_stages": 0, "llm_calls": 0, "llm_tokens": 0}

    encoded = json.dumps(trace, default=str)
    llm_calls = encoded.count("request_id")
    total_tokens = 0
    for marker in ("actual_total_tokens",):
        pos = 0
        while True:
            pos = encoded.find(marker, pos)
            if pos < 0:
                break
            colon = encoded.find(":", pos)
            comma = encoded.find(",", colon)
            if colon >= 0:
                raw = encoded[colon + 1:comma if comma >= 0 else len(encoded)].strip().strip("}\n ")
                try:
                    total_tokens += int(raw)
                except (TypeError, ValueError):
                    pass
            pos = colon + 1 if colon >= 0 else pos + len(marker)

    return {
        "trace_available": True,
        "trace_stages": len(trace.get("runtime_contract_trace", []) or []),
        "llm_calls": llm_calls,
        "llm_tokens": total_tokens,
        "route": trace.get("route") or trace.get("selected_route"),
    }


def run_variant(case, neural_enabled):
    """Run the real Brain directly; neural path is shadow-only in Phase 5."""
    core = start_jarvis(heartbeat_interval=60.0, idle_threshold=600.0)
    neural = NeuralStateAdapter() if neural_enabled else None
    results = []
    try:
        brain = core.organs["brain"]
        for turn_index, prompt in enumerate(case["turns"]):
            started = time.perf_counter()
            error = None
            try:
                response = brain.think_and_respond(
                    prompt,
                    source="phase5_runtime_probe",
                )
            except Exception as exc:
                response = ""
                error = f"{type(exc).__name__}: {exc}"
            latency_ms = (time.perf_counter() - started) * 1000

            metrics = _trace_metrics(brain)
            neural_metrics = None
            if neural is not None:
                n_started = time.perf_counter()
                neural_metrics = neural.process(case["workflow_signal"])
                neural_metrics["latency_ms"] = (time.perf_counter() - n_started) * 1000

            text = str(response)
            results.append({
                "turn": turn_index + 1,
                "prompt": prompt,
                "response": text,
                "response_nonempty": bool(text.strip()),
                "latency_ms": latency_ms,
                "error": error,
                "metrics": metrics,
                "neural": neural_metrics,
            })
    finally:
        stop_jarvis(core)
    return results


def main():
    results = []

    for case in CASES:
        print(f"\n[{case['id']}] {case['name']}")
        a = run_variant(case, neural_enabled=False)
        b = run_variant(case, neural_enabled=True)

        expected = case.get("expected")
        a_context = None
        b_context = None
        if expected:
            a_context = expected.lower() in (a[-1]["response"] or "").lower()
            b_context = expected.lower() in (b[-1]["response"] or "").lower()

        results.append({
            "id": case["id"],
            "name": case["name"],
            "turns": case["turns"],
            "A_current_jarvis": a,
            "B_jarvis_plus_neural_shadow": b,
            "context_carryover": {
                "expected": expected,
                "A_pass": a_context,
                "B_pass": b_context,
            },
            "neural_role": "shadow_only",
            "behavioral_feedback_enabled": False,
        })

        print(" A:", [round(x["latency_ms"], 3) for x in a], "ms")
        print(" B:", [round(x["latency_ms"], 3) for x in b], "ms")
        if expected:
            print(" context A/B:", a_context, b_context)
        print(" neural activity:", [round(x["neural"]["mean_activity"], 8) for x in b])

    OUT.write_text(
        json.dumps(
            {
                "experiment": "phase5_real_runtime_ab_shadow",
                "brain_authority": "existing_jarvis_brain",
                "neural_role": "shadow_only",
                "behavioral_feedback_enabled": False,
                "results": results,
                "interpretation": "Real Jarvis A/B runtime measurement is now connected. Neural output is observed only; no improvement is claimed until a controlled feedback variant is measured.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nRESULT:", OUT)


if __name__ == "__main__":
    main()
