# GAP-013 — Full Operator Smoke contract coverage

Status: fixed by the full Operator Smoke contract PR.

## Problem

GAP-012 added deploy-free checks for helper behavior in `scripts/operator_smoke.py`, but the test still did not execute the `smoke()` function itself.

That left a future risk where the list of smoke checks, optional `--run-pipeline` handling, optional checkout handling, or PASS/FAIL report rows could regress without a deploy-free test catching it.

## Repair

- Extended `scripts/test_operator_smoke_contract.py` with a fake HTTP client.
- Executed `operator_smoke.smoke()` with both optional paths enabled:
  - pipeline trigger
  - checkout creation
- Asserted that the expected eight smoke checks are present.
- Asserted that all fake-path checks return PASS.
- Asserted that the rendered report includes the pipeline and checkout PASS rows.

## Result

Operator Smoke now has a fuller deploy-free contract test for the actual smoke flow, not only helper functions.

This keeps the manual smoke workflow safer while Vercel deployment validation remains reserved for app changes.
