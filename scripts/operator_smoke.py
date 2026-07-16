#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def base(url: str) -> str:
    url = url.strip().rstrip('/')
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    return url


def parse(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw or '{}')
        return data if isinstance(data, dict) else {'value': data}
    except json.JSONDecodeError:
        return {'raw': raw[:300]}


def req(root: str, path: str, token: str = '', method: str = 'GET') -> Tuple[int, Dict[str, Any], str]:
    url = base(root) + path
    headers = {'Accept': 'application/json'}
    if token:
        headers['x-operator-secret'] = token
    request = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as res:
            return res.status, parse(res.read().decode('utf-8')), url
    except urllib.error.HTTPError as exc:
        return exc.code, parse(exc.read().decode('utf-8')), url


def check(name: str, ok: bool, detail: str) -> Dict[str, str]:
    return {'name': name, 'status': 'PASS' if ok else 'FAIL', 'detail': detail}


def smoke(args: argparse.Namespace) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    status, data, _ = req(args.api_base_url, '/api/operator/pipeline/status')
    out.append(check('operator auth rejects missing header', status in (401, 403), f'status={status}; keys={sorted(data.keys())}'))

    status, data, _ = req(args.api_base_url, '/api/operator/pipeline/status', args.operator_secret)
    out.append(check('operator pipeline status', status == 200 and 'status' in data, f'status={status}; keys={sorted(data.keys())}'))

    status, data, _ = req(args.api_base_url, '/api/operator/pipeline/runs?limit=12', args.operator_secret)
    out.append(check('pipeline run history', status == 200 and isinstance(data.get('runs'), list), f"status={status}; runs={len(data.get('runs', [])) if isinstance(data.get('runs'), list) else 'missing'}"))

    status, data, _ = req(args.api_base_url, '/api/operator/delivery-status?limit=8', args.operator_secret)
    out.append(check('delivery run history', status == 200 and isinstance(data.get('runs'), list), f"status={status}; runs={len(data.get('runs', [])) if isinstance(data.get('runs'), list) else 'missing'}"))

    status, data, _ = req(args.api_base_url, '/api/operator/discover-diagnostics', args.operator_secret)
    out.append(check('discover diagnostics', status == 200 and data.get('ok') is True and isinstance(data.get('reels'), list), f"status={status}; ok={data.get('ok')}; missingExpiryCount={data.get('missingExpiryCount')}"))

    sport = urllib.parse.urlencode({'sport': args.sessions_sport})
    status, data, _ = req(args.api_base_url, f'/api/sessions?{sport}')
    out.append(check('public discover sessions', status == 200, f'status={status}; sport={args.sessions_sport}; keys={sorted(data.keys())}'))

    # Upload footage, Reset/rerun, Send-to-re-edit, and Approve draft each dispatch a
    # real, mutating GitHub Actions run or move real files/state, so there is no safe
    # way to smoke-test their actual behavior against a live environment by default
    # (see docs/operator-smoke.md). Every one of these routes checks operator auth
    # before doing anything mutating, so an unauthenticated request is a safe,
    # zero-side-effect regression check that the route is not accidentally left open.
    for name, path in (
        ('upload footage auth', '/api/operator/upload'),
        ('send-to-re-edit auth', '/api/operator/reprocess'),
        ('approve draft auth', '/api/operator/drafts/approve'),
        ('reset and rerun auth', '/api/operator/pipeline/reset'),
    ):
        status, data, _ = req(args.api_base_url, path, method='POST')
        out.append(check(f'{name} rejects missing header', status in (401, 403), f'status={status}; keys={sorted(data.keys())}'))

    if args.run_pipeline:
        status, data, _ = req(args.api_base_url, '/api/operator/pipeline/start', args.operator_secret, 'POST')
        out.append(check('trigger pipeline run', status == 200 and isinstance(data.get('pipeline_run_id'), str), f"status={status}; pipeline_run_id={data.get('pipeline_run_id')}"))
    else:
        out.append({'name': 'trigger pipeline run', 'status': 'SKIP', 'detail': 'not requested'})

    if args.checkout_token:
        token = urllib.parse.quote(args.checkout_token, safe='')
        status, data, _ = req(args.api_base_url, f'/api/checkout/{token}', method='POST')
        out.append(check('checkout creation', status == 200 and isinstance(data.get('checkout_url'), str), f"status={status}; has_checkout_url={isinstance(data.get('checkout_url'), str)}"))
    else:
        out.append({'name': 'checkout creation', 'status': 'SKIP', 'detail': 'not requested'})

    return out


def render(results: List[Dict[str, str]], api_base_url: str) -> str:
    lines = ['# Operator smoke report', '', f'Generated: {datetime.now(timezone.utc).isoformat()}', f'API: `{base(api_base_url)}`', '', '| Check | Result | Detail |', '|---|---|---|']
    for result in results:
        detail = result['detail'].replace('|', '\\|')
        lines.append(f"| {result['name']} | {result['status']} | {detail} |")
    failed = [r for r in results if r['status'] == 'FAIL']
    lines += ['', 'Result: ' + ('FAIL' if failed else 'PASS')]
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-base-url', required=True)
    parser.add_argument('--operator-secret', required=True)
    parser.add_argument('--sessions-sport', default='stripe_test')
    parser.add_argument('--run-pipeline', action='store_true')
    parser.add_argument('--checkout-token', default='')
    parser.add_argument('--report-path', default='')
    args = parser.parse_args()

    results = smoke(args)
    report = render(results, args.api_base_url)
    print(report)
    if args.report_path:
        with open(args.report_path, 'w', encoding='utf-8') as handle:
            handle.write(report)
    return 1 if any(r['status'] == 'FAIL' for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
