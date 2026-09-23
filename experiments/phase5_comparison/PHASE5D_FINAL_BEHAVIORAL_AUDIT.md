# Phase 5D — Final FruitFly Behavioral Audit

## Purpose

This is the final A/B audit for the FruitFly / Phase-5B neural-feedback layer.
The only question being decided is:

> Does bounded neural feedback improve Jarvis behavior compared with the same Jarvis without FruitFly?

No provider-performance conclusion is part of this audit.

## Experimental control

- A = same Jarvis with FruitFly/neural feedback OFF.
- B = same Jarvis with FruitFly/neural feedback ON.
- Same Jarvis code, model, identity, prompts, conversation context, tools/capabilities, and runtime environment.
- Brain remains authoritative.
- Neural action execution remains disabled in this behavioral experiment.
- No evaluator LLM is introduced.
- Deterministic checks are used where an exact oracle is possible.

## Evidence sources

The audit combines the existing Phase-5D runtime probe with the workflow-level information already exposed by Jarvis Deep Inspector. The workflow is treated as the evidence path:

`input → perception → cognition → thinking decision → routing → FruitFly feedback → brain decision → action/tool decision → response → post-response evaluation`

Existing usage instrumentation is retained:

- LLM call count
- prompt tokens
- completion tokens
- total tokens
- thinking activation
- thinking stage count
- turn latency
- errors/failures

Provider-specific latency, TPM, key rotation, and per-key allocation are explicitly excluded from the FruitFly decision gate. They are provider/orchestration concerns, not behavioral evidence.

## Behavioral dimensions

The final audit must report A/B and B-A delta for:

1. Behavioral correctness
2. Context retention / exact carryover
3. Reasoning correctness and required reasoning structure
4. Instruction following
5. Response relevance/appropriateness
6. Hallucination or unsupported-claim/error behavior
7. Execution-claim honesty
8. Thinking activation
9. Thinking stages
10. Deep-Inspector workflow/decision-path evidence
11. LLM calls and actual observed tokens
12. Turn latency
13. Failures/recovery

Where a dimension is not applicable to a case, it is marked N/A rather than fabricated.

## Case coverage

- T01 — simple/control: verifies normal conversational behavior and that FruitFly does not perturb trivial turns.
- T02 — context behavior: exact context carryover.
- T03 — reasoning behavior: steps, trade-offs, verification, and no false execution claim.
- Final audit coverage also reserves cases for instruction conflict, multi-step planning, correction/recovery, hallucination traps, and identity/behavior consistency when the final harness supports them.

## Current Phase-5D evidence already observed

The existing 5-trial-per-case run contains 15 paired A/B trials. Its aggregate behavioral-correctness delta is approximately **+0.003**, while total-token delta is approximately **+95.6 tokens** and mean turn-latency delta is approximately **-513 ms**.

Those results do **not** establish a meaningful behavioral improvement by themselves. T02/T03 show mixed per-trial effects, including positive, neutral, and negative B-A deltas.

## Decision rule

FruitFly is considered behaviorally useful only when the final repeated A/B audit demonstrates a meaningful, reproducible improvement in behavioral dimensions. Lower latency or lower token usage alone is never sufficient.

The conclusion must be one of:

- **BENEFIT DEMONSTRATED** — behavioral improvements are clear and reproducible across the covered cases.
- **NO MEANINGFUL BENEFIT DEMONSTRATED** — B does not show a meaningful reproducible behavioral advantage.
- **BEHAVIORAL REGRESSION** — B causes a clear reproducible deterioration.

No provider metric may change this conclusion.

## Finality

After the final audit run and conclusion, do not create another evidence loop for Phase 5D. Proceed to verification, full fixes, commit, repository sync, and the documented local Python 3 test command.
