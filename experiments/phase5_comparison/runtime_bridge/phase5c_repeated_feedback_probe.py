import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = ROOT / "experiments" / "phase5_comparison" / "runtime_bridge" / "phase5c_repeated_feedback_probe_result.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PHASE4))

from neural_state_adapter import NeuralStateAdapter
from core.organism.bootstrap import start_jarvis, stop_jarvis


TRIALS = 5
CASES = [
    {"id": "T01", "name": "simple_query", "turns": ["Hello Jarvis"], "workflow_signal": 0.20},
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


class BoundedNeuralFeedbackController:
    THRESHOLD = 0.020

    def decide(self, metrics):
        activity = float(metrics.get("mean_activity", 0.0))
        enabled = activity >= self.THRESHOLD
        return {
            "thinking_mode": "on" if enabled else "off",
            "enabled": enabled,
            "threshold": self.THRESHOLD,
            "mean_activity": activity,
        }


def trace_metrics(brain):
    trace = getattr(brain, "last_turn_trace", None)
    if not isinstance(trace, dict):
        return {"trace_available": False, "trace_stages": 0, "llm_calls": 0, "llm_tokens": 0, "route": None}
    encoded = json.dumps(trace, default=str)
    calls = encoded.count("request_id")
    tokens = 0
    marker = "actual_total_tokens"
    pos = 0
    while True:
        pos = encoded.find(marker, pos)
        if pos < 0:
            break
        colon = encoded.find(":", pos)
        comma = encoded.find(",", colon)
        try:
            tokens += int(encoded[colon + 1:comma if comma >= 0 else len(encoded)].strip().strip("}\n "))
        except (TypeError, ValueError):
            pass
        pos = colon + 1 if colon >= 0 else pos + len(marker)
    return {
        "trace_available": True,
        "trace_stages": len(trace.get("runtime_contract_trace", []) or []),
        "llm_calls": calls,
        "llm_tokens": tokens,
        "route": trace.get("route") or trace.get("selected_route"),
    }


def response_signature(text):
    return hashlib.sha256(" ".join(str(text or "").split()).lower().encode()).hexdigest()[:16]


def run_variant(case, neural_enabled, trial, variant):
    core = start_jarvis(heartbeat_interval=60.0, idle_threshold=600.0)
    neural = NeuralStateAdapter() if neural_enabled else None
    controller = BoundedNeuralFeedbackController() if neural_enabled else None
    turns = []
    try:
        brain = core.organs["brain"]
        original_mode = getattr(brain, "thinking_mode", "off")
        for index, prompt in enumerate(case["turns"]):
            feedback = None
            neural_metrics = None
            if neural_enabled:
                ns = time.perf_counter()
                neural_metrics = neural.process(case["workflow_signal"])
                neural_metrics["latency_ms"] = (time.perf_counter() - ns) * 1000
                feedback = controller.decide(neural_metrics)
                brain.thinking_mode = feedback["thinking_mode"]

            started = time.perf_counter()
            error = None
            try:
                response = brain.think_and_respond(prompt, source="phase5c_repeated_feedback_probe")
            except Exception as exc:
                response = ""
                error = f"{type(exc).__name__}: {exc}"
            latency = (time.perf_counter() - started) * 1000
            text = str(response)
            turns.append({
                "turn": index + 1,
                "prompt": prompt,
                "response": text,
                "response_nonempty": bool(text.strip()),
                "response_signature": response_signature(text),
                "latency_ms": latency,
                "error": error,
                "metrics": trace_metrics(brain),
                "neural": neural_metrics,
                "feedback": feedback,
                "brain_thinking_mode": getattr(brain, "thinking_mode", None),
                "brain_thinking_decision": getattr(brain, "last_thinking_decision", None),
            })
        brain.thinking_mode = original_mode
    finally:
        stop_jarvis(core)
    return turns


def aggregate(turns):
    lat = [x["latency_ms"] for x in turns]
    return {
        "turns": len(turns),
        "mean_latency_ms": statistics.mean(lat) if lat else 0.0,
        "median_latency_ms": statistics.median(lat) if lat else 0.0,
        "stdev_latency_ms": statistics.stdev(lat) if len(lat) > 1 else 0.0,
        "min_latency_ms": min(lat) if lat else 0.0,
        "max_latency_ms": max(lat) if lat else 0.0,
        "errors": sum(bool(x.get("error")) for x in turns),
        "nonempty_responses": sum(bool(x.get("response_nonempty")) for x in turns),
        "success_rate": (sum(bool(x.get("response_nonempty")) for x in turns) / len(turns)) if turns else 0.0,
        "llm_calls": sum(int(x["metrics"].get("llm_calls", 0)) for x in turns),
        "llm_tokens": sum(int(x["metrics"].get("llm_tokens", 0)) for x in turns),
    }


def main():
    all_results = []
    for case in CASES:
        case_trials = []
        for trial in range(1, TRIALS + 1):
            # Alternate order to reduce systematic A-first/B-first bias.
            if trial % 2:
                a = run_variant(case, False, trial, "A")
                b = run_variant(case, True, trial, "B")
            else:
                b = run_variant(case, True, trial, "B")
                a = run_variant(case, False, trial, "A")
            expected = case.get("expected")
            a_context = expected.lower() in a[-1]["response"].lower() if expected else None
            b_context = expected.lower() in b[-1]["response"].lower() if expected else None
            aagg, bagg = aggregate(a), aggregate(b)
            case_trials.append({
                "trial": trial,
                "A": a,
                "B": b,
                "A_aggregate": aagg,
                "B_aggregate": bagg,
                "context_carryover": {"expected": expected, "A_pass": a_context, "B_pass": b_context},
                "mean_latency_delta_B_minus_A_ms": bagg["mean_latency_ms"] - aagg["mean_latency_ms"],
            })
            print(f"[{case['id']}] trial {trial}: A={aagg['mean_latency_ms']:.2f} ms B={bagg['mean_latency_ms']:.2f} ms delta={bagg['mean_latency_ms']-aagg['mean_latency_ms']:+.2f} ms")
            if expected:
                print(f"  context A/B: {a_context} / {b_context}")

        deltas = [x["mean_latency_delta_B_minus_A_ms"] for x in case_trials]
        all_results.append({
            "id": case["id"],
            "name": case["name"],
            "trials": case_trials,
            "repeatability": {
                "delta_mean_ms": statistics.mean(deltas),
                "delta_median_ms": statistics.median(deltas),
                "delta_stdev_ms": statistics.stdev(deltas) if len(deltas) > 1 else 0.0,
                "improved_trials": sum(d < 0 for d in deltas),
                "slower_trials": sum(d > 0 for d in deltas),
                "tie_trials": sum(d == 0 for d in deltas),
            },
        })

    payload = {
        "experiment": "phase5c_repeated_real_runtime_ab",
        "trials_per_case": TRIALS,
        "cases": [x["name"] for x in CASES],
        "A": "current_jarvis",
        "B": "current_jarvis_plus_phase5b_bounded_neural_feedback",
        "controller_scope": "brain.thinking_mode only",
        "controller_threshold": BoundedNeuralFeedbackController.THRESHOLD,
        "brain_authority_preserved": True,
        "neural_action_execution": False,
        "order_control": "alternating A/B order by trial",
        "results": all_results,
        "interpretation": "Phase 5C is a repeatability measurement. It does not declare neural benefit or statistical significance; the recorded real-runtime output is the source of truth for the next decision.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("RESULT:", OUT)


if __name__ == "__main__":
    main()
