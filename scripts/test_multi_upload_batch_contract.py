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
    pipeline_screen = _read("mobile/src/app/(operator)/pipeline.tsx")
    upload_queue = _read("mobile/src/features/operator/lib/uploadQueue.ts")
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    ast.parse(_read("scripts/test_multi_upload_batch_contract.py"))

    require_tokens(
        "durable upload route",
        upload_route,
        [
            "MAX_BATCH_FILES",
            "client_upload_id?: string",
            "files?: UploadFileInput[]",
            "normalizeUploadFiles",
            "resolveSinglePutBatchId",
            "findSourceUploadByClientUploadId",
            "createSinglePutSourceManifest",
            "registerSourceUploadBatchMembership",
            "createR2UploadUrlForKey(session.storageKey)",
            "source_filename: session.sourceFilename",
            "uploads,",
            "storage_key: session.storageKey",
        ],
    )
    require_order(
        "upload route parses files before rate limit",
        upload_route,
        "const files = normalizeUploadFiles(body);",
        "const limited = await enforceRateLimit",
    )
    require_no_tokens(
        "upload route must not recreate timestamped sources on every retry",
        upload_route,
        [
            "createR2UploadUrl(file.uploadFilename, batchId)",
            "createR2UploadUrl(file.filename, batchId)",
            "createUploadSession(file.filename, rawFolder, file.mimeType)",
        ],
    )

    require_tokens(
        "mobile multi-file upload UX",
        pipeline_screen,
        [
            "allowsMultipleSelection: true",
            "UploadFileState",
            "uploadItems",
            "clientUploadId",
            "requestUploadSession",
            "sourceSizeBytes",
            "batch_id: item.batch_id ?? activeBatchId",
            "uploadInit.uploads?.[0] ?? uploadInit",
            "uploadAssetToSession",
            "runUploadQueue",
            "retryUploadItem",
            "Retry all failed",
            "Upload batch progress",
            "Uploading ${verifiedUploads}/${uploadItems.length}",
        ],
    )
    require_no_tokens(
        "mobile must not select only one asset or reuse an anonymous upload session",
        pipeline_screen,
        [
            "allowsMultipleSelection: false",
            "const asset = result.assets[0]",
            "setUploadProgress",
            "uploadProgress !== null",
        ],
    )

    require_tokens(
        "upload queue batch-race protection",
        upload_queue,
        [
            "createClientBatchId",
            "assignSharedUploadBatchId",
            "Selected uploads span multiple durable batches",
            "const batchScopedItems: BatchScopedUpload[] = []",
            "if (isBatchScopedUpload(item)) batchScopedItems.push(item)",
            "batchScopedItems.length === items.length",
            "assignSharedUploadBatchId(batchScopedItems);",
            "const workerCount = Math.min(Math.max(concurrencyLimit, 1), items.length)",
        ],
    )
    require_order(
        "shared batch assignment happens before concurrent workers",
        upload_queue,
        "assignSharedUploadBatchId(batchScopedItems);",
        "await Promise.all(",
    )

    require_tokens(
        "operator smoke workflow trigger",
        workflow,
        [
            "scripts/test_multi_upload_batch_contract.py",
            "mobile/src/features/operator/lib/uploadQueue.ts",
            "mobile/src/features/operator/lib/uploadQueue.test.ts",
            "web-api/src/app/api/operator/upload/route.ts",
            "Validate Multi-upload batch contract",
        ],
    )

    print("Multi-upload batch contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
