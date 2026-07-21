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
        index = text.find(token, cursor + 1)
        if index < 0:
            raise SystemExit(f"{label} missing ordered token: {token!r}")
        if index <= cursor:
            raise SystemExit(f"{label} has incorrect order around: {token!r}")
        cursor = index


def block(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def main() -> int:
    r2 = read("web-api/src/lib/r2-storage.ts")
    init_route = read("web-api/src/app/api/operator/upload/route.ts")
    lifecycle_route = read("web-api/src/app/api/operator/upload/multipart/route.ts")
    verify_route = read("web-api/src/app/api/operator/upload/verify/route.ts")
    mobile = read("mobile/src/features/operator/lib/resumableMultipartUpload.ts")
    pipeline = read("mobile/src/app/(operator)/pipeline.tsx")
    audit = read("docs/audit/remaining-gaps-official-reference-audit-20260721.md")
    workflow = read(".github/workflows/operator-smoke-check.yml")

    ast.parse(read("scripts/test_r2_multipart_upload_contract.py"))

    require(
        "official-reference audit",
        audit,
        [
            "Cloudflare R2",
            "multipart",
            "presigned",
            "Expo",
            "AWS",
        ],
    )

    require(
        "R2 official multipart limits",
        r2,
        [
            "MIN_MULTIPART_PART_SIZE = 5 * MIB",
            "DEFAULT_MULTIPART_PART_SIZE = 8 * MIB",
            "MAX_MULTIPART_PARTS = 10_000",
            "Math.ceil(knownBytes / MAX_MULTIPART_PARTS)",
        ],
    )
    require(
        "idempotent multipart initialization",
        r2,
        [
            "objectIdentity(",
            "verifyR2Object(identity.key)",
            "findActiveMultipartUpload(identity.key)",
            "new URLSearchParams({ uploads: '' })",
            "already_complete: true",
            "reused: true",
        ],
    )
    ordered(
        "multipart initialization checks object and active upload before creating",
        block(r2, "export async function createR2MultipartUpload", "export function createR2MultipartPartUrl"),
        [
            "verifyR2Object(identity.key)",
            "findActiveMultipartUpload(identity.key)",
            "signedFetch(",
        ],
    )

    require(
        "part URL and authoritative reconciliation",
        r2,
        [
            "new URLSearchParams({",
            "partNumber: String(partNumber)",
            "uploadId,",
            "listR2MultipartParts",
            "part-number-marker",
            "NextPartNumberMarker",
            "parts.sort((left, right) => left.partNumber - right.partNumber)",
        ],
    )

    complete_block = block(r2, "export async function completeR2MultipartUpload", "export async function abortR2MultipartUpload")
    require(
        "server-authoritative completion",
        complete_block,
        [
            "const status = await getR2MultipartStatus(key, uploadId)",
            "const parts = validateCompleteParts(status.parts, expectedSizeBytes)",
            "part.etag",
            "CompleteMultipartUpload",
            "verifyR2Object(key)",
            "verified.size === expectedSizeBytes",
        ],
    )
    forbid(
        "completion must not trust client-provided ETags",
        lifecycle_route,
        [
            "parts?:",
            "body.parts",
            "etag?:",
            "body.etag",
        ],
    )
    require(
        "part and total validation",
        r2,
        [
            "Multipart upload is missing part",
            "smaller than 5 MiB",
            "All non-final multipart parts must use the same byte size",
            "The final multipart part cannot be larger",
            "Multipart byte total mismatch",
        ],
    )

    require(
        "authenticated lifecycle endpoint",
        lifecycle_route,
        [
            "requireOperator(req)",
            "enforceRateLimit",
            "isSafeRawR2Key",
            "action === 'status'",
            "action === 'part_url'",
            "action === 'complete'",
            "abortR2MultipartUpload",
        ],
    )
    ordered(
        "part URL checks R2 state before signing",
        block(lifecycle_route, "if (action === 'part_url')", "if (action === 'complete')"),
        [
            "getR2MultipartStatus(key, uploadId)",
            "status.state === 'missing'",
            "status.state === 'completed'",
            "createR2MultipartPartUrl",
        ],
    )

    require(
        "mobile bounded reader",
        mobile,
        [
            "FileSystem.readAsStringAsync(sourceUri",
            "FileSystem.EncodingType.Base64",
            "position: offset",
            "length,",
            "const bytes = decode(encoded)",
            "bytes.byteLength",
        ],
    )
    forbid(
        "mobile multipart path must remain bounded",
        mobile,
        [
            "FileSystem.copyAsync",
            "FileSystem.createUploadTask",
            ".slice(",
            ".bytesSync(",
        ],
    )

    require(
        "persisted resume state",
        mobile,
        [
            "RECORD_PREFIX",
            "ACTIVE_BATCH_KEY",
            "uploadId: string",
            "parts: MultipartUploadPart[]",
            "status: 'uploading' | 'failed' | 'verified'",
            "AsyncStorage.setItem(recordKey(record.clientUploadId)",
            "AsyncStorage.multiGet(keys)",
            "loadActiveMultipartBatch",
            "clearPersistedMultipartBatch",
        ],
    )
    ordered(
        "each completed part is saved before the next loop iteration",
        block(mobile, "for (let partNumber = 1", "const finalStatus = await serverStatus"),
        [
            "const uploaded = await uploadPart",
            "record.parts = normalizedParts",
            "await saveRecord(record)",
            "input.onProgress?.",
        ],
    )
    require(
        "fresh URL and part-only retry",
        mobile,
        [
            "return withRetry(async () =>",
            "action: 'part_url'",
            "fetch(signed.upload_url, { method: 'PUT', body: bytes })",
            "PART_UPLOAD_ATTEMPTS = 3",
            "response.headers.get('etag')",
            "authoritativeUploadedPart",
        ],
    )

    require(
        "pipeline persistence integration",
        pipeline,
        [
            "loadActiveMultipartBatch()",
            "Interrupted upload ready to resume",
            "resumeMultipartUpload({",
            "clearPersistedMultipartBatch(finishedBatch)",
            "Pipeline start is blocked until every selected upload is verified.",
        ],
    )
    ordered(
        "persisted state clears only after dispatch",
        block(pipeline, "const runPipeline", "const confirmReset"),
        [
            "operatorFetch<PipelineDispatchResponse>",
            "const finishedBatch",
            "clearPersistedMultipartBatch(finishedBatch)",
            "setUploadItems([])",
        ],
    )

    require(
        "exact legacy object verification",
        verify_route,
        [
            "expected_size_bytes?: number",
            "const sizeMatches",
            "result.exists && sizeMatches",
            "status: result.exists && sizeMatches ? 200 : result.exists ? 409 : 404",
        ],
    )
    require(
        "multipart init request",
        init_route,
        [
            "upload_mode?: 'resilient_batch_item' | 'multipart_resumable'",
            "source_size_bytes?: number",
            "createR2MultipartUpload(",
            "multipart_upload_id",
            "part_size_bytes",
        ],
    )

    require(
        "CI wiring",
        workflow,
        [
            "scripts/test_r2_multipart_upload_contract.py",
            "Validate R2 multipart resumable upload contract",
        ],
    )

    print("R2 multipart resumable upload contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
