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
