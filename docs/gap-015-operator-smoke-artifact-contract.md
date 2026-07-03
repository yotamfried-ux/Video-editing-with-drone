# GAP-015 — Operator Smoke artifact contract

Status: fixed by the Operator Smoke artifact contract PR.

## Problem

The Operator Smoke workflow already uploaded `operator-smoke-report.md`, but the workflow validator did not enforce the artifact contract.

A future change could remove `actions/upload-artifact`, remove `if: always()`, or change the report path, and the lightweight workflow validator would still pass.

## Repair

- Extended `scripts/validate_operator_smoke_workflow.py` to require:
  - `actions/upload-artifact@v4`
  - `if: always()`
  - artifact name `operator-smoke-report`
  - artifact path `operator-smoke-report.md`
- Added a count check that confirms the report path appears in both write and upload contexts.

## Result

The smoke workflow now has a deploy-free guard for preserving the operator smoke report artifact even when the smoke run fails.
