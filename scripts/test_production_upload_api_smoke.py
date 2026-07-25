#!/usr/bin/env python3
"""Run a production-domain upload API smoke without real drone footage.

The smoke creates one tiny logical multipart source, verifies authorization and
correlation failures, reads status, aborts the empty R2 multipart session, records local
cleanup evidence, verifies the durable DB rows, and removes only its own test rows.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import psycopg
import requests

TIMEOUT = 45


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def post(base: str, path: str, secret: str | None, payload: Any = None, raw: bytes | None = None) -> requests.Response:
    headers = {"Accept": "application/json"}
    if secret is not None:
        headers["x-operator-secret"] = secret
    if raw is not None:
        headers["Content-Type"] = "application/json"
        return requests.post(f"{base}{path}", data=raw, headers=headers, timeout=TIMEOUT)
    return requests.post(f"{base}{path}", json=payload, headers=headers, timeout=TIMEOUT)


def expect(response: requests.Response, status: int, label: str) -> dict[str, Any]:
    if response.status_code != status:
        body = response.text[:500]
        raise RuntimeError(f"{label}: expected HTTP {status}, got {response.status_code}: {body}")
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"{label}: response is not JSON") from error
    return payload if isinstance(payload, dict) else {"value": payload}


def main() -> int:
    base = required("PRODUCTION_API_BASE_URL").rstrip("/")
    secret = required("PRODUCTION_OPERATOR_SECRET")
    db_url = required("SUPABASE_DB_URL")
    evidence_path = Path(os.getenv("PRODUCTION_SMOKE_EVIDENCE_PATH", "/tmp/production-upload-smoke.json"))
    token = uuid.uuid4().hex
    batch_id = f"release_smoke_{token[:20]}"
    client_upload_id = f"release-smoke-{token}"
    source_size = 11 * 1024 * 1024
    upload_id: str | None = None
    storage_key: str | None = None
    aborted = False
    cleanup_recorded = False
    evidence: dict[str, Any] = {
        "protocol": "production_upload_api_smoke_v1",
        "base_url": base,
        "batch_id": batch_id,
        "checks": [],
        "result": "pending",
        "started_at_unix": int(time.time()),
    }
    cleanup_errors: list[str] = []

    def passed(name: str) -> None:
        evidence["checks"].append({"name": name, "ok": True})

    try:
        expect(post(base, "/api/operator/upload/multipart/status", None, {"upload_id": "missing"}), 401, "missing auth")
        passed("non_operator_missing_auth_rejected")
        expect(post(base, "/api/operator/upload/multipart/status", "definitely-wrong", {"upload_id": "missing"}), 401, "wrong auth")
        passed("non_operator_wrong_auth_rejected")
        expect(post(base, "/api/operator/upload/batch", secret, raw=b"{"), 400, "malformed JSON")
        passed("malformed_input_rejected")
        expect(post(base, "/api/operator/upload/batch", secret, {"additional_file_count": 0}), 400, "invalid batch")
        passed("invalid_batch_input_rejected")

        batch = expect(
            post(base, "/api/operator/upload/batch", secret, {
                "batch_id": batch_id,
                "additional_file_count": 1,
                "source_kind": "api",
                "grouping_kind": "unassigned",
            }),
            200,
            "create batch",
        )
        if batch.get("batch_id") != batch_id or batch.get("expected_file_count") != 1:
            raise RuntimeError("Batch response does not preserve requested identity/count")
        passed("batch_created")

        started = expect(
            post(base, "/api/operator/upload/multipart/start", secret, {
                "client_upload_id": client_upload_id,
                "filename": "release-smoke.bin",
                "mimeType": "application/octet-stream",
                "size": source_size,
                "batch_id": batch_id,
                "part_size_bytes": 5 * 1024 * 1024,
                "local_cleanup_required": True,
            }),
            200,
            "start multipart",
        )
        upload_id = str(started.get("upload_id") or "")
        storage_key = str(started.get("storage_key") or "")
        if not upload_id or not storage_key.startswith(f"raw/{batch_id}/"):
            raise RuntimeError("Multipart start returned an invalid upload or raw key correlation")
        if started.get("batch_id") != batch_id or started.get("source_size_bytes") != source_size:
            raise RuntimeError("Multipart start correlation mismatch")
        evidence.update({"upload_id": upload_id, "storage_key": storage_key})
        passed("multipart_session_created")

        cross_batch = post(base, "/api/operator/upload/multipart/start", secret, {
            "client_upload_id": client_upload_id,
            "filename": "release-smoke.bin",
            "mimeType": "application/octet-stream",
            "size": source_size,
            "batch_id": f"{batch_id}_other",
            "part_size_bytes": 5 * 1024 * 1024,
            "local_cleanup_required": True,
        })
        expect(cross_batch, 409, "cross-batch idempotency mismatch")
        passed("cross_batch_start_mismatch_rejected")

        status = expect(
            post(base, "/api/operator/upload/multipart/status", secret, {
                "upload_id": upload_id,
                "batch_id": batch_id,
                "storage_key": storage_key,
            }),
            200,
            "read multipart status",
        )
        if status.get("batch_id") != batch_id or status.get("storage_key") != storage_key:
            raise RuntimeError("Multipart status correlation mismatch")
        passed("status_correlation_verified")

        expect(
            post(base, "/api/operator/upload/multipart/status", secret, {
                "upload_id": upload_id,
                "batch_id": f"{batch_id}_wrong",
                "storage_key": storage_key,
            }),
            409,
            "status cross-batch mismatch",
        )
        passed("cross_batch_status_mismatch_rejected")
        expect(
            post(base, "/api/operator/upload/multipart/status", secret, {
                "upload_id": upload_id,
                "batch_id": batch_id,
                "storage_key": f"raw/{batch_id}/wrong.bin",
            }),
            409,
            "status raw-key mismatch",
        )
        passed("raw_key_status_mismatch_rejected")

        aborted_payload = expect(
            post(base, "/api/operator/upload/multipart/abort", secret, {
                "upload_id": upload_id,
                "reason": "production_release_smoke",
            }),
            200,
            "abort multipart",
        )
        if aborted_payload.get("upload_status") != "aborted":
            raise RuntimeError("Abort did not return aborted status")
        aborted = True
        passed("multipart_abort_confirmed")

        cleanup = expect(
            post(base, "/api/operator/upload/multipart/cleanup", secret, {
                "upload_id": upload_id,
                "cleanup_status": "confirmed",
                "artifact_count": 0,
                "reclaimed_bytes": 0,
                "source_preserved": True,
            }),
            200,
            "record cleanup",
        )
        if cleanup.get("local_cleanup_status") != "confirmed":
            raise RuntimeError("Cleanup status was not confirmed")
        cleanup_recorded = True
        passed("cleanup_confirmation_recorded")

        final_status = expect(
            post(base, "/api/operator/upload/multipart/status", secret, {
                "upload_id": upload_id,
                "batch_id": batch_id,
                "storage_key": storage_key,
            }),
            200,
            "final status",
        )
        if final_status.get("status") != "aborted" or final_status.get("local_cleanup_status") != "confirmed":
            raise RuntimeError("Final API state is not aborted with confirmed cleanup")
        passed("final_api_state_verified")

        with psycopg.connect(db_url, connect_timeout=15) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select batch_id, storage_key, status, local_cleanup_status, client_upload_id "
                    "from public.source_uploads where id = %s::uuid",
                    (upload_id,),
                )
                row = cursor.fetchone()
                if row != (batch_id, storage_key, "aborted", "confirmed", client_upload_id):
                    raise RuntimeError(f"Durable source row mismatch: {row!r}")
                cursor.execute(
                    "select batch_id, expected_file_count, actual_file_count from public.upload_batches where batch_id=%s",
                    (batch_id,),
                )
                batch_row = cursor.fetchone()
                if not batch_row or batch_row[0] != batch_id or batch_row[1] != 1:
                    raise RuntimeError(f"Durable batch row mismatch: {batch_row!r}")
        passed("durable_db_state_verified")
        evidence["result"] = "success"
    finally:
        if upload_id and not aborted:
            try:
                response = post(base, "/api/operator/upload/multipart/abort", secret, {
                    "upload_id": upload_id,
                    "reason": "production_release_smoke_finally",
                })
                if response.status_code not in (200, 409):
                    cleanup_errors.append(f"abort cleanup returned HTTP {response.status_code}")
                else:
                    aborted = True
            except Exception as error:
                cleanup_errors.append(f"abort cleanup failed: {type(error).__name__}: {error}")
        if upload_id and aborted and not cleanup_recorded:
            try:
                response = post(base, "/api/operator/upload/multipart/cleanup", secret, {
                    "upload_id": upload_id,
                    "cleanup_status": "confirmed",
                    "artifact_count": 0,
                    "reclaimed_bytes": 0,
                    "source_preserved": True,
                })
                if response.status_code != 200:
                    cleanup_errors.append(f"cleanup evidence returned HTTP {response.status_code}")
            except Exception as error:
                cleanup_errors.append(f"cleanup evidence failed: {type(error).__name__}: {error}")
        if upload_id:
            try:
                with psycopg.connect(db_url, connect_timeout=15) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("delete from public.source_uploads where id=%s::uuid", (upload_id,))
                        cursor.execute("delete from public.upload_batches where batch_id=%s", (batch_id,))
                    connection.commit()
            except Exception as error:
                cleanup_errors.append(f"DB fixture cleanup failed: {type(error).__name__}: {error}")
        evidence["fixture_cleanup"] = "confirmed" if not cleanup_errors else "failed"
        evidence["cleanup_errors"] = cleanup_errors
        evidence["finished_at_unix"] = int(time.time())
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        if cleanup_errors:
            raise RuntimeError("Production smoke cleanup failed: " + "; ".join(cleanup_errors))

    print("Production upload API smoke passed and fixture cleanup was confirmed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
