# Phase 5 Runtime Bridge

Connect Phase 5 A/B measurement to the **real Jarvis Brain runtime**.

A = fresh current Jarvis runtime.
B = fresh current Jarvis runtime + experimental neural layer.

The previous probe used `cli.process_query()` and could return `Engine Not Initialized in CLI Process.` The bridge now starts the actual organism with `start_jarvis()` and invokes the authoritative Brain directly.

## Phase 5 shadow baseline

`real_runtime_probe.py` keeps the neural layer shadow-only.

Rules:
- Existing Brain remains authoritative.
- Neural layer cannot generate or override responses.
- Neural layer cannot execute actions.
- Same test sequence is sent through A and B.
- A and B use fresh Jarvis instances so prior-run state does not contaminate the comparison.
- Capture real response latency, trace availability/stages, LLM-call/token evidence when exposed, response stability, and context carryover.
- Neural activity is measured after the real turn as shadow state; it is not fed back into routing or response generation.
- No improvement claim is allowed from shadow measurements alone.

## Phase 5B bounded feedback

`phase5b_feedback_probe.py` is the next controlled experiment after the verified shadow baseline.

The Phase-4 connectome state is connected to **one existing Brain control only**: `brain.thinking_mode`. The neural layer may turn the existing extended-thinking path on/off from a deterministic activity threshold; it does not select a route, generate text, execute a skill, or replace Brain.

Controller boundary:
- `mean_activity < 0.020` -> `thinking_mode = off`
- `mean_activity >= 0.020` -> `thinking_mode = on`

This threshold is an experimental controller parameter, not a biological claim.

Run from the repository root:

```bash
python3 experiments/phase5_comparison/runtime_bridge/phase5b_feedback_probe.py
python3 experiments/phase5_comparison/phase5b_final_report.py
```

The same T01/T02/T03 tests are repeated for A and B. The machine-readable result is `runtime_bridge/phase5b_feedback_probe_result.json`; the human-readable report is `PHASE5B_FINAL_REPORT.txt`.

Phase 5B decision gate: keep the feedback controller only if the real A/B measurements show a measurable target benefit that justifies its added latency/LLM cost. Otherwise modify or discard it. Do not scale it based on neural activity alone.
