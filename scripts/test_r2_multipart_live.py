#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError

MIB = 1024 * 1024
TOTAL_BYTES = 17 * MIB + 123
TRUNCATED_BYTES = b'truncated-single-put'
TIMEOUT = 60


def required(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'{name} is required for the live R2 integration test')
    return value


def endpoint() -> str:
    explicit = os.environ.get('R2_ENDPOINT_URL', '').strip().rstrip('/')
    return explicit or f"https://{required('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def s3_client():
    return boto3.client(
        's3',
        endpoint_url=endpoint(),
        aws_access_key_id=required('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=required('R2_SECRET_ACCESS_KEY'),
        region_name='auto',
        config=Config(signature_version='s3v4', retries={'max_attempts': 3, 'mode': 'standard'}),
    )


def deterministic_bytes(offset: int, length: int) -> bytes:
    # A repeatable non-zero payload that can be regenerated after the simulated
    # server restart without storing a second 4K-sized fixture in the repo.
    return bytes(((offset + index) * 31 + 17) % 256 for index in range(length))


def api(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = os.environ.get('SPORTREEL_TEST_API_URL', 'http://127.0.0.1:3001').rstrip('/')
    response = requests.post(
        f'{base}{path}',
        headers={
            'content-type': 'application/json',
            'x-operator-secret': required('OPERATOR_SECRET'),
        },
        json=payload,
        timeout=TIMEOUT,
    )
    if not response.ok:
        raise RuntimeError(f'{path} returned {response.status_code}: {response.text[:500]}')
    return response.json()


def upload_part(state: dict[str, Any], part_number: int) -> None:
    part_size = int(state['part_size_bytes'])
    offset = (part_number - 1) * part_size
    length = min(part_size, TOTAL_BYTES - offset)
    signed = api('/api/operator/upload/multipart', {
        'action': 'part_url',
        'storage_key': state['storage_key'],
        'upload_id': state['upload_id'],
        'part_number': part_number,
    })
    upload_url = signed.get('upload_url')
    if not upload_url:
        raise RuntimeError(f'Part {part_number} did not receive a signed upload URL')
    response = requests.put(upload_url, data=deterministic_bytes(offset, length), timeout=TIMEOUT)
    if not response.ok:
        raise RuntimeError(f'Part {part_number} PUT returned {response.status_code}: {response.text[:500]}')
    if not response.headers.get('etag'):
        raise RuntimeError(f'Part {part_number} response did not expose an ETag')


def init_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {
        'filename': state['filename'],
        'mimeType': 'video/mp4',
        'batch_id': state['batch_id'],
        'upload_mode': 'multipart_resumable',
        'client_upload_id': state['client_upload_id'],
        'source_size_bytes': TOTAL_BYTES,
    }


def expected_storage_key(state: dict[str, Any]) -> str:
    return f"raw/{state['batch_id']}/{state['client_upload_id']}_{state['filename']}"


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')


def phase_init(state_path: Path) -> None:
    run_id = os.environ.get('GITHUB_RUN_ID', 'local')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    state: dict[str, Any] = {
        'filename': 'multipart-live-fixture.mp4',
        'batch_id': f'ci_multipart_{run_id}_{attempt}',
        'client_upload_id': f'ci_multipart_upload_{run_id}_{attempt}',
    }
    state['storage_key'] = expected_storage_key(state)
    # Persist cleanup identity before the first external write so the workflow
    # trap can remove the fixture even when initialization itself fails.
    save_state(state_path, state)

    # Reproduce a partial legacy single-PUT object at the exact stable key.
    # Multipart init must reject it as complete and later overwrite it.
    s3_client().put_object(
        Bucket=required('R2_BUCKET'),
        Key=state['storage_key'],
        Body=TRUNCATED_BYTES,
        ContentType='video/mp4',
    )

    result = api('/api/operator/upload', init_payload(state))
    upload = (result.get('uploads') or [result])[0]
    if upload.get('storage_key') != state['storage_key']:
        raise RuntimeError(f"Stable key mismatch: {upload.get('storage_key')} != {state['storage_key']}")
    if upload.get('already_complete'):
        raise RuntimeError('Wrong-size existing object was incorrectly treated as complete')
    if int(upload.get('existing_size_bytes') or -1) != len(TRUNCATED_BYTES):
        raise RuntimeError(f"Wrong-size object was not reported: {upload.get('existing_size_bytes')}")

    state.update({
        'upload_id': upload['multipart_upload_id'],
        'part_size_bytes': int(upload['part_size_bytes']),
    })
    save_state(state_path, state)
    if not state['upload_id']:
        raise RuntimeError('Multipart init did not return upload_id')
    if state['part_size_bytes'] < 5 * MIB:
        raise RuntimeError(f"Multipart part size is below 5 MiB: {state['part_size_bytes']}")

    upload_part(state, 1)
    status = api('/api/operator/upload/multipart', {
        'action': 'status',
        'storage_key': state['storage_key'],
        'upload_id': state['upload_id'],
    })
    parts = status.get('parts') or []
    if status.get('state') != 'in_progress' or len(parts) != 1 or int(parts[0]['partNumber']) != 1:
        raise RuntimeError(f'Unexpected state after first part: {status}')
    save_state(state_path, state)
    print('Live multipart phase 1 passed: wrong-size object rejected and first part persisted')


def phase_resume(state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding='utf-8'))
    resumed = api('/api/operator/upload', init_payload(state))
    upload = (resumed.get('uploads') or [resumed])[0]
    if upload.get('multipart_upload_id') != state['upload_id']:
        raise RuntimeError('Server restart did not reuse the original multipart upload_id')
    if not upload.get('multipart_reused'):
        raise RuntimeError('Resumed multipart init was not marked reused')

    status = api('/api/operator/upload/multipart', {
        'action': 'status',
        'storage_key': state['storage_key'],
        'upload_id': state['upload_id'],
    })
    completed_numbers = {int(part['partNumber']) for part in status.get('parts') or []}
    if completed_numbers != {1}:
        raise RuntimeError(f'Restart reconciliation lost or invented parts: {completed_numbers}')

    part_count = math.ceil(TOTAL_BYTES / int(state['part_size_bytes']))
    for part_number in range(1, part_count + 1):
        if part_number not in completed_numbers:
            upload_part(state, part_number)

    complete = api('/api/operator/upload/multipart', {
        'action': 'complete',
        'storage_key': state['storage_key'],
        'upload_id': state['upload_id'],
        'expected_size_bytes': TOTAL_BYTES,
    })
    if not complete.get('verified') or int(complete.get('size', -1)) != TOTAL_BYTES:
        raise RuntimeError(f'Completion did not verify exact bytes: {complete}')

    verified = api('/api/operator/upload/verify', {
        'storage_key': state['storage_key'],
        'expected_size_bytes': TOTAL_BYTES,
    })
    if not verified.get('ok') or int(verified.get('size', -1)) != TOTAL_BYTES:
        raise RuntimeError(f'Verify route did not confirm exact object size: {verified}')

    head = s3_client().head_object(Bucket=required('R2_BUCKET'), Key=state['storage_key'])
    if int(head['ContentLength']) != TOTAL_BYTES:
        raise RuntimeError(f"R2 HEAD size mismatch: {head['ContentLength']} != {TOTAL_BYTES}")
    print(f'Live multipart restart integration passed with {part_count} parts and exact size {TOTAL_BYTES}')


def phase_cleanup(state_path: Path) -> None:
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text(encoding='utf-8'))
    client = s3_client()
    bucket = required('R2_BUCKET')
    key = state.get('storage_key')
    upload_id = state.get('upload_id')
    if key and upload_id:
        try:
            client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
        except ClientError as error:
            code = str(error.response.get('Error', {}).get('Code', ''))
            if code not in {'NoSuchUpload', '404'}:
                raise
    if key:
        client.delete_object(Bucket=bucket, Key=key)
        try:
            client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            status = int(error.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0))
            if status != 404:
                raise
        else:
            raise RuntimeError('Live integration object still exists after cleanup')
    print('Live multipart fixture cleaned from R2')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['init', 'resume', 'cleanup'], required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()

    if args.phase == 'init':
        phase_init(args.state)
    elif args.phase == 'resume':
        phase_resume(args.state)
    else:
        phase_cleanup(args.state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
