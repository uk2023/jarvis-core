# JARVIS Contracts

This directory is the single boundary-contract layer for the JARVIS architecture.

## Responsibility

- Define stable input/output contracts for each architecture layer.
- Keep implementations independent from the transport shape.
- Enforce contracts through one central validator.
- Provide local smoke tests for registry completeness and layer wiring.

It does **not** implement perception, semantic understanding, cognition, routing,
brain decisions, learning, or evolution.

## Files

- `schemas.py` — contract definitions only.
- `validator.py` — the central enforcement point.
- `test_contracts.py` — dependency-free local smoke tests.

## Current layer contracts

Each layer has both `<layer>.input` and `<layer>.output` contracts:

`perception` → `semantic_understanding` → `cognition` → `cognitive_router` →
`brain` → `experience` → `learning` → `memory` → `self_evaluation` → `evolution`

## Local wiring/test commands

From the repository root:

```bash
git pull origin brian-idle
python3 -m core.contracts.test_contracts
```

Expected result includes:

```text
PASS: 20 JARVIS input/output contracts validated
PASS: perception -> semantic_understanding -> cognition wiring validated
PASS: invalid payload rejection validated
```

## Integration rule

A layer should validate its input at the boundary and validate its output before
handing the result to the next layer:

```python
from core.contracts import validate_input, validate_output

incoming = validate_input("semantic_understanding", incoming_payload)
result = implementation(incoming)
outgoing = validate_output("semantic_understanding", result)
```

The contract layer is infrastructure. It should not contain regex parsing,
LLM calls, knowledge-building logic, routing decisions, or action execution.
