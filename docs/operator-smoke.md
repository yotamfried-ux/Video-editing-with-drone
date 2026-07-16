# Operator smoke loop

This document defines the repeatable validation loop for GAP-011.

## What to run

Use the smoke harness:

```bash
python scripts/operator_smoke.py --api-base-url https://example.com --operator-secret "$OPERATOR_SECRET" --report-path operator-smoke-report.md
```

Or run the manual workflow:

```text
Actions -> Operator Smoke -> Run workflow
```

## Default checks

The default run is read-only and checks:

- missing operator header is rejected
- operator pipeline status endpoint responds
- operator pipeline run history endpoint responds
- operator delivery history endpoint responds
- operator discover diagnostics endpoint responds
- public sessions endpoint responds
- upload footage, send-to-re-edit, approve draft, and reset-and-rerun each
  reject an unauthenticated request (auth-only checks — see below)

## Why Upload/Reset/Send-to-re-edit/Approve stay functionally manual

GAP-011 originally listed six critical operator actions needing smoke
coverage: Run pipeline, Upload footage, Reset and rerun, Send to re-edit,
Approve draft, and Delivery to Discover. Run pipeline and Delivery/discover
diagnostics are covered above (Run pipeline behind `--run-pipeline`). The
remaining four are **not** functionally automated by default, and this is a
deliberate decision, not an oversight: every one of them dispatches a real,
mutating GitHub Actions run or moves real files/state against whatever
environment `--api-base-url` points at (uploading real footage costs real
Gemini/Actions usage; reset deletes REVIEW drafts and restores
PROCESSED→RAW; send-to-re-edit and approve mutate real draft/delivery state).
There is no safe dry-run mode for any of them in the web-api routes today, so
a scheduled or frequently-run smoke check must not call their real behavior.

What the harness *does* check for all four, safely and by default: each
route's `requireOperator(req)` auth check runs before any rate-limiting or
mutation, so an unauthenticated request is rejected with zero side effects.
This is real regression coverage — it catches an accidentally-unprotected
route — without exercising the destructive path. Full functional smoke
testing of these four remains a manual procedure:
`docs/upload-to-run-smoke.md`, `docs/qa-reedit-migration-smoke.md`. Follow
those during a controlled verification window, on an environment where the
destructive side effects are acceptable.

## Optional checks

These checks are disabled by default and must be requested explicitly:

- `--run-pipeline` for the real pipeline dispatch path
- `--checkout-token <token>` for a smoke checkout path

Use optional checks only during a controlled verification window.

## Pass criteria

A smoke run passes when all required checks are PASS. Skipped optional checks are acceptable only when the run is intentionally read-only.

## Failure handling

A failed smoke run blocks operational readiness for that environment.

1. Open `operator-smoke-report.md`.
2. Find the first FAIL row.
3. Fix the route, configuration, external service, or data setup.
4. Re-run the smoke loop.
5. Attach the passing report to the PR, issue, or release note.

## Related docs

- `docs/upload-to-run-smoke.md`
- `docs/discover-reels-smoke-loop.md`
