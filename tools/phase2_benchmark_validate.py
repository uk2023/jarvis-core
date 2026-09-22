#!/usr/bin/env python3
"""Validate the fixed Phase 2 behavioral benchmark without changing Jarvis."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "tools" / "phase2_behavioral_benchmark.json"

def main() -> int:
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tests = data.get("tests", [])
    ids = [t.get("id") for t in tests if isinstance(t, dict)]
    required = {"single_turn", "context_carryover", "correction_carryover",
                "interruption_recovery", "memory_retrieval", "action_success",
                "action_failure_recovery", "state_stability", "llm_fallback", "multistep"}
    categories = {t.get("category") for t in tests if isinstance(t, dict)}
    assert len(tests) == 10, f"expected 10 tests, got {len(tests)}"
    assert len(ids) == len(set(ids)), "duplicate benchmark IDs"
    assert all(isinstance(x, str) and x for x in ids), "missing benchmark ID"
    assert required <= categories, f"missing categories: {sorted(required - categories)}"
    assert len(data.get("metrics", [])) >= 6, "benchmark metrics are incomplete"
    print("PHASE 2 BEHAVIORAL BENCHMARK: PASS")
    print(f"version: {data.get('version')}")
    print(f"tests: {len(tests)}")
    print("IDs: " + ", ".join(ids))
    print("The benchmark is fixed for A/B runs; this command does not claim live performance.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
