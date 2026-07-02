# GAP-011 — Real end-to-end validation

Status: improved by the operator smoke harness PR.

## Problem

The project had code review and deployment checks, but no repeatable operator-level smoke gate that produced a durable pass/fail report for the deployed environment.

## Repair

- Added `scripts/operator_smoke.py`.
- Added `.github/workflows/operator-smoke.yml`.
- Added `docs/operator-smoke.md`.

## Default proof

The default run is read-only and verifies:

- missing operator header is rejected
- operator pipeline status endpoint works
- operator pipeline history endpoint works
- operator delivery history endpoint works
- operator Discover diagnostics endpoint works
- public sessions endpoint works

## Optional proof

Optional flags can verify write paths during a controlled validation window:

- `--run-pipeline`
- `--checkout-token <token>`

## Remaining work

This creates the repeatable smoke gate. Full environment validation still requires attaching a passing smoke report to the relevant PR, release, or issue.
