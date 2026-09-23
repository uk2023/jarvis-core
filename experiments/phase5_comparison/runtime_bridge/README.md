# Phase 5 Runtime Bridge

Connect Phase 5 A/B measurement to the **real Jarvis Brain runtime**.

A = fresh current Jarvis runtime.
B = fresh current Jarvis runtime + experimental neural layer in shadow mode.

The previous probe used `cli.process_query()` and could return `Engine Not Initialized in CLI Process.` This bridge now starts the actual organism with `start_jarvis()` and invokes the authoritative `BlueprintBrain.think_and_respond()` directly.

Rules:
- Existing Brain remains authoritative.
- Neural layer cannot generate or override responses.
- Neural layer cannot execute actions.
- Same test sequence is sent through A and B.
- A and B use fresh Jarvis instances so prior-run state does not contaminate the comparison.
- Capture real response latency, trace availability/stages, LLM-call/token evidence when exposed, response stability, and context carryover.
- Neural activity is measured after the real turn as shadow state; it is not fed back into routing or response generation yet.
- No improvement claim is allowed from shadow measurements alone.
- The next controlled experiment may enable a bounded feedback signal only after this real-runtime baseline is verified.
