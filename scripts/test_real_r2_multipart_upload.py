#!/usr/bin/env python3
"""Run a real, non-destructive Cloudflare R2 multipart upload probe.

The probe creates deterministic bytes, uploads several parts through presigned URLs,
retries one part, completes with the exact latest response ETags in ascending order,
verifies HEAD/download size and SHA-256, proves the completed multipart ETag is not the
whole-file MD5, then deletes the object and verifies absence. Cleanup failure is fatal.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import boto3
import requests
from botocore.config import Config

MIB = 1024 * 1024
PART_SIZE = 5 * MIB


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def endpoint() -> str:
    explicit = os.getenv("R2_ENDPOINT_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    return f"https://{required('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def deterministic_part(part_number: int, size: int) -> bytes:
    seed = hashlib.sha256(f"sportreel-r2-probe-part-{part_number}".encode()).digest()
    repeats, remainder = divmod(size, len(seed))
    return seed * repeats + seed[:remainder]


def sha256_bytes(chunks: list[bytes]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def md5_bytes(chunks: list[bytes]) -> str:  # nosec B324 - comparison evidence, not security
    digest = hashlib.md5(usedforsecurity=False)
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def safe_etag(value: str | None) -> str:
    etag = (value or "").strip()
    if not etag:
        raise RuntimeError("R2 part response did not expose an ETag")
    if len(etag) > 1024:
        raise RuntimeError("R2 part ETag is unexpectedly long")
    return etag


def unquote_etag(value: str) -> str:
    return value.strip().strip('"')


def main() -> int:
    total_mib = int(os.getenv("R2_PROBE_SIZE_MIB", "11"))
    if total_mib < 11 or total_mib > 64:
        raise RuntimeError("R2_PROBE_SIZE_MIB must be between 11 and 64")

    bucket = os.getenv("R2_BUCKET", "sportreel").strip() or "sportreel"
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    key = f"integration-tests/large-upload/{run_id}/{uuid.uuid4().hex}.bin"
    total_size = total_mib * MIB
    part_sizes: list[int] = []
    remaining = total_size
    while remaining > 0:
        size = min(PART_SIZE, remaining)
        part_sizes.append(size)
        remaining -= size

    client = boto3.client(
        "s3",
        endpoint_url=endpoint(),
        aws_access_key_id=required("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=required("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )

    upload_id: str | None = None
    object_created = False
    probe_succeeded = False
    started = time.time()
    evidence: dict[str, Any] = {
        "protocol": "r2_multipart_real_probe_v2",
        "bucket": bucket,
        "key": key,
        "total_size_bytes": total_size,
        "part_size_bytes": PART_SIZE,
        "part_count": len(part_sizes),
        "retried_part_number": 2,
        "parts": [],
        "cleanup": "pending",
    }

    try:
        created = client.create_multipart_upload(Bucket=bucket, Key=key, ContentType="application/octet-stream")
        upload_id = str(created["UploadId"])
        evidence["upload_id_prefix"] = upload_id[:12]

        source_chunks = [deterministic_part(index + 1, size) for index, size in enumerate(part_sizes)]
        expected_sha256 = sha256_bytes(source_chunks)
        source_md5 = md5_bytes(source_chunks)
        completed_parts: list[dict[str, Any]] = []

        for part_number, payload in enumerate(source_chunks, start=1):
            presigned_url = client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=900,
            )
            response = requests.put(
                presigned_url,
                data=payload,
                headers={"Content-Type": "application/octet-stream"},
                timeout=180,
            )
            response.raise_for_status()
            first_etag = safe_etag(response.headers.get("ETag"))
            latest_etag = first_etag
            attempts = 1

            if part_number == 2:
                retry = requests.put(
                    presigned_url,
                    data=payload,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=180,
                )
                retry.raise_for_status()
                latest_etag = safe_etag(retry.headers.get("ETag"))
                attempts = 2

            completed_parts.append({"PartNumber": part_number, "ETag": latest_etag})
            evidence["parts"].append(
                {
                    "part_number": part_number,
                    "size_bytes": len(payload),
                    "attempts": attempts,
                    "first_etag": first_etag,
                    "completion_etag": latest_etag,
                    "latest_successful_etag_used": True,
                }
            )

        completion = client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": completed_parts},
        )
        object_created = True
        upload_id = None

        head = client.head_object(Bucket=bucket, Key=key)
        actual_size = int(head["ContentLength"])
        if actual_size != total_size:
            raise RuntimeError(f"R2 HEAD size mismatch: expected {total_size}, got {actual_size}")
        completed_etag = safe_etag(str(head.get("ETag") or completion.get("ETag") or ""))
        normalized_completed_etag = unquote_etag(completed_etag)
        if normalized_completed_etag == source_md5:
            raise RuntimeError("Completed multipart ETag was incorrectly equal to the whole-file MD5")
        expected_suffix = f"-{len(part_sizes)}"
        if len(part_sizes) > 1 and not normalized_completed_etag.endswith(expected_suffix):
            raise RuntimeError(
                f"Completed multipart ETag does not expose expected part-count suffix {expected_suffix}"
            )

        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(prefix="sportreel-r2-probe-", delete=True) as target:
            client.download_fileobj(bucket, key, target)
            target.flush()
            target.seek(0)
            while True:
                chunk = target.read(MIB)
                if not chunk:
                    break
                digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError("Downloaded R2 object SHA-256 does not match the source bytes")

        evidence.update(
            {
                "head_size_bytes": actual_size,
                "source_sha256": expected_sha256,
                "download_sha256": actual_sha256,
                "download_matches_source": True,
                "source_file_md5": source_md5,
                "completed_multipart_etag": completed_etag,
                "multipart_etag_is_not_file_md5": True,
                "multipart_etag_part_count_suffix_verified": True,
                "completion_part_numbers": [part["PartNumber"] for part in completed_parts],
                "completion_part_numbers_ascending": True,
                "duration_seconds": round(time.time() - started, 3),
            }
        )
        probe_succeeded = True
        print(f"PASS: real R2 multipart retry, ETag, HEAD, hash, and cleanup probe for {key}")
    finally:
        cleanup_errors: list[str] = []
        if upload_id:
            try:
                client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except Exception as error:  # pragma: no cover - real service cleanup path
                cleanup_errors.append(f"abort failed: {type(error).__name__}: {error}")
        if object_created:
            try:
                client.delete_object(Bucket=bucket, Key=key)
                try:
                    client.head_object(Bucket=bucket, Key=key)
                    cleanup_errors.append("object still exists after delete")
                except client.exceptions.ClientError as error:
                    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if status != 404:
                        cleanup_errors.append(f"post-delete HEAD failed with status {status}")
            except Exception as error:  # pragma: no cover - real service cleanup path
                cleanup_errors.append(f"object delete failed: {type(error).__name__}: {error}")

        evidence["cleanup"] = "confirmed" if not cleanup_errors else "failed"
        evidence["cleanup_errors"] = cleanup_errors
        evidence["probe_succeeded"] = probe_succeeded
        evidence_path = Path(os.getenv("R2_PROBE_EVIDENCE_PATH", "/tmp/r2-multipart-evidence.json"))
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Evidence written to {evidence_path}")
        if cleanup_errors:
            message = "Cleanup failures: " + "; ".join(cleanup_errors)
            print(message, file=sys.stderr)
            raise RuntimeError(message)

    if not probe_succeeded:
        raise RuntimeError("R2 probe did not reach verified completion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
