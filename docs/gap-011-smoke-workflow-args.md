# GAP-011 follow-up — Operator Smoke workflow args

Status: fixed by the Operator Smoke workflow hardening PR.

## Problem

The Operator Smoke workflow built optional CLI arguments in a shell string named `ARGS`.

That is fragile because quote characters produced by variable expansion are not treated as shell quoting. A checkout token could be passed with literal quote characters and fail the smoke check.

The workflow also did not fail early when the `OPERATOR_SECRET` repository secret was missing.

Validation also exposed a Vercel quota issue: docs and workflow changes were still triggering Vercel builds even when `web-api` was unchanged.

## Repair

- Replaced the string-based `ARGS` construction with a bash array.
- Passed the array using `"${args[@]}"` so each argument is preserved exactly.
- Added a fail-fast guard for a missing `OPERATOR_SECRET` repository secret.
- Added `scripts/validate_operator_smoke_workflow.py`.
- Added `.github/workflows/operator-smoke-check.yml` so future PRs touching the smoke workflow validate the wiring.
- Added a validation step inside `Operator Smoke` before the actual smoke run.
- Added `ignoreCommand` to `web-api/vercel.json` so Vercel skips builds when the `web-api` project root is unchanged.

## Result

The manual Operator Smoke workflow can now safely pass optional flags such as:

- `--run-pipeline`
- `--checkout-token <token>`

without argument splitting or literal quote bugs.

The workflow also fails with a clear message when `OPERATOR_SECRET` is not configured.

Vercel should no longer spend build quota on PRs that do not change the deployed `web-api` app.
