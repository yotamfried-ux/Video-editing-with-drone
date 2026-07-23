#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(token: str, text: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"{label} missing {token}")


def forbid(token: str, text: str, label: str) -> None:
    if token in text:
        raise SystemExit(f"{label} contains forbidden {token}")


def main() -> int:
    migration = read("supabase/migrations/20260722_multipart_upload_foundation.sql")
    policy = read("web-api/src/lib/multipart-policy.mjs")
    r2 = read("web-api/src/lib/r2-storage.ts")
    route = read("web-api/src/app/api/operator/upload/multipart/route.ts")
    admission = read("web-api/src/lib/upload-batch-admission.ts")
    pipeline_start = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    focused_audit = read("docs/audit/multipart-upload-foundation-20260722.md")
    main_audit = read("docs/app-pipeline-audit.md")

    for token in [
        "create table if not exists public.upload_batches",
        "create table if not exists public.upload_files",
        "create table if not exists public.upload_parts",
        "part_size_bytes bigint not null check (part_size_bytes >= 5242880)",
        "total_parts integer not null check (total_parts between 1 and 10000)",
        "upload_files_active_source_fingerprint_idx",
        "state in ('collecting', 'uploading', 'ready', 'dispatching', 'dispatched'",
        "alter table public.upload_batches enable row level security",
        "alter table public.upload_files enable row level security",
        "alter table public.upload_parts enable row level security",
        "refresh_upload_batch_rollup",
        "refresh_upload_file_bytes",
    ]:
        require(token, migration, "multipart migration")

    for token in [
        "MIN_PART_SIZE_BYTES = 5 * MIB",
        "MAX_MULTIPART_PARTS = 10_000",
        "MULTIPART_PROTOCOL_VERSION = 'r2-multipart-v1'",
        "chooseMultipartPartSize",
        "expectedMultipartPartCount",
        "expectedPartSize",
        "normalizeCompletedParts",
        "duplicate part number",
        "missing ETag",
        "normalized.sort((a, b) => a.PartNumber - b.PartNumber)",
    ]:
        require(token, policy, "multipart policy")

    for token in [
        "createR2MultipartUpload",
        "createR2MultipartPartUrl",
        "listR2MultipartParts",
        "completeR2MultipartUpload",
        "abortR2MultipartUpload",
        "new URLSearchParams({ uploads: '' })",
        "new URLSearchParams({ partNumber: String(partNumber), uploadId })",
        "<CompleteMultipartUpload>",
        "verifyR2Object",
        "NoSuchUpload",
    ]:
        require(token, r2, "R2 multipart adapter")

    for token in [
        "'create_batch'",
        "'create_upload'",
        "'part_url'",
        "'record_part'",
        "'complete'",
        "client_upload_id",
        "upload_id:",
        "source_fingerprint",
        "normalizeCompletedParts",
        "listR2MultipartParts",
        "R2 parts do not match the durable ETag/size ledger",
        "verified.size !== upload.source_size_bytes",
        "in_flight_part_numbers",
        "wait for all in-flight part requests before abort",
        "state === 'completing'",
        "already_completed",
    ]:
        require(token, route, "multipart operator route")
    forbid("bytesSync", route, "multipart operator route")
    forbid("base64", route, "multipart operator route")

    for token in [
        "claimVerifiedUploadBatch",
        ".eq('state', 'ready')",
        ".update({ state: 'dispatching' })",
        "verified_size_bytes !== file.source_size_bytes",
        "releaseUploadBatchClaim",
        "markUploadBatchDispatched",
    ]:
        require(token, admission, "upload batch admission")

    for token in [
        "A verified durable batch_id is required for R2 pipeline runs",
        "claimVerifiedUploadBatch",
        "input_files: admittedBatch?.input_objects",
        "AbortSignal.timeout(8_000)",
        "releaseUploadBatchClaim",
        "markUploadBatchDispatched",
        "workflow_dispatched",
    ]:
        require(token, pipeline_start, "pipeline start gate")

    for token in [
        "cloudflare/cloudflare-docs",
        "aws/aws-sdk-js-v3",
        "expo/expo/blob/sdk-52",
        "FileBlob.slice()",
        "ContentResolver",
        "Do not hide the SDK 52 limitation by copying the complete external video to cache",
        "GAP-026",
        "aws-samples/amazon-s3-checksum-tool",
        "dropbox.com/developers/reference/content-hash",
        "git-lfs/git-lfs/blob/main/docs/spec.md",
        "postgresql.org/docs/current/indexes-partial.html",
        "newest successfully verified upload wins",
        "multipart ETag are not exact-content identity",
        "No foundation code or green CI result closes GAP-013, GAP-014, GAP-015, or GAP-026",
    ]:
        require(token, focused_audit, "multipart focused audit")

    for token in [
        "GAP-013 — Resumable multipart R2 upload",
        "GAP-014 — Durable Android source access and restart recovery",
        "GAP-015 — Durable batch/session/athlete upload manifest and verified-run gate",
        "GAP-026 — Exact-content upload deduplication and newest-verified retention",
        "byte-identical uploads resolve to one canonical newest-verified source before dispatch",
        "multipart-upload-foundation-20260722.md",
    ]:
        require(token, main_audit, "consolidated audit")

    print("Multipart upload foundation contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
