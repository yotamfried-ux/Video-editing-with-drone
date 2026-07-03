# GAP-012 — Operator Smoke contract checks

Status: fixed by the Operator Smoke contract PR.

## Problem

The Operator Smoke workflow validation protected the workflow wiring, but it did not validate the smoke script contract itself.

That left a future risk where `scripts/operator_smoke.py` could change its URL normalization, JSON parsing, or report PASS/FAIL behavior without a local CI check catching the regression.

## Repair

- Added `scripts/test_operator_smoke_contract.py`.
- Added the contract check to `.github/workflows/operator-smoke-check.yml`.
- Expanded workflow path filters to run when the smoke script or its contract test changes.

## Result

Operator Smoke now has a deploy-free CI check for:

- JSON parse behavior
- base URL normalization
- PASS report rendering
- FAIL report rendering

This closes a non-deploy validation gap and does not require Vercel.
