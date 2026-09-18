#!/usr/bin/env python3
"""Remove the legacy biometric Storage bucket through the official Supabase SDK."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from supabase import create_client

BUCKET = "athlete-photos"
CONFIRMATION = "REMOVE_BIOMETRICS"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def bucket_id(row: object) -> str:
    if isinstance(row, dict):
        return str(row.get("id") or row.get("name") or "")
    return str(getattr(row, "id", "") or getattr(row, "name", ""))


def main() -> int:
    url = required("SUPABASE_URL")
    key = required("SUPABASE_SERVICE_KEY")
    confirmation = required("CONFIRM_BIOMETRIC_REMOVAL")
    if confirmation != CONFIRMATION:
        raise RuntimeError(f"CONFIRM_BIOMETRIC_REMOVAL must equal {CONFIRMATION}")

    evidence_path = Path(
        os.getenv("BIOMETRIC_STORAGE_EVIDENCE_PATH", "/tmp/biometric-storage-evidence.json")
    )
    evidence = {
        "protocol": "supabase_biometric_storage_removal_v2",
        "bucket": BUCKET,
        "sdk": "supabase-py",
        "secret_values_recorded": False,
        "result": "pending",
    }

    try:
        client = create_client(url, key)
        buckets = client.storage.list_buckets()
        exists = any(bucket_id(row) == BUCKET for row in buckets)

        if not exists:
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

        client.storage.empty_bucket(BUCKET)
        client.storage.delete_bucket(BUCKET)

        remaining = client.storage.list_buckets()
        if any(bucket_id(row) == BUCKET for row in remaining):
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
        print("Biometric Storage bucket removed through Supabase SDK.")
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
