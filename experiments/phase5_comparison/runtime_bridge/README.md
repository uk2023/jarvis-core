# Phase 5 Runtime Bridge

Connect Phase 5 A/B measurement to the real Jarvis runtime.

A = real current Jarvis workflow.
B = same workflow + experimental neural state/feedback observation.

Rules:
- Existing Brain remains authoritative.
- Neural layer cannot generate or override responses.
- Neural layer cannot execute actions.
- Same test input must be sent through A and B.
- Capture real latency, LLM calls, tokens, context carryover,
  interruption handling, action result, and response stability.
- If neural layer adds no measurable benefit, keep it experimental.
