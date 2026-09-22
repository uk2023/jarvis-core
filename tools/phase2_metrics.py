#!/usr/bin/env python3
"""Phase 2 baseline metrics harness for JARVIS-NEURAL.

This is deliberately isolated from production cognition code. It provides:
1) a deterministic offline functional-regression score using the existing
   end-to-end scenario suite;
2) optional aggregation of live JSONL trace records exported by JARVIS.

It does not modify Jarvis behavior, memory, provider configuration, or token
budgets. Live on-device latency/interruption measurements must be collected
on the target Android/PRoot runtime because that environment is part of the
measurement itself.

Usage:
    python3 tools/phase2_metrics.py
    python3 tools/phase2_metrics.py --trace runtime/trace_log.jsonl
    python3 tools/phase2_metrics.py --trace runtime/trace_log.jsonl --json-out phase2_baseline.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "tests" / "test_e2e_scenarios.py"


def _percent(n: int, d: int) -> float | None:
    return round((100.0 * n / d), 2) if d else None


def run_offline_regression(timeout: float = 180.0) -> Dict[str, Any]:
    """Run the existing deterministic E2E scenario suite and measure it."""
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(SCENARIO)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        proc = None
        timed_out = True
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
    else:
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

    elapsed = time.perf_counter() - started
    passed = len(re.findall(r"✓ PASS", stdout))
    failed = len(re.findall(r"✗ FAIL", stdout))
    # The suite can be run in a terminal where ANSI escapes are present; the
    # regex above intentionally keys only on the stable PASS/FAIL text.
    total = passed + failed
    return {
        "suite": str(SCENARIO.relative_to(ROOT)),
        "elapsed_seconds": round(elapsed, 4),
        "passed": passed,
        "failed": failed,
        "total": total,
        "functional_accuracy_percent": _percent(passed, total),
        "return_code": None if proc is None else proc.returncode,
        "timed_out": timed_out,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def _records_from_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                yield item


def aggregate_live_records(path: Path) -> Dict[str, Any]:
    """Aggregate common timestamp/call/token fields without assuming one schema.

    Supported latency pairs:
      request_start/request_end
      start_timestamp/end_timestamp
      start/end

    Supported call counters:
      llm_call, llm_calls, purpose=chat/generate, event names containing
      llm+call.

    Token fields:
      prompt_tokens, completion_tokens, total_tokens.
    """
    records = list(_records_from_jsonl(path))
    latencies: List[float] = []
    llm_calls = 0
    tokens = Counter()
    event_names = Counter()

    for record in records:
        name = str(record.get("event") or record.get("event_name") or record.get("name") or "").lower()
        event_names[name] += 1

        pairs = (
            (record.get("request_start"), record.get("request_end")),
            (record.get("start_timestamp"), record.get("end_timestamp")),
            (record.get("start"), record.get("end")),
        )
        for start, end in pairs:
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
                latencies.append(float(end - start))
                break

        purpose = str(record.get("purpose", "")).lower()
        if (
            record.get("llm_call") is True
            or isinstance(record.get("llm_calls"), (int, float))
            or "llm" in name and "call" in name
            or purpose in {"chat", "generate", "llm"}
        ):
            value = record.get("llm_calls", 1)
            llm_calls += int(value) if isinstance(value, (int, float)) else 1

        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = record.get(key)
            if isinstance(value, (int, float)):
                tokens[key] += value

    return {
        "source": str(path),
        "records_read": len(records),
        "latency_samples": len(latencies),
        "latency_seconds_mean": round(mean(latencies), 4) if latencies else None,
        "latency_seconds_median": round(median(latencies), 4) if latencies else None,
        "latency_seconds_min": round(min(latencies), 4) if latencies else None,
        "latency_seconds_max": round(max(latencies), 4) if latencies else None,
        "llm_calls": llm_calls,
        "prompt_tokens": int(tokens["prompt_tokens"]),
        "completion_tokens": int(tokens["completion_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "event_counts": dict(event_names),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS Phase 2 metrics harness")
    parser.add_argument("--trace", type=Path, help="optional JSONL runtime trace to aggregate")
    parser.add_argument("--json-out", type=Path, help="optional JSON report output")
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "phase": "2",
        "branch": "jarvis-neural",
        "generated_at": time.time(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "offline_regression": run_offline_regression(),
        "live_trace": None,
        "status": "offline_regression_collected",
    }

    if args.trace:
        if not args.trace.is_absolute():
            args.trace = ROOT / args.trace
        if not args.trace.exists():
            parser.error(f"trace file does not exist: {args.trace}")
        report["live_trace"] = aggregate_live_records(args.trace)
        report["status"] = "baseline_metrics_collected"

    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)

    if args.json_out:
        output = args.json_out if args.json_out.is_absolute() else ROOT / args.json_out
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote: {output}")

    # A failed scenario suite is a measurement result, not a harness crash.
    # Return 0 so the report is still generated and can be inspected.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
