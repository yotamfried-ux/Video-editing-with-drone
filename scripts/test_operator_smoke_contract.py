#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

import operator_smoke
import test_batch_scope_contract


def fake_req(root: str, path: str, token: str = '', method: str = 'GET') -> Tuple[int, Dict[str, Any], str]:
    if path == '/api/operator/pipeline/status' and not token:
        return 401, {'error': 'Unauthorized'}, root + path
    if path == '/api/operator/pipeline/status' and token:
        return 200, {'status': 'ready'}, root + path
    if path.startswith('/api/operator/pipeline/runs'):
        return 200, {'runs': []}, root + path
    if path.startswith('/api/operator/delivery-status'):
        return 200, {'runs': []}, root + path
    if path == '/api/operator/discover-diagnostics':
        return 200, {'ok': True, 'reels': [], 'missingExpiryCount': 0}, root + path
    if path.startswith('/api/sessions?'):
        return 200, {'sessions': []}, root + path
    if path == '/api/operator/pipeline/start' and method == 'POST':
        return 200, {'pipeline_run_id': 'run_123'}, root + path
    if path.startswith('/api/checkout/') and method == 'POST':
        return 200, {'checkout_url': 'https://checkout.example'}, root + path
    return 404, {'error': 'not found'}, root + path


def failing_req(root: str, path: str, token: str = '', method: str = 'GET') -> Tuple[int, Dict[str, Any], str]:
    if path.startswith('/api/operator/pipeline/runs'):
        return 500, {'error': 'boom'}, root + path
    return fake_req(root, path, token, method)


def validate_helpers() -> None:
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


def validate_full_smoke_contract() -> None:
    original_req = operator_smoke.req
    operator_smoke.req = fake_req
    try:
        args = argparse.Namespace(
            api_base_url='example.com',
            operator_secret='secret',
            sessions_sport='stripe_test',
            run_pipeline=True,
            checkout_token='checkout token with spaces',
            report_path='',
        )
        results = operator_smoke.smoke(args)
    finally:
        operator_smoke.req = original_req

    expected_names = {
        'operator auth rejects missing header',
        'operator pipeline status',
        'pipeline run history',
        'delivery run history',
        'discover diagnostics',
        'public discover sessions',
        'trigger pipeline run',
        'checkout creation',
    }
    names = {item['name'] for item in results}
    if names != expected_names:
        raise SystemExit(f'unexpected smoke checks: {sorted(names)}')

    statuses = {item['status'] for item in results}
    if statuses != {'PASS'}:
        raise SystemExit(f'unexpected smoke statuses: {sorted(statuses)}')

    report = operator_smoke.render(results, 'example.com')
    if '| checkout creation | PASS |' not in report:
        raise SystemExit('checkout row missing from full smoke report')
    if '| trigger pipeline run | PASS |' not in report:
        raise SystemExit('pipeline trigger row missing from full smoke report')
    if 'Result: PASS' not in report:
        raise SystemExit('full smoke report did not pass')


def run_cli_with(req_impl, report_path: Path) -> int:
    original_req = operator_smoke.req
    original_argv = sys.argv[:]
    operator_smoke.req = req_impl
    sys.argv = [
        'operator_smoke.py',
        '--api-base-url',
        'example.com',
        '--operator-secret',
        'secret',
        '--sessions-sport',
        'stripe_test',
        '--run-pipeline',
        '--checkout-token',
        'checkout token with spaces',
        '--report-path',
        str(report_path),
    ]
    try:
        return operator_smoke.main()
    finally:
        operator_smoke.req = original_req
        sys.argv = original_argv


def validate_cli_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pass_report = Path(tmp) / 'pass-report.md'
        pass_code = run_cli_with(fake_req, pass_report)
        if pass_code != 0:
            raise SystemExit(f'expected CLI pass exit code 0, got {pass_code}')
        pass_text = pass_report.read_text(encoding='utf-8')
        if 'Result: PASS' not in pass_text:
            raise SystemExit('CLI pass report missing PASS result')

        fail_report = Path(tmp) / 'fail-report.md'
        fail_code = run_cli_with(failing_req, fail_report)
        if fail_code != 1:
            raise SystemExit(f'expected CLI fail exit code 1, got {fail_code}')
        fail_text = fail_report.read_text(encoding='utf-8')
        if 'Result: FAIL' not in fail_text:
            raise SystemExit('CLI fail report missing FAIL result')
        if '| pipeline run history | FAIL |' not in fail_text:
            raise SystemExit('CLI fail report missing failed check row')


def main() -> int:
    validate_helpers()
    validate_full_smoke_contract()
    validate_cli_contract()
    test_batch_scope_contract.main()
    print('Operator Smoke contract checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
