#!/usr/bin/env python3
"""Remove the legacy biometric Storage bucket through the supported Supabase Storage API."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "athlete-photos"
CONFIRMATION = "REMOVE_BIOMETRICS"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def request(method: str, url: str, key: str) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        if exc.code == 404:
            return 404, body
        # Never print the response body. It may contain sensitive diagnostics.
        raise RuntimeError(f"Supabase Storage API {method} failed with HTTP {exc.code}") from None


def main() -> int:
    base = required("SUPABASE_URL").rstrip("/")
    key = required("SUPABASE_SERVICE_KEY")
    confirmation = required("CONFIRM_BIOMETRIC_REMOVAL")
    if confirmation != CONFIRMATION:
        raise RuntimeError(
            f"CONFIRM_BIOMETRIC_REMOVAL must equal {CONFIRMATION}"
        )

    evidence_path = Path(
        os.getenv("BIOMETRIC_STORAGE_EVIDENCE_PATH", "/tmp/biometric-storage-evidence.json")
    )
    evidence = {
        "protocol": "supabase_biometric_storage_removal_v1",
        "bucket": BUCKET,
        "secret_values_recorded": False,
        "result": "pending",
    }

    bucket_id = urllib.parse.quote(BUCKET, safe="")
    bucket_url = f"{base}/storage/v1/bucket/{bucket_id}"

    try:
        status, _ = request("GET", bucket_url, key)
        if status == 404:
            evidence.update(
                {
                    "bucket_existed": False,
                    "bucket_emptied": False,
                    "bucket_deleted": True,
                    "result": "success",
                }
            )
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
            print("Biometric Storage bucket already absent.")
            return 0

        # Use the official Storage API to remove any remaining files before deleting the bucket.
        empty_url = f"{bucket_url}/empty"
        empty_status, _ = request("POST", empty_url, key)
        if empty_status not in {200, 201}:
            raise RuntimeError(f"Unexpected empty-bucket status {empty_status}")

        delete_status, _ = request("DELETE", bucket_url, key)
        if delete_status not in {200, 204}:
            raise RuntimeError(f"Unexpected delete-bucket status {delete_status}")

        verify_status, _ = request("GET", bucket_url, key)
        if verify_status != 404:
            raise RuntimeError("Biometric Storage bucket still exists after deletion")

        evidence.update(
            {
                "bucket_existed": True,
                "bucket_emptied": True,
                "bucket_deleted": True,
                "result": "success",
            }
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        print("Biometric Storage bucket removed through Supabase Storage API.")
        return 0
    except Exception as error:
        evidence.update(
            {
                "result": "failure",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
