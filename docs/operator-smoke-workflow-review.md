# Operator Smoke workflow review note

Reviewers should check that `.github/workflows/operator-smoke.yml` does not build optional arguments with a single string variable.

The expected pattern is a bash array plus `scripts/validate_operator_smoke_workflow.py`.
