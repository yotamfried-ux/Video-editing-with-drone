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
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    ast.parse(_read("scripts/test_multi_upload_batch_contract.py"))

    require_tokens(
        "upload route batch API",
        upload_route,
        [
            "MAX_BATCH_FILES",
            "files?: UploadFileInput[]",
            "normalizeUploadFiles",
            "uploadFilename",
            "String(index + 1).padStart(3, '0')",
            "operator-upload-batch",
            "safeBatchId(requestedBatchId) || newBatchId()",
            "const uploads = files.map",
            "createR2UploadUrl(file.uploadFilename, batchId)",
            "await Promise.all(",
            "createUploadSession(file.uploadFilename, rawFolder, file.mimeType)",
            "source_filename: file.filename",
            "uploads,",
            "storage_key: upload.key",
        ],
    )
    require_order(
        "upload route parses files before rate limit",
        upload_route,
        "const files = normalizeUploadFiles(body);",
        "const limited = await enforceRateLimit",
    )
    require_no_tokens(
        "upload route must not hard-limit every selected file as its own hourly request",
        upload_route,
        [
            "enforceRateLimit(req, 'operator-upload', 10, 3600);\n  if (limited) return limited;",
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
            "Promise.allSettled",
            "files: items.map",
            "uploadInit.uploads?.length",
            "uploadAssetToSession",
            "retryUploadItem",
            "Upload batch progress",
            "Retry",
            "Uploading ${verifiedUploads}/${uploadItems.length}",
        ],
    )
    require_no_tokens(
        "mobile must not select only one asset",
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
            "Validate Multi-upload batch contract",
        ],
    )

    print("Multi-upload batch contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
