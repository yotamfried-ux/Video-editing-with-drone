# GAP-014 — Operator Smoke CLI contract

Status: covered by the Operator Smoke CLI contract PR.

## Scope

The workflow runs `scripts/operator_smoke.py` as a command line program and relies on two outcomes:

- the process status
- the generated markdown report

## Change

`script/test_operator_smoke_contract.py` now invokes `operator_smoke.main()` with temporary report files and mocked request behavior.

## Result

The deploy-free check now covers command line argument parsing, report file creation, and report result content.
