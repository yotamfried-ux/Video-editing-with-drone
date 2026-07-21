#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def forbid(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def ordered(label: str, text: str, tokens: list[str]) -> None:
    cursor = -1
    for token in tokens:
        cursor = text.find(token, cursor + 1)
        if cursor < 0:
            raise SystemExit(f"{label} missing ordered token: {token!r}")


def block(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    return text[start_index:text.index(end, start_index)]


def main() -> int:
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    multipart_route = read("web-api/src/app/api/operator/upload/multipart/route.ts")
    r2 = read("web-api/src/lib/r2-storage.ts")
    pipeline = read("mobile/src/app/(operator)/pipeline.tsx")
    multipart_mobile = read("mobile/src/features/operator/lib/resumableMultipartUpload.ts")
    upload_queue = read("mobile/src/features/operator/lib/uploadQueue.ts")
    operator_workflow = read(".github/workflows/operator-smoke-check.yml")
    multipart_workflow = read(".github/workflows/r2-multipart-upload-contract.yml")

    ast.parse(read("scripts/test_multi_upload_batch_contract.py"))

    require("batch and multipart init", upload_route, [
        "MAX_BATCH_FILES",
        "files?: UploadFileInput[]",
        "normalizeUploadFiles",
        "String(index + 1).padStart(3, '0')",
        "upload_mode?: 'resilient_batch_item' | 'multipart_resumable'",
        "source_size_bytes?: number",
        "operator-upload-multipart-item",
        "safeBatchId(requestedBatchId) || newBatchId()",
        "client_upload_id is required for resilient uploads",
        "source_size_bytes is required for multipart uploads",
        "createR2MultipartUpload(",
        "multipart_upload_id: upload.upload_id",
        "part_size_bytes: upload.part_size_bytes",
        "already_complete: upload.already_complete",
        "source_filename: file.filename",
        "storage_key: upload.key",
    ])
    ordered("parse before rate limit", upload_route, ["const files = normalizeUploadFiles(body);", "const limited = await enforceRateLimit"])

    require("R2 lifecycle", r2, [
        "MIN_MULTIPART_PART_SIZE = 5 * MIB",
        "DEFAULT_MULTIPART_PART_SIZE = 8 * MIB",
        "MAX_MULTIPART_PARTS = 10_000",
        "createR2MultipartUpload",
        "findActiveMultipartUpload",
        "createR2MultipartPartUrl",
        "listR2MultipartParts",
        "getR2MultipartStatus",
        "validateCompleteParts",
        "completeR2MultipartUpload",
        "abortR2MultipartUpload",
        "All non-final multipart parts must use the same byte size",
        "Multipart byte total mismatch",
        "R2 completed-object verification failed",
    ])
    require("authenticated lifecycle route", multipart_route, [
        "requireOperator(req)",
        "operator-upload-multipart-lifecycle",
        "action === 'status'",
        "action === 'part_url'",
        "action === 'complete'",
        "abortR2MultipartUpload",
        "expected_size_bytes",
    ])

    require("mobile batch UX", pipeline, [
        "allowsMultipleSelection: true",
        "runQueue(items",
        "withRetry(",
        "upload_mode: 'multipart_resumable'",
        "client_upload_id: item.id",
        "source_size_bytes: sourceSizeBytes",
        "prepareMultipartSource(item)",
        "resumeMultipartUpload({",
        "loadActiveMultipartBatch()",
        "clearPersistedMultipartBatch(finishedBatch)",
        "Resume all failed",
        "Upload batch progress",
        "Pipeline start is blocked until every selected upload is verified.",
        "Uploading ${verifiedUploads}/${uploadItems.length}",
    ])
    forbid("no single-selection regression", pipeline, [
        "allowsMultipleSelection: false",
        "const asset = result.assets[0]",
        "setUploadProgress",
        "uploadProgress !== null",
    ])

    require("persisted part resume", multipart_mobile, [
        "AsyncStorage",
        "ACTIVE_BATCH_KEY",
        "uploadId: string",
        "parts: MultipartUploadPart[]",
        "FileSystem.readAsStringAsync",
        "FileSystem.EncodingType.Base64",
        "while (remaining > 0)",
        "position: cursor",
        "length: remaining",
        "const combined = new Uint8Array(length)",
        "action: 'status'",
        "action: 'part_url'",
        "action: 'complete'",
        "response.headers.get('etag')",
        "authoritativeUploadedPart",
        "loadActiveMultipartBatch",
        "clearPersistedMultipartBatch",
        "cleanupStagedSource",
        "abortPersistedMultipartUpload",
    ])
    part_loop = block(multipart_mobile, "for (let partNumber = 1", "const finalStatus = await serverStatus")
    ordered("persist uploaded part before next iteration", part_loop, [
        "const uploaded = await uploadPart",
        "record.parts = normalizedParts",
        "await saveRecord(record)",
        "input.onProgress?.",
    ])
    forbid("no whole-file multipart materialization", multipart_mobile, [
        ".slice(",
        "FileSystem.copyAsync",
        "FileSystem.createUploadTask",
    ])

    require("retry queue", upload_queue, [
        "isRetryableUploadError",
        "error.status === 403",
        "error.status === 429",
        "error.status >= 500",
        "retryDelay",
        "PromiseSettledResult<void>[]",
        "concurrencyLimit",
    ])
    require("operator smoke wiring", operator_workflow, [
        "scripts/test_multi_upload_batch_contract.py",
        "Validate Multi-upload batch contract",
    ])
    require("dedicated multipart wiring", multipart_workflow, [
        "scripts/test_multi_upload_batch_contract.py",
        "Validate multi-upload batch contract",
    ])

    print("Multi-upload multipart resume contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
