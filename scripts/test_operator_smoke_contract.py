#!/usr/bin/env python3
from __future__ import annotations

import operator_smoke


def main() -> int:
    data = operator_smoke.parse('{"ok": true}')
    if data.get('ok') is not True:
        raise SystemExit('parse failed')

    wrapped = operator_smoke.parse('[1, 2]')
    if 'value' not in wrapped:
        raise SystemExit('non object json was not wrapped')

    url = operator_smoke.base('example.com/')
    if url != 'https://example.com':
        raise SystemExit('base URL normalization failed')

    results = [
        {'name': 'alpha', 'status': 'PASS', 'detail': 'ok'},
        {'name': 'beta', 'status': 'SKIP', 'detail': 'not requested'},
    ]
    report = operator_smoke.render(results, 'example.com')
    if 'Result: PASS' not in report:
        raise SystemExit('pass report failed')

    failed = [{'name': 'alpha', 'status': 'FAIL', 'detail': 'bad'}]
    fail_report = operator_smoke.render(failed, 'example.com')
    if 'Result: FAIL' not in fail_report:
        raise SystemExit('fail report failed')

    print('Operator Smoke contract checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
