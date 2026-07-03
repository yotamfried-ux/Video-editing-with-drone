#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import validate_operator_smoke_workflow as validator


def expect_failure(workflow: str, expected: str) -> None:
    try:
        validator.validate(workflow)
    except SystemExit as exc:
        message = str(exc)
        if expected not in message:
            raise SystemExit(f'expected failure containing {expected!r}, got {message!r}')
        return
    raise SystemExit(f'expected validator failure containing {expected!r}')


def main() -> int:
    workflow = Path('.github/workflows/operator-smoke.yml').read_text(encoding='utf-8')
    validator.validate(workflow)

    expect_failure(
        workflow.replace('actions/upload-artifact@v4', 'actions/upload-artifact@v3'),
        'actions/upload-artifact@v4',
    )
    expect_failure(
        workflow.replace('if: always()', 'if: success()'),
        'if: always()',
    )
    expect_failure(
        workflow.replace('args=(', 'ARGS=""'),
        'args=(',
    )
    expect_failure(
        workflow.replace('operator-smoke-report.md', 'smoke.md', 1),
        'write and upload operator-smoke-report.md',
    )

    print('Operator Smoke workflow validator contract checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
