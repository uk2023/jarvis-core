import argparse
import gc
import hashlib
import json
import multiprocessing
import os
import resource
import statistics
import sys
import tempfile
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
    core = None
    turns = []
    try:
        core = start_jarvis(heartbeat_interval=60.0, idle_threshold=600.0)
        neural = NeuralStateAdapter() if neural_enabled else None
        controller = BoundedNeuralFeedbackController() if neural_enabled else None
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
        return {
            "ok": True,
            "turns": turns,
            "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "trial": trial,
            "variant": variant,
        }
    except BaseException as exc:
        return {
            "ok": False,
            "turns": turns,
            "error": f"{type(exc).__name__}: {exc}",
            "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "trial": trial,
            "variant": variant,
        }
    finally:
        if core is not None:
            try:
                stop_jarvis(core)
            except Exception:
                pass
        gc.collect()


def _isolated_worker(case, neural_enabled, trial, variant, result_path):
    result = run_variant(case, neural_enabled, trial, variant)
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")


def run_variant_isolated(case, neural_enabled, trial, variant):
    """Run one A/B variant in a separate process so Jarvis/ONNX memory is OS-reclaimed."""
    with tempfile.TemporaryDirectory(prefix="phase5c_") as tmp:
        result_path = Path(tmp) / "variant.json"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_isolated_worker,
            args=(case, neural_enabled, trial, variant, str(result_path)),
        )
        proc.start()
        proc.join()
        if not result_path.exists():
            raise RuntimeError(
                f"isolated {variant} worker exited without a result (exitcode={proc.exitcode})"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if proc.exitcode not in (0, None) and result.get("ok"):
            result["ok"] = False
            result["error"] = f"worker exited with code {proc.exitcode}"
        return result


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


def atomic_write(payload):
    """Write a valid checkpoint after every completed trial."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="phase5c_checkpoint_", suffix=".json", dir=OUT.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, OUT)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def load_checkpoint():
    if not OUT.exists():
        return None
    try:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("experiment") != "phase5c_repeated_real_runtime_ab":
        return None
    return payload


def empty_payload():
    return {
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
        "execution_safety": {
            "variant_process_isolation": True,
            "checkpoint_after_each_trial": True,
            "atomic_checkpoint_write": True,
            "resume_supported": True,
            "child_max_rss_recorded": True,
        },
        "status": "in_progress",
        "results": [],
        "interpretation": "Phase 5C is a repeatability measurement. It does not declare neural benefit or statistical significance; the recorded real-runtime output is the source of truth for the next decision.",
    }


def main():
    parser = argparse.ArgumentParser(description="Safe/resumable Phase 5C real-runtime A/B probe")
    parser.add_argument("--reset", action="store_true", help="discard the existing Phase 5C checkpoint")
    args = parser.parse_args()

    if args.reset and OUT.exists():
        OUT.unlink()

    payload = load_checkpoint() if not args.reset else None
    resumed = payload is not None
    if payload is None:
        payload = empty_payload()

    completed = {(item["id"], trial["trial"]) for item in payload.get("results", []) for trial in item.get("trials", [])}

    for case in CASES:
        case_entry = next((x for x in payload["results"] if x.get("id") == case["id"]), None)
        if case_entry is None:
            case_entry = {"id": case["id"], "name": case["name"], "trials": [], "repeatability": {}}
            payload["results"].append(case_entry)

        for trial in range(1, TRIALS + 1):
            if (case["id"], trial) in completed:
                print(f"[{case['id']}] trial {trial}: already checkpointed; skipping")
                continue

            if trial % 2:
                a_result = run_variant_isolated(case, False, trial, "A")
                b_result = run_variant_isolated(case, True, trial, "B")
            else:
                b_result = run_variant_isolated(case, True, trial, "B")
                a_result = run_variant_isolated(case, False, trial, "A")

            a = a_result.get("turns", [])
            b = b_result.get("turns", [])
            expected = case.get("expected")
            a_context = expected.lower() in a[-1]["response"].lower() if expected and a else None
            b_context = expected.lower() in b[-1]["response"].lower() if expected and b else None
            aagg, bagg = aggregate(a), aggregate(b)
            case_entry["trials"].append({
                "trial": trial,
                "A": a,
                "B": b,
                "A_worker": {"ok": a_result.get("ok"), "error": a_result.get("error"), "max_rss_kb": a_result.get("max_rss_kb")},
                "B_worker": {"ok": b_result.get("ok"), "error": b_result.get("error"), "max_rss_kb": b_result.get("max_rss_kb")},
                "A_aggregate": aagg,
                "B_aggregate": bagg,
                "context_carryover": {"expected": expected, "A_pass": a_context, "B_pass": b_context},
                "mean_latency_delta_B_minus_A_ms": bagg["mean_latency_ms"] - aagg["mean_latency_ms"],
            })
            case_entry["trials"].sort(key=lambda x: x["trial"])
            deltas = [x["mean_latency_delta_B_minus_A_ms"] for x in case_entry["trials"]]
            case_entry["repeatability"] = {
                "delta_mean_ms": statistics.mean(deltas),
                "delta_median_ms": statistics.median(deltas),
                "delta_stdev_ms": statistics.stdev(deltas) if len(deltas) > 1 else 0.0,
                "improved_trials": sum(d < 0 for d in deltas),
                "slower_trials": sum(d > 0 for d in deltas),
                "tie_trials": sum(d == 0 for d in deltas),
            }
            payload["status"] = "in_progress"
            payload["checkpointed_after"] = {"case": case["id"], "trial": trial}
            payload["resumed_from_checkpoint"] = resumed
            atomic_write(payload)
            print(f"[{case['id']}] trial {trial}: A={aagg['mean_latency_ms']:.2f} ms B={bagg['mean_latency_ms']:.2f} ms delta={bagg['mean_latency_ms']-aagg['mean_latency_ms']:+.2f} ms")
            if expected:
                print(f"  context A/B: {a_context} / {b_context}")
            print(f"  worker RSS KB A/B: {a_result.get('max_rss_kb')} / {b_result.get('max_rss_kb')}")
            completed.add((case["id"], trial))
            gc.collect()

    payload["status"] = "complete"
    payload["completed_trials"] = sum(len(x.get("trials", [])) for x in payload["results"])
    payload["resumed_from_checkpoint"] = resumed
    atomic_write(payload)
    print("RESULT:", OUT)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
