# Operator Smoke workflow validation command

Run this before merging changes to Operator Smoke wiring:

```bash
python scripts/validate_operator_smoke_workflow.py
```

Expected output:

```text
Operator Smoke workflow validation passed
```

This check guards against returning to fragile string-based optional argument construction in `.github/workflows/operator-smoke.yml`.
