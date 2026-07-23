#!/usr/bin/env python3
"""Deterministic contract for the large drone-video upload foundation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise AssertionError(f"{label} missing: {missing}")


def forbid(source: str, tokens: list[str], label: str) -> None:
    present = [token for token in tokens if token in source]
    if present:
        raise AssertionError(f"{label} contains forbidden patterns: {present}")


def test_durable_multipart_schema() -> None:
    schema = read("supabase/migrations/20260723_source_upload_multipart_foundation.sql")
    cleanup_schema = read("supabase/migrations/20260723_source_upload_local_cleanup_evidence.sql")
    require(
        schema,
        [
            "source_upload_parts",
            "primary key (source_upload_id, part_number)",
            "part_size_bytes is null or part_size_bytes >= 5242880",
            "expected_part_count between 1 and 10000",
            "attach_source_multipart_session",
            "record_source_upload_part",
            "begin_source_upload_completion",
            "order by part_number asc",
            "v_total <> v_upload.source_size_bytes",
            "mark_source_upload_aborted",
            "local_cleanup_status",
            "enable row level security",
            "service_role",
        ],
        "multipart migration",
    )
    require(
        cleanup_schema,
        [
            "local_cleanup_artifact_count",
            "local_cleanup_reclaimed_bytes",
            "local_cleanup_source_preserved",
            "p_source_preserved is distinct from true",
            "record_source_upload_local_cleanup_evidence",
        ],
        "cleanup evidence migration",
    )


def test_r2_multipart_protocol() -> None:
    storage = read("web-api/src/lib/r2-storage.ts")
    require(
        storage,
        [
            "R2_MIN_MULTIPART_PART_SIZE = 5 * 1024 * 1024",
            "R2_MAX_MULTIPART_PARTS = 10_000",
            "createR2MultipartUpload",
            "createR2MultipartPartUploadUrl",
            "completeR2MultipartUpload",
            "abortR2MultipartUpload",
            "partNumber",
            "uploadId",
            "sorted = [...parts].sort",
            "Duplicate multipart part number",
            "<CompleteMultipartUpload>",
            "x-amz-content-sha256",
        ],
        "R2 multipart implementation",
    )
    forbid(
        storage,
        [
            "multipartEtag === sourceMd5",
            "multipart_etag_is_source_md5: true",
        ],
        "R2 checksum policy",
    )


def test_api_requires_durable_completion_and_cleanup() -> None:
    start = read("web-api/src/app/api/operator/upload/multipart/start/route.ts")
    part_url = read("web-api/src/app/api/operator/upload/multipart/part-url/route.ts")
    record_part = read("web-api/src/app/api/operator/upload/multipart/record-part/route.ts")
    complete = read("web-api/src/app/api/operator/upload/multipart/complete/route.ts")
    abort = read("web-api/src/app/api/operator/upload/multipart/abort/route.ts")
    cleanup = read("web-api/src/app/api/operator/upload/multipart/cleanup/route.ts")
    status = read("web-api/src/app/api/operator/upload/multipart/status/route.ts")

    require(start, ["sourceSizeBytes", "expectedPartCount", "createR2MultipartUpload", "createSourceUploadManifests", "attachMultipartSession"], "start endpoint")
    require(part_url, ["getMultipartSession", "createR2MultipartPartUploadUrl", "size_bytes"], "part URL endpoint")
    require(record_part, ["The exact R2 ETag is required", "recordMultipartPart"], "part record endpoint")
    require(
        complete,
        [
            "beginMultipartCompletion",
            "completeR2MultipartUpload",
            "verifyR2Object",
            "markSourceUploadVerified",
            "recovered_existing_object",
            "multipart_etag_is_source_md5: false",
            "cleanup_confirmation_endpoint",
        ],
        "complete endpoint",
    )
    require(abort, ["abortR2MultipartUpload", "markMultipartAborted", "cleanup_confirmation_endpoint"], "abort endpoint")
    require(
        cleanup,
        [
            "artifact_count",
            "reclaimed_bytes",
            "source_preserved",
            "source_preserved !== true",
            "recordLocalCleanup",
        ],
        "cleanup endpoint",
    )
    require(status, ["completed_parts", "local_cleanup_reclaimed_bytes", "local_cleanup_source_preserved"], "status endpoint")


def test_phone_cleanup_never_targets_sd_source() -> None:
    cleanup = read("mobile/src/features/operator/lib/uploadLocalCleanup.ts")
    require(
        cleanup,
        [
            "SPORTREEL_UPLOAD_CACHE_PREFIX",
            "isSportReelOwnedUploadTempUri",
            "!uri.startsWith('file://')",
            "Refusing to delete non-SportReel upload artifact",
            "Refusing to delete the selected SD / USB source",
            "FileSystem.deleteAsync(uri, { idempotent: true })",
            "Temporary upload artifact still exists after deletion",
            "await assertSourcePreserved(input.sourceUri, input.expectedSourceSize)",
            "sweepStaleSportReelUploadArtifacts",
            "activeTemporaryUris",
        ],
        "mobile cleanup helper",
    )
    forbid(
        cleanup,
        [
            "deleteAsync(input.sourceUri",
            "deleteAsync(sourceUri",
            "moveAsync({ from: input.sourceUri",
            "copyAsync({ from: input.sourceUri",
        ],
        "SD source safety",
    )


def test_android_reader_is_bounded_and_seekable() -> None:
    config = read("mobile/modules/sportreel-source-reader/expo-module.config.json")
    kotlin = read("mobile/modules/sportreel-source-reader/android/src/main/java/expo/modules/sportreelsourcereader/SportReelSourceReaderModule.kt")
    typescript = read("mobile/modules/sportreel-source-reader/src/SportReelSourceReaderModule.ts")
    workflow = read(".github/workflows/large-upload-foundation-check.yml")

    require(
        config,
        [
            '"platforms": ["android"]',
            "expo.modules.sportreelsourcereader.SportReelSourceReaderModule",
        ],
        "source reader module config",
    )
    require(
        kotlin,
        [
            "MAX_RANGE_BYTES = 64 * 1024 * 1024",
            "ContentResolver.SCHEME_CONTENT",
            "openFileDescriptor(uri, \"r\")",
            "Os.lseek",
            "channel.position(offset)",
            "ByteArray(length)",
            "ParcelFileDescriptor.AutoCloseInputStream(descriptor).use",
            "source_not_seekable",
            "source_changed_or_truncated",
        ],
        "bounded Android source reader",
    )
    forbid(
        kotlin,
        [
            "Base64",
            "copyTo(",
            "readBytes()",
            "FileOutputStream",
        ],
        "bounded Android source reader",
    )
    require(
        typescript,
        [
            "requireOptionalNativeModule",
            "Promise<Uint8Array>",
            "getSportReelSourceReader",
            "matching EAS build",
            "inspectSource",
            "readRange",
        ],
        "source reader TypeScript bridge",
    )
    require(
        workflow,
        [
            "mobile/modules/sportreel-source-reader/**",
            "expo-modules-autolinking resolve --platform android",
            "SportReelSourceReaderModule",
        ],
        "source reader CI wiring",
    )


def test_plan_uses_verified_primary_sources() -> None:
    plan = read("docs/audit/drone-large-upload-experiment-entry-plan-20260723.md")
    require(
        plan,
        [
            "must never delete, rename, move, or overwrite the original `content://` source",
            "Immediately after durable verification",
            "verify absence after deletion",
            "must not require a complete local copy",
            "source_not_seekable",
            "Cloudflare R2",
            "Expo SDK 52 compatibility decision",
            "ContentResolver",
            "Uint8Array",
            "Prove phone storage does not grow by the full source size",
        ],
        "experiment-entry plan",
    )


def main() -> None:
    tests = [
        test_durable_multipart_schema,
        test_r2_multipart_protocol,
        test_api_requires_durable_completion_and_cleanup,
        test_phone_cleanup_never_targets_sd_source,
        test_android_reader_is_bounded_and_seekable,
        test_plan_uses_verified_primary_sources,
    ]
    for test in tests:
        test()
        print(f"PASS: {test.__name__}")
    print(f"PASS: {len(tests)} large-upload foundation contracts")


if __name__ == "__main__":
    main()
