#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

workflow = Path('.github/workflows/operator-smoke.yml').read_text(encoding='utf-8')

required = [
    'args=',
    'python scripts/operator_smoke.py "${args[@]}"',
    'OPERATOR_SECRET repository secret is required',
    'shell: bash',
    'actions/upload-artifact@v4',
    'if: always()',
    'name: operator-smoke-report',
    'path: operator-smoke-report.md',
]

missing = [item for item in required if item not in workflow]

if missing:
    raise SystemExit('Operator Smoke workflow validation failed. Missing: ' + ', '.join(missing))

if 'ARGS=' in workflow:
    raise SystemExit('Operator Smoke workflow must not use string-based ARGS construction')

if workflow.count('operator-smoke-report.md') < 2:
    raise SystemExit('Operator Smoke workflow must write and upload operator-smoke-report.md')

print('Operator Smoke workflow validation passed')
