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
    r2 = read("web-api/src/lib/r2-storage.ts")
    init_route = read("web-api/src/app/api/operator/upload/route.ts")
    lifecycle_route = read("web-api/src/app/api/operator/upload/multipart/route.ts")
    verify_route = read("web-api/src/app/api/operator/upload/verify/route.ts")
    mobile = read("mobile/src/features/operator/lib/resumableMultipartUpload.ts")
    pipeline = read("mobile/src/app/(operator)/pipeline.tsx")
    audit = read("docs/audit/remaining-gaps-official-reference-audit-20260721.md")
    workflow = read(".github/workflows/r2-multipart-upload-contract.yml")
    live_test = read("scripts/test_r2_multipart_live.py")

    ast.parse(read("scripts/test_r2_multipart_upload_contract.py"))
    ast.parse(live_test)

    require("official-reference audit", audit, ["Cloudflare R2", "multipart", "presigned", "Expo", "AWS"])
    require("official limits", r2, [
        "MIN_MULTIPART_PART_SIZE = 5 * MIB",
        "DEFAULT_MULTIPART_PART_SIZE = 8 * MIB",
        "MAX_MULTIPART_PARTS = 10_000",
        "Math.ceil(knownBytes / MAX_MULTIPART_PARTS)",
    ])
    init_block = block(r2, "export async function createR2MultipartUpload", "export function createR2MultipartPartUrl")
    require("idempotent init", init_block, [
        "objectIdentity(",
        "verifyR2Object(identity.key)",
        "const expectedBytes = Number.isSafeInteger(totalBytes)",
        "object.exists && (expectedBytes === null || object.size === expectedBytes)",
        "findActiveMultipartUpload(identity.key)",
        "new URLSearchParams({ uploads: '' })",
        "already_complete: true",
        "reused: true",
        "A stable key can contain a truncated object",
        "existing_size_bytes: object.exists ? object.size : null",
    ])
    ordered(
        "init order",
        init_block,
        ["verifyR2Object(identity.key)", "findActiveMultipartUpload(identity.key)", "signedFetch("],
    )

    require("part reconciliation", r2, [
        "partNumber: String(partNumber)",
        "listR2MultipartParts",
        "part-number-marker",
        "NextPartNumberMarker",
        "parts.sort((left, right) => left.partNumber - right.partNumber)",
    ])
    complete = block(r2, "export async function completeR2MultipartUpload", "export async function abortR2MultipartUpload")
    require("server-authoritative complete", complete, [
        "const status = await getR2MultipartStatus(key, uploadId)",
        "const parts = validateCompleteParts(status.parts, expectedSizeBytes)",
        "part.etag",
        "CompleteMultipartUpload",
        "verifyR2Object(key)",
        "verified.size === expectedSizeBytes",
    ])
    forbid("no client ETag trust", lifecycle_route, ["parts?:", "body.parts", "etag?:", "body.etag"])
    require("part validation", r2, [
        "Multipart upload is missing part",
        "smaller than 5 MiB",
        "All non-final multipart parts must use the same byte size",
        "The final multipart part cannot be larger",
        "Multipart byte total mismatch",
    ])

    require("authenticated lifecycle", lifecycle_route, [
        "requireOperator(req)",
        "enforceRateLimit(req, 'operator-upload-multipart-lifecycle', 25_000, 3600)",
        "isSafeRawR2Key",
        "action === 'status'",
        "action === 'part_url'",
        "action === 'complete'",
        "abortR2MultipartUpload",
    ])
    part_url = block(lifecycle_route, "if (action === 'part_url')", "if (action === 'complete')")
    require("fresh part URL", part_url, ["createR2MultipartPartUrl(key, uploadId, partNumber)", "expires_in_seconds: 3600"])
    forbid("part URL must stay O(1)", part_url, ["getR2MultipartStatus", "listR2MultipartParts", "ListParts"])

    require("bounded mobile reader", mobile, [
        "FileSystem.readAsStringAsync(sourceUri",
        "FileSystem.EncodingType.Base64",
        "while (remaining > 0)",
        "position: cursor",
        "length: remaining",
        "const buffer = decode(encoded)",
        "const combined = new Uint8Array(length)",
    ])
    forbid("no whole-file multipart materialization", mobile, ["FileSystem.copyAsync", "FileSystem.createUploadTask", ".slice(", ".bytesSync("])
    require("persisted resume", mobile, [
        "RECORD_PREFIX",
        "ACTIVE_BATCH_KEY",
        "uploadId: string",
        "parts: MultipartUploadPart[]",
        "status: 'uploading' | 'failed' | 'verified'",
        "AsyncStorage.setItem(recordKey(record.clientUploadId)",
        "AsyncStorage.multiGet(keys)",
        "loadActiveMultipartBatch",
        "clearPersistedMultipartBatch",
        "cleanupStagedSource",
        "abortPersistedMultipartUpload",
    ])
    ordered(
        "persist after each part",
        block(mobile, "for (let partNumber = 1", "const finalStatus = await serverStatus"),
        ["const uploaded = await uploadPart", "record.parts = normalizedParts", "await saveRecord(record)", "input.onProgress?."],
    )
    require("fresh part URL retry", mobile, [
        "return withRetry(async () =>",
        "action: 'part_url'",
        "fetch(signed.upload_url, { method: 'PUT', body: bytes })",
        "PART_UPLOAD_ATTEMPTS = 3",
        "response.status === 404",
        "Multipart upload no longer exists",
        "response.headers.get('etag')",
        "authoritativeUploadedPart",
    ])

    require("SAF staging", pipeline, [
        "const prepareMultipartSource",
        "expo-file-system 18 reports content:// size through InputStream.available()",
        "sportreel-multipart-",
        "FileSystem.copyAsync({ from: item.uri, to: stableUri })",
        "Cannot determine the exact staged source size",
        "sourceUri: source!.uri",
        "sourceSizeBytes: source!.size",
        "staged copy is kept only until verification or Discard",
    ])
    require("pipeline integration", pipeline, [
        "loadActiveMultipartBatch()",
        "Interrupted upload ready to resume",
        "resumeMultipartUpload({",
        "clearPersistedMultipartBatch(finishedBatch)",
        "Pipeline start is blocked until every selected upload is verified.",
    ])
    ordered(
        "clear only after dispatch",
        block(pipeline, "const runPipeline", "const confirmReset"),
        ["operatorFetch<PipelineDispatchResponse>", "const finishedBatch", "clearPersistedMultipartBatch(finishedBatch)", "setUploadItems([])"],
    )

    require("exact legacy verify", verify_route, [
        "expected_size_bytes?: number",
        "const sizeMatches",
        "result.exists && sizeMatches",
        "status: result.exists && sizeMatches ? 200 : result.exists ? 409 : 404",
    ])
    require("multipart init response", init_route, [
        "upload_mode?: 'resilient_batch_item' | 'multipart_resumable'",
        "source_size_bytes?: number",
        "createR2MultipartUpload(",
        "multipart_upload_id",
        "part_size_bytes",
    ])
    require("live restart integration", live_test, [
        "phase_init",
        "upload_part(state, 1)",
        "phase_resume",
        "Server restart did not reuse the original multipart upload_id",
        "expected_size_bytes': TOTAL_BYTES",
        "head_object",
        "phase_cleanup",
    ])
    require("CI wiring", workflow, [
        "scripts/test_r2_multipart_upload_contract.py",
        "Validate R2 multipart resumable upload contract",
        "Type-check Web API multipart implementation",
        "Type-check mobile multipart implementation",
        "Upload mobile typecheck diagnostics",
        "Test multipart resume across server restart",
        "r2-multipart-live-diagnostics",
    ])

    print("R2 multipart resumable upload contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
