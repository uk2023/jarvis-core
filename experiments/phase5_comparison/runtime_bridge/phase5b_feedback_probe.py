import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = ROOT / "experiments" / "phase5_comparison" / "runtime_bridge" / "phase5b_feedback_probe_result.json"

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
        "turns": [
            "Analyze this task and explain the required steps without executing anything."
        ],
        "workflow_signal": 1.00,
    },
]


class BoundedNeuralFeedbackController:
    """Phase 5B controller.

    The connectome never writes a response, chooses a route, executes an
    action, or replaces Brain. It controls exactly one bounded Brain knob:
    whether this turn may use the existing extended-thinking path.

    The mapping is deliberately deterministic and small:
      mean_activity < 0.020 -> normal/off
      mean_activity >= 0.020 -> extended/on

    This is an experiment, not a claim that this threshold is biologically
    meaningful. It exists so the neural state can be measured as an actual
    feedback signal rather than remaining shadow-only.
    """

    THRESHOLD = 0.020

    def decide(self, neural_metrics):
        activity = float(neural_metrics.get("mean_activity", 0.0))
        enabled = activity >= self.THRESHOLD
        return {
            "thinking_mode": "on" if enabled else "off",
            "enabled": enabled,
            "threshold": self.THRESHOLD,
            "mean_activity": activity,
            "reason": "neural_activity_threshold" if enabled else "below_neural_threshold",
        }


def _trace_metrics(brain):
    trace = getattr(brain, "last_turn_trace", None)
    if not isinstance(trace, dict):
        return {
            "trace_available": False,
            "trace_stages": 0,
            "llm_calls": 0,
            "llm_tokens": 0,
            "route": None,
        }

    encoded = json.dumps(trace, default=str)
    llm_calls = encoded.count("request_id")
    total_tokens = 0
    marker = "actual_total_tokens"
    pos = 0
    while True:
        pos = encoded.find(marker, pos)
        if pos < 0:
            break
        colon = encoded.find(":", pos)
        comma = encoded.find(",", colon)
        if colon >= 0:
            raw = encoded[colon + 1 : comma if comma >= 0 else len(encoded)].strip().strip("}\n ")
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


def _response_signature(text):
    normalized = " ".join(str(text or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def run_variant(case, neural_enabled):
    core = start_jarvis(heartbeat_interval=60.0, idle_threshold=600.0)
    neural = NeuralStateAdapter() if neural_enabled else None
    controller = BoundedNeuralFeedbackController() if neural_enabled else None
    results = []
    try:
        brain = core.organs["brain"]
        original_thinking_mode = getattr(brain, "thinking_mode", "off")

        for turn_index, prompt in enumerate(case["turns"]):
            feedback = None
            if neural_enabled:
                neural_started = time.perf_counter()
                neural_metrics = neural.process(case["workflow_signal"])
                neural_metrics["latency_ms"] = (time.perf_counter() - neural_started) * 1000
                feedback = controller.decide(neural_metrics)
                # Only this one bounded Brain control is changed.
                brain.thinking_mode = feedback["thinking_mode"]

            started = time.perf_counter()
            error = None
            try:
                response = brain.think_and_respond(
                    prompt,
                    source="phase5b_feedback_probe",
                )
            except Exception as exc:
                response = ""
                error = f"{type(exc).__name__}: {exc}"
            latency_ms = (time.perf_counter() - started) * 1000

            metrics = _trace_metrics(brain)
            response_text = str(response)
            results.append({
                "turn": turn_index + 1,
                "prompt": prompt,
                "response": response_text,
                "response_nonempty": bool(response_text.strip()),
                "response_length": len(response_text),
                "response_signature": _response_signature(response_text),
                "latency_ms": latency_ms,
                "error": error,
                "metrics": metrics,
                "neural": neural_metrics if neural_enabled else None,
                "feedback": feedback,
                "brain_thinking_mode": getattr(brain, "thinking_mode", None),
                "brain_thinking_decision": getattr(brain, "last_thinking_decision", None),
            })

        brain.thinking_mode = original_thinking_mode
    finally:
        stop_jarvis(core)
    return results


def _aggregate(turns):
    latencies = [float(x["latency_ms"]) for x in turns]
    errors = sum(1 for x in turns if x.get("error"))
    nonempty = sum(1 for x in turns if x.get("response_nonempty"))
    calls = sum(int(x["metrics"].get("llm_calls", 0)) for x in turns)
    tokens = sum(int(x["metrics"].get("llm_tokens", 0)) for x in turns)
    return {
        "turns": len(turns),
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "errors": errors,
        "nonempty_responses": nonempty,
        "response_success_rate": nonempty / len(turns) if turns else 0.0,
        "llm_calls": calls,
        "llm_tokens": tokens,
    }


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
            "B_jarvis_plus_neural_feedback": b,
            "A_aggregate": _aggregate(a),
            "B_aggregate": _aggregate(b),
            "context_carryover": {
                "expected": expected,
                "A_pass": a_context,
                "B_pass": b_context,
            },
            "feedback_scope": "existing Brain extended-thinking knob only",
            "brain_authority_preserved": True,
            "neural_action_execution": False,
        })

        print(" A latency:", [round(x["latency_ms"], 2) for x in a], "ms")
        print(" B latency:", [round(x["latency_ms"], 2) for x in b], "ms")
        print(" B feedback:", [x["feedback"] for x in b])
        print(" B thinking:", [x["brain_thinking_mode"] for x in b])
        print(" B LLM calls/tokens:", _aggregate(b)["llm_calls"], _aggregate(b)["llm_tokens"])
        if expected:
            print(" context A/B:", a_context, b_context)

    payload = {
        "experiment": "phase5b_real_runtime_bounded_neural_feedback",
        "brain_authority": "existing_jarvis_brain",
        "neural_role": "bounded_feedback_controller",
        "feedback_control": "brain.thinking_mode only",
        "controller_threshold": BoundedNeuralFeedbackController.THRESHOLD,
        "behavioral_actions": False,
        "results": results,
        "interpretation": "Phase 5B connects the measured neural state to one bounded existing Brain control. No replacement or action authority is granted. Improvement must be judged only from repeated real A/B metrics.",
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\nRESULT:", OUT)


if __name__ == "__main__":
    main()
