# GAP-011 follow-up — Operator Smoke workflow args

Status: fixed by the Operator Smoke workflow hardening PR.

## Problem

The Operator Smoke workflow built optional CLI arguments in a shell string named `ARGS`.

That is fragile because quote characters produced by variable expansion are not treated as shell quoting. A checkout token could be passed with literal quote characters and fail the smoke check.

The workflow also did not fail early when the `OPERATOR_SECRET` repository secret was missing.

## Repair

- Replaced the string-based `ARGS` construction with a bash array.
- Passed the array using `"${args[@]}"` so each argument is preserved exactly.
- Added a fail-fast guard for a missing `OPERATOR_SECRET` repository secret.

## Result

The manual Operator Smoke workflow can now safely pass optional flags such as:

- `--run-pipeline`
- `--checkout-token <token>`

without argument splitting or literal quote bugs.
