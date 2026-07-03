# Operator Smoke workflow hardening

The Operator Smoke workflow must preserve optional CLI arguments exactly.

Required invariant:

- use a bash array for optional arguments
- invoke the script with `"${args[@]}"`
- fail fast when `OPERATOR_SECRET` is missing
- keep `scripts/validate_operator_smoke_workflow.py` passing
