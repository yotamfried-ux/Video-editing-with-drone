#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def require_order(label: str, text: str, first: str, second: str) -> None:
    if first not in text or second not in text:
        raise SystemExit(f"{label} missing ordering tokens: {first!r}, {second!r}")
    if text.index(first) > text.index(second):
        raise SystemExit(f"{label} has wrong order: {first!r} must come before {second!r}")


def main() -> int:
    upload_route = _read("web-api/src/app/api/operator/upload/route.ts")
    multipart_route = _read("web-api/src/app/api/operator/upload/multipart/route.ts")
    r2_storage = _read("web-api/src/lib/r2-storage.ts")
    pipeline_screen = _read("mobile/src/app/(operator)/pipeline.tsx")
    multipart_mobile = _read("mobile/src/features/operator/lib/resumableMultipartUpload.ts")
    upload_queue = _read("mobile/src/features/operator/lib/uploadQueue.ts")
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    ast.parse(_read("scripts/test_multi_upload_batch_contract.py"))

    require_tokens(
        "upload route batch and multipart API",
        upload_route,
        [
            "MAX_BATCH_FILES",
            "files?: UploadFileInput[]",
            "normalizeUploadFiles",
            "uploadFilename",
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
        ],
    )
    require_order(
        "upload route parses files before rate limit",
        upload_route,
        "const files = normalizeUploadFiles(body);",
        "const limited = await enforceRateLimit",
    )

    require_tokens(
        "R2 multipart lifecycle",
        r2_storage,
        [
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
        ],
    )

    require_tokens(
        "authenticated multipart route",
        multipart_route,
        [
            "requireOperator(req)",
            "operator-upload-multipart-lifecycle",
            "action === 'status'",
            "action === 'part_url'",
            "action === 'complete'",
            "abortR2MultipartUpload",
            "getR2MultipartStatus",
            "createR2MultipartPartUrl",
            "completeR2MultipartUpload",
            "expected_size_bytes",
        ],
    )

    require_tokens(
        "mobile resumable multi-file upload UX",
        pipeline_screen,
        [
            "allowsMultipleSelection: true",
            "UploadFileState",
            "uploadItems",
            "runQueue(items",
            "withRetry(",
            "requestUploadSession",
            "upload_mode: 'multipart_resumable'",
            "client_upload_id: item.id",
            "source_size_bytes: sourceSizeBytes",
            "resumeMultipartUpload({",
            "loadActiveMultipartBatch()",
            "clearPersistedMultipartBatch(finishedBatch)",
            "MAX_UPLOAD_ATTEMPTS",
            "Resume all failed",
            "Upload batch progress",
            "Pipeline start is blocked until every selected upload is verified.",
            "Uploading ${verifiedUploads}/${uploadItems.length}",
        ],
    )

    require_tokens(
        "persisted part-level resume",
        multipart_mobile,
        [
            "AsyncStorage",
            "ACTIVE_BATCH_KEY",
            "uploadId: string",
            "parts: MultipartUploadPart[]",
            "FileSystem.readAsStringAsync",
            "FileSystem.EncodingType.Base64",
            "position: offset",
            "length,",
            "action: 'status'",
            "action: 'part_url'",
            "action: 'complete'",
            "response.headers.get('etag')",
            "authoritativeUploadedPart",
            "await saveRecord(record)",
            "loadActiveMultipartBatch",
            "clearPersistedMultipartBatch",
            "abortPersistedMultipartUpload",
        ],
    )
    require_order(
        "part state is persisted after authoritative upload",
        multipart_mobile,
        "const uploaded = await uploadPart",
        "await saveRecord(record)",
    )
    require_no_tokens(
        "multipart uploader must not materialize the entire video",
        multipart_mobile,
        [
            ".slice(",
            "FileSystem.copyAsync",
            "FileSystem.createUploadTask",
            "readAsStringAsync(sourceUri, { encoding: FileSystem.EncodingType.Base64 })",
        ],
    )

    require_tokens(
        "retry queue semantics",
        upload_queue,
        [
            "isRetryableUploadError",
            "error.status === 403",
            "error.status === 429",
            "error.status >= 500",
            "retryDelay",
            "PromiseSettledResult<void>[]",
            "concurrencyLimit",
        ],
    )
    require_no_tokens(
        "mobile must not select only one asset or use removed scalar progress state",
        pipeline_screen,
        [
            "allowsMultipleSelection: false",
            "const asset = result.assets[0]",
            "setUploadProgress",
            "uploadProgress !== null",
        ],
    )

    require_tokens(
        "operator smoke workflow trigger",
        workflow,
        [
            "scripts/test_multi_upload_batch_contract.py",
            "web-api/src/app/api/operator/upload/route.ts",
            "mobile/src/features/operator/lib/uploadQueue.ts",
            "Validate Multi-upload batch contract",
        ],
    )

    print("Multi-upload multipart resume contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
