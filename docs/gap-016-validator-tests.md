# GAP-016 — Operator Smoke validator tests

Status: covered by the Operator Smoke validator tests PR.

## Scope

The workflow validator now exposes a reusable `validate(workflow_text)` function.

## Change

A deploy-free test now checks both the current workflow and expected failure cases for weakened workflow wiring.

## Result

The validator is now protected by its own contract test.
