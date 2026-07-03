# GAP-011 smoke workflow validation

Status: fixed by the Operator Smoke workflow hardening PR.

The smoke workflow now validates its own wiring before running.

Validation command:

```bash
python scripts/validate_operator_smoke_workflow.py
```

The validator fails if the workflow returns to string-based optional argument construction or loses the `OPERATOR_SECRET` guard.
