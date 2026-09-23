from __future__ import annotations

import argparse
import gc
import hashlib
import json
import multiprocessing
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
PHASE4 = ROOT / "experiments" / "phase4_jarvis_poc"
OUT = ROOT / "experiments" / "phase5_comparison" / "runtime_bridge" / "phase5d_behavioral_feedback_probe_result.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PHASE4))

from neural_state_adapter import NeuralStateAdapter
from core.organism.bootstrap import start_jarvis, stop_jarvis
from core.orchestration.groq_provider_latency import install_groq_latency_capture
from core.orchestration.token_management import get_token_manager
from deep_inspector import _real_turn_metrics

install_groq_latency_capture()

TRIALS = 3
CASES = [
    {
        "id": "T01", "name": "simple_control", "turns": ["Hello Jarvis"],
        "workflow_signal": 0.20, "expected_thinking": False,
    },
    {
        "id": "T02", "name": "context_behavior",
        "turns": [
            "Remember this exact test phrase: NEURAL-BEHAVIOR-5D.",
            "What exact test phrase did I just ask you to remember?",
        ],
        "expected": "NEURAL-BEHAVIOR-5D", "workflow_signal": 0.50,
        "expected_thinking": True,
    },
    {
        "id": "T03", "name": "reasoning_behavior",
        "turns": [
            "Analyze this task carefully and explain the required steps, the key trade-offs, and what should be verified before execution. Do not execute anything."
        ],
        "workflow_signal": 1.00, "expected_thinking": True,
    },
]


class BoundedNeuralFeedbackController:
    THRESHOLD = 0.020

    def decide(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        activity = float(metrics.get("mean_activity", 0.0))
        enabled = activity >= self.THRESHOLD
        return {
            "thinking_mode": "on" if enabled else "off",
            "enabled": enabled,
            "threshold": self.THRESHOLD,
            "mean_activity": activity,
        }


def response_signature(text: Any) -> str:
    return hashlib.sha256(" ".join(str(text or "").split()).lower().encode()).hexdigest()[:16]


def token_snapshot() -> Dict[str, Any]:
    try:
        return get_token_manager().summary()
    except Exception as exc:
        return {
            "overall": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": str(exc),
        }


def usage_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, int]:
    b = before.get("overall", {}) if isinstance(before, dict) else {}
    a = after.get("overall", {}) if isinstance(after, dict) else {}
    return {
        k: max(0, int(a.get(k, 0) or 0) - int(b.get(k, 0) or 0))
        for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")
    }


def provider_total_seconds(brain: Any) -> float:
    """Cumulative REAL Groq server-side total_time captured in this process."""
    try:
        llm = getattr(brain, "llm", None)
        return float(getattr(llm, "_phase5_provider_timing_total_seconds", 0.0) or 0.0)
    except Exception:
        return 0.0


def provider_timing_calls(brain: Any) -> int:
    try:
        llm = getattr(brain, "llm", None)
        return int(getattr(llm, "_phase5_provider_timing_calls", 0) or 0)
    except Exception:
        return 0


def provider_timing_snapshot(brain: Any) -> List[Dict[str, Any]]:
    try:
        llm = getattr(brain, "llm", None)
        snapshot = llm.telemetry_snapshot() if llm is not None and hasattr(llm, "telemetry_snapshot") else {}
        result = []
        for key in (snapshot or {}).get("keys", []) or []:
            if not isinstance(key, dict):
                continue
            last = key.get("last_request") or {}
            fields = {
                k: last[k]
                for k in last
                if k.startswith("provider_") or k == "network_overhead_seconds"
            }
            if fields:
                result.append({"key_index": key.get("key_index"), **fields})
        return result
    except Exception:
        return []


