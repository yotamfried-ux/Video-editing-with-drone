#!/usr/bin/env python3
"""Independent backend verification for UPL-01 (Android gallery upload E2E).

The Maestro flows prove what the operator *saw*. This script proves what the
backend *recorded*, without trusting any UI text:

1. exactly one gallery ``public.source_uploads`` row with the fixture's exact
   byte count was created since the run started (so the negative flows created
   none and the positive flow did not double-upload). The filename is recorded
   but not used for correlation: on the Android 13+ Photo Picker path the app
   receives a MediaStore display name such as ``1000000016.mp4``;
2. that row is a verified single-PUT gallery upload whose declared and
   verified sizes equal the exact fixture byte count;
3. the production verify API independently HEADs the exact R2 object and
   reports the same size and a verified status.

Secrets are read from the environment only and are never written to the
evidence file. Exit code 0 means PASS; any failed check exits 1 with the
specific reasons.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ROW_COLUMNS = (
    "id,client_upload_id,batch_id,storage_key,source_filename,mime_type,status,"
    "source_size_bytes,verified_size_bytes,verified_at,source_size_evidence,"
    "upload_protocol,created_at"
)
CLIENT_UPLOAD_ID = re.compile(r"^gallery_[A-Za-z0-9_-]+$")


def check_rows(rows: list[dict[str, Any]], *, fixture_bytes: int) -> list[str]:
    """Return failure reasons for the gallery rows of fixture size since the run started."""
    if len(rows) != 1:
        return [f"expected exactly 1 gallery source_uploads row of {fixture_bytes} bytes since run start, found {len(rows)}"]
    row = rows[0]
    errors: list[str] = []
    for field in ("id", "client_upload_id", "batch_id", "storage_key", "source_filename", "verified_at"):
        if not row.get(field):
            errors.append(f"row.{field} is empty")
    if row.get("status") != "verified":
        errors.append(f"row.status={row.get('status')!r}, expected 'verified'")
    if row.get("upload_protocol") != "single_put":
        errors.append(f"row.upload_protocol={row.get('upload_protocol')!r}, expected 'single_put'")
    if row.get("source_size_bytes") != fixture_bytes:
        errors.append(f"row.source_size_bytes={row.get('source_size_bytes')!r}, expected fixture size {fixture_bytes}")
    if row.get("verified_size_bytes") != fixture_bytes:
        errors.append(f"row.verified_size_bytes={row.get('verified_size_bytes')!r}, expected fixture size {fixture_bytes}")
    client_upload_id = row.get("client_upload_id") or ""
    if client_upload_id and not CLIENT_UPLOAD_ID.match(client_upload_id):
        errors.append(f"row.client_upload_id={client_upload_id!r} is not an app gallery upload id")
    storage_key = row.get("storage_key") or ""
    batch_id = row.get("batch_id") or ""
    filename = row.get("source_filename") or ""
    if storage_key and batch_id and filename and not (
        storage_key.startswith(f"raw/{batch_id}/") and storage_key.endswith(f"_{filename}")
    ):
        errors.append(f"row.storage_key={storage_key!r} is not raw/<batch_id>/<stamp>_{filename}")
    return errors


def check_verify_response(status_code: int, body: dict[str, Any], *, row: dict[str, Any], fixture_bytes: int) -> list[str]:
    """Return failure reasons for the verify API's view of the exact R2 object."""
    errors: list[str] = []
    if status_code != 200:
        errors.append(f"verify API returned HTTP {status_code}: {body.get('error')!r}")
    expected = {
        "ok": True,
        "exists": True,
        "storage_backend": "r2",
        "storage_key": row.get("storage_key"),
        "size": fixture_bytes,
        "upload_id": row.get("id"),
        "upload_status": "verified",
    }
    for field, value in expected.items():
        if body.get(field) != value:
            errors.append(f"verify.{field}={body.get(field)!r}, expected {value!r}")
    return errors


def _request(url: str, *, headers: dict[str, str], data: bytes | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw or b"null")
        except json.JSONDecodeError:
            return error.code, {"error": raw[:300].decode("utf-8", "replace")}


def fetch_rows(supabase_url: str, service_key: str, *, fixture_bytes: int, since_iso: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "select": ROW_COLUMNS,
            "client_upload_id": "like.gallery_*",
            "source_size_bytes": f"eq.{fixture_bytes}",
            "created_at": f"gte.{since_iso}",
            "order": "created_at.asc",
        }
    )
    status, body = _request(
        f"{supabase_url.rstrip('/')}/rest/v1/source_uploads?{query}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    if status != 200 or not isinstance(body, list):
        raise RuntimeError(f"Supabase source_uploads read failed with HTTP {status}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", required=True, help="path to the exact MP4 seeded into the emulator")
    parser.add_argument("--since", required=True, help="ISO-8601 UTC timestamp taken before the first flow")
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--supabase-url", required=True)
    parser.add_argument("--evidence", required=True, help="output JSON path (no secrets)")
    args = parser.parse_args()

    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    operator_secret = os.environ["OPERATOR_SECRET"]
    filename = os.path.basename(args.fixture)
    fixture_bytes = os.path.getsize(args.fixture)

    rows = fetch_rows(args.supabase_url, service_key, fixture_bytes=fixture_bytes, since_iso=args.since)
    errors = check_rows(rows, fixture_bytes=fixture_bytes)
    row = rows[0] if len(rows) == 1 else {}
    verify_status, verify_body = None, None
    if not errors:
        verify_status, verify_body = _request(
            f"{args.api_base.rstrip('/')}/api/operator/upload/verify",
            headers={"x-operator-secret": operator_secret, "Content-Type": "application/json"},
            data=json.dumps({"storage_key": row["storage_key"]}).encode(),
        )
        errors += check_verify_response(verify_status, verify_body or {}, row=row, fixture_bytes=fixture_bytes)

    evidence = {
        "experiment": "UPL-01",
        "harness": "maestro",
        "result": "PASS" if not errors else "FAIL",
        "failures": errors,
        "fixture": {"filename": filename, "size_bytes": fixture_bytes},
        "source_filename_preserved": bool(row) and row.get("source_filename") == filename,
        "window_start_utc": args.since,
        "rows_since_window_start": len(rows),
        "source_upload": {key: row.get(key) for key in ROW_COLUMNS.split(",")} if row else None,
        "verify_api": {"http_status": verify_status, "body": verify_body},
        "run": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "sha": os.environ.get("GITHUB_SHA"),
            "ref": os.environ.get("GITHUB_REF_NAME"),
            "run_url": (
                f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}"
                if os.environ.get("GITHUB_RUN_ID")
                else None
            ),
        },
        "secret_values_recorded": False,
    }
    with open(args.evidence, "w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
    for error in errors:
        print(f"UPL-01 backend check failed: {error}", file=sys.stderr)
    print(f"UPL-01 backend verification: {evidence['result']}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