def deterministic_behavior_score(case: Dict[str, Any], response: str) -> Dict[str, Any]:
    """Small, transparent behavioral oracle; it never calls another LLM."""
    text = str(response or "")
    lowered = text.lower()
    if not text.strip():
        return {"score": 0.0, "passed": False, "checks": {"nonempty": False}}

    checks: Dict[str, bool] = {"nonempty": True}
    if case["id"] == "T01":
        checks["greeting_response"] = bool(re.search(r"hello|hi|namaste|jarvis", lowered))
    elif case["id"] == "T02":
        expected = case.get("expected", "").lower()
        checks["exact_context_recall"] = expected in lowered
    elif case["id"] == "T03":
        checks["steps_present"] = bool(re.search(r"step|steps|1\.|2\.|first|then|phir|pehle|baad", lowered))
        checks["tradeoffs_present"] = bool(re.search(r"trade.?off|pros|cons|fayda|nuksan|advantage|disadvantage", lowered))
        checks["verification_present"] = bool(re.search(r"verif|check|test|validate|confirm|verify", lowered))
        checks["no_execution_claim"] = not bool(re.search(r"\b(i|we|jarvis)\s+(executed|ran|changed|modified|completed|fixed|deployed)\b", lowered))

    score = sum(bool(v) for v in checks.values()) / len(checks)
    return {"score": round(score, 3), "passed": score >= 0.75, "checks": checks}


def trace_behavior(brain: Any, trace: Dict[str, Any], response: str, case: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _real_turn_metrics(brain, trace)
    decision = getattr(brain, "last_thinking_decision", None)
    decision = decision if isinstance(decision, dict) else {}
    # The real Brain decision uses `think`; the previous probe incorrectly
    # looked only for `thinking_used`, producing 0/0 even when thinking was
    # actually enabled. Preserve both names for compatibility, but use the
    # authoritative `think` flag first.
    thinking_used = bool(decision.get("think", decision.get("thinking_used", False)))
    stages = decision.get("stages") if isinstance(decision.get("stages"), list) else []
    behavior_score = deterministic_behavior_score(case, response)
    timings = trace.get("timings") if isinstance(trace.get("timings"), dict) else {}
    llm_timing_fields = {
        k: v for k, v in timings.items()
        if any(token in str(k).lower() for token in ("llm", "generate", "provider", "model"))
    }
    return {
        "route": trace.get("route") or trace.get("selected_route"),
        "thinking_decision": decision,
        "thinking_used": thinking_used,
        "thinking_mode_requested": decision.get("mode") or getattr(brain, "thinking_mode", None),
        "thinking_reason": decision.get("reason"),
        "thinking_stage_count": len(stages),
        "response_nonempty": bool(str(response).strip()),
        "response_signature": response_signature(response),
        "behavioral_correctness": behavior_score,
        "trace_pipeline_success": bool(trace.get("pipeline_success", False)),
        "turn_timings": timings,
        "llm_timing_fields": llm_timing_fields,
        "real_metrics": metrics,
    }


def run_variant(case: Dict[str, Any], neural_enabled: bool, trial: int, variant: str) -> Dict[str, Any]:
    core = None
    turns: List[Dict[str, Any]] = []
    before_usage = token_snapshot()
    try:
        core = start_jarvis(heartbeat_interval=60.0, idle_threshold=600.0)
        neural = NeuralStateAdapter() if neural_enabled else None
        controller = BoundedNeuralFeedbackController() if neural_enabled else None
        brain = core.organs["brain"]

        # Experimental control: give this A/B harness enough turn-call budget
        # for the real thinking-mode gate to activate after perception. This
        # does NOT change production defaults; it prevents the experiment from
        # measuring "budget blocked thinking" instead of neural behavior.
        llm = getattr(brain, "llm", None)
        if llm is not None and hasattr(llm, "_budget_max_calls"):
            llm._budget_max_calls = max(int(getattr(llm, "_budget_max_calls", 0) or 0), 12)

        original_mode = getattr(brain, "thinking_mode", "off")
        for index, prompt in enumerate(case["turns"]):
            feedback = None
            neural_metrics = None
            if neural is not None:
                started_neural = time.perf_counter()
                neural_metrics = neural.process(case["workflow_signal"])
                neural_metrics["latency_ms"] = (time.perf_counter() - started_neural) * 1000.0
                feedback = controller.decide(neural_metrics)
                brain.thinking_mode = feedback["thinking_mode"]
            else:
                brain.thinking_mode = "on" if case.get("expected_thinking") else "off"

            usage_before_turn = token_snapshot()
            provider_before = provider_total_seconds(brain)
            provider_calls_before = provider_timing_calls(brain)

            started = time.perf_counter()
            error = None
            try:
                response = brain.think_and_respond(prompt, source="phase5d_behavioral_feedback_probe")
            except Exception as exc:
                response = ""
                error = f"{type(exc).__name__}: {exc}"
            latency_ms = (time.perf_counter() - started) * 1000.0

            usage_after_turn = token_snapshot()
            provider_after = provider_total_seconds(brain)
            provider_calls_after = provider_timing_calls(brain)
            trace = getattr(brain, "last_turn_trace", None)
            trace = trace if isinstance(trace, dict) else {}
            behavior = trace_behavior(brain, trace, str(response), case)
            turns.append({
                "turn": index + 1,
                "prompt": prompt,
                "response": str(response),
                "latency_ms": latency_ms,
                "error": error,
                "feedback": feedback,
                "neural": neural_metrics,
                "brain_thinking_mode": getattr(brain, "thinking_mode", None),
                "behavior": behavior,
                "usage_delta": usage_delta(usage_before_turn, usage_after_turn),
                "provider_timing_delta": {
                    "calls": max(0, provider_calls_after - provider_calls_before),
                    "total_time_ms": round(max(0.0, provider_after - provider_before) * 1000.0, 3),
                    "raw_provider_timing": provider_timing_snapshot(brain),
                },
            })
        brain.thinking_mode = original_mode
        after_usage = token_snapshot()
        return {
            "ok": True, "trial": trial, "variant": variant, "turns": turns,
            "usage_delta": usage_delta(before_usage, after_usage),
            "usage_snapshot_after": after_usage,
        }
    except BaseException as exc:
        after_usage = token_snapshot()
        return {
            "ok": False, "trial": trial, "variant": variant, "turns": turns,
            "error": f"{type(exc).__name__}: {exc}",
            "usage_delta": usage_delta(before_usage, after_usage),
            "usage_snapshot_after": after_usage,
        }
    finally:
        if core is not None:
            try:
                stop_jarvis(core)
            except Exception:
                pass
        gc.collect()


def isolated_worker(case: Dict[str, Any], neural_enabled: bool, trial: int, variant: str, result_path: str) -> None:
    Path(result_path).write_text(
        json.dumps(run_variant(case, neural_enabled, trial, variant), indent=2),
        encoding="utf-8",
    )


def run_isolated(case: Dict[str, Any], neural_enabled: bool, trial: int, variant: str) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="phase5d_") as tmp:
        result_path = Path(tmp) / "variant.json"
        proc = multiprocessing.get_context("spawn").Process(
            target=isolated_worker,
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


def aggregate(result: Dict[str, Any]) -> Dict[str, Any]:
    turns = result.get("turns", [])
    latencies = [float(x.get("latency_ms", 0.0)) for x in turns]
    behavior = [x.get("behavior", {}) for x in turns]
    correctness = [float(x.get("behavior", {}).get("behavioral_correctness", {}).get("score", 0.0)) for x in turns]
    thinking = [bool(x.get("behavior", {}).get("thinking_used", False)) for x in turns]
    provider = [float(x.get("provider_timing_delta", {}).get("total_time_ms", 0.0) or 0.0) for x in turns]
    usage = result.get("usage_delta", {})
    return {
        "turns": len(turns),
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "provider_response_latency_ms": sum(provider),
        "provider_timing_calls": sum(int(x.get("provider_timing_delta", {}).get("calls", 0) or 0) for x in turns),
        "errors": sum(bool(x.get("error")) for x in turns),
        "nonempty_responses": sum(bool(x.get("behavior", {}).get("response_nonempty")) for x in turns),
        "thinking_used_turns": sum(thinking),
        "thinking_stage_count": sum(int(x.get("behavior", {}).get("thinking_stage_count", 0) or 0) for x in turns),
        "behavioral_correctness_mean": statistics.mean(correctness) if correctness else 0.0,
        "behavioral_correctness_passes": sum(float(s) >= 0.75 for s in correctness),
        "llm_calls": int(usage.get("calls", 0) or 0),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5D real behavioral neural-feedback A/B probe")
    parser.add_argument("--trials", type=int, default=TRIALS)
    trials = max(1, int(parser.parse_args().trials))
    payload: Dict[str, Any] = {
        "experiment": "phase5d_real_behavioral_feedback_ab",
        "trials_per_case": trials,
        "A": "current_jarvis_with_thinking_control",
        "B": "current_jarvis_plus_phase5b_bounded_neural_feedback",
        "controller_scope": "brain.thinking_mode only",
        "controller_threshold": BoundedNeuralFeedbackController.THRESHOLD,
        "brain_authority_preserved": True,
        "neural_action_execution": False,
        "metrics_source": "deep_inspector._real_turn_metrics + persistent token ledger delta + real Groq provider timing metadata",
        "llm_usage_rule": "Only persistent successful provider response usage is counted; no token estimates are used.",
        "behavioral_oracle_rule": "Deterministic case-specific correctness checks; no evaluator LLM call is added.",
        "thinking_measurement_rule": "Authoritative Brain decision field `think` is mapped to thinking_used; legacy `thinking_used` is fallback only.",
        "experimental_budget_rule": "Harness raises per-turn call ceiling to at least 12 only to prevent the existing thinking budget gate from suppressing the controlled experiment; production defaults are untouched.",
        "results": [],
    }
    for case in CASES:
        entry = {
            "id": case["id"], "name": case["name"],
            "expected_thinking": case.get("expected_thinking"), "trials": [],
        }
        for trial in range(1, trials + 1):
            if trial % 2:
                a, b = run_isolated(case, False, trial, "A"), run_isolated(case, True, trial, "B")
            else:
                b, a = run_isolated(case, True, trial, "B"), run_isolated(case, False, trial, "A")
            aa, bb = aggregate(a), aggregate(b)
            entry["trials"].append({
                "trial": trial,
                "A": a,
                "B": b,
                "A_aggregate": aa,
                "B_aggregate": bb,
                "behavioral_delta": {
                    "thinking_used_delta_B_minus_A": bb["thinking_used_turns"] - aa["thinking_used_turns"],
                    "thinking_stage_delta_B_minus_A": bb["thinking_stage_count"] - aa["thinking_stage_count"],
                    "behavioral_correctness_delta_B_minus_A": round(bb["behavioral_correctness_mean"] - aa["behavioral_correctness_mean"], 3),
                    "behavioral_pass_delta_B_minus_A": bb["behavioral_correctness_passes"] - aa["behavioral_correctness_passes"],
                    "llm_calls_delta_B_minus_A": bb["llm_calls"] - aa["llm_calls"],
                    "prompt_tokens_delta_B_minus_A": bb["prompt_tokens"] - aa["prompt_tokens"],
                    "completion_tokens_delta_B_minus_A": bb["completion_tokens"] - aa["completion_tokens"],
                    "total_tokens_delta_B_minus_A": bb["total_tokens"] - aa["total_tokens"],
                    "provider_latency_delta_B_minus_A_ms": bb["provider_response_latency_ms"] - aa["provider_response_latency_ms"],
                    "latency_delta_B_minus_A_ms": bb["mean_latency_ms"] - aa["mean_latency_ms"],
                },
            })
            print(
                f"[{case['id']}] trial {trial}: "
                f"think A/B={aa['thinking_used_turns']}/{bb['thinking_used_turns']} "
                f"accuracy A/B={aa['behavioral_correctness_mean']:.2f}/{bb['behavioral_correctness_mean']:.2f} "
                f"LLM calls A/B={aa['llm_calls']}/{bb['llm_calls']} "
                f"tokens A/B={aa['total_tokens']}/{bb['total_tokens']} "
                f"provider latency A/B={aa['provider_response_latency_ms']:.1f}/{bb['provider_response_latency_ms']:.1f} ms "
                f"turn latency delta={bb['mean_latency_ms']-aa['mean_latency_ms']:+.2f} ms"
            )
        payload["results"].append(entry)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("RESULT:", OUT)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
