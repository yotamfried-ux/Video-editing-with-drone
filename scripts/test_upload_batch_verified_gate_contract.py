#!/usr/bin/env python3
"""Contract for durable upload membership and verified pipeline admission."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, source: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise SystemExit(f"{label} missing: {missing}")


def require_order(label: str, source: str, tokens: list[str]) -> None:
    positions = [source.index(token) for token in tokens]
    if positions != sorted(positions):
        raise SystemExit(f"{label} order is unsafe: {tokens}")


def main() -> int:
    migration = read("supabase/migrations/20260723_upload_batch_verified_gate.sql")
    helper = read("web-api/src/lib/upload-batch-manifest.ts")
    multipart_start = read("web-api/src/app/api/operator/upload/multipart/start/route.ts")
    single_start = read("web-api/src/app/api/operator/upload/route.ts")
    batch_route = read("web-api/src/app/api/operator/upload/batch/route.ts")
    pipeline_start = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    pipeline_post = pipeline_start[pipeline_start.index("export async function POST"):]

    require(
        "upload batch migration",
        migration,
        [
            "create table if not exists public.upload_batches",
            "expected_file_count",
            "actual_file_count",
            "verified_file_count",
            "cleanup_pending_count",
            "input_manifest",
            "pipeline_run_id uuid references public.pipeline_runs",
            "register_upload_batch",
            "refresh_upload_batch_state",
            "source_uploads_refresh_batch",
            "verified_size_bytes = source_size_bytes",
            "local_cleanup_status <> 'confirmed'",
            "v_actual = v_batch.expected_file_count",
            "v_verified = v_batch.expected_file_count",
            "v_cleanup_pending = 0",
            "assert_upload_batch_ready",
            "jsonb_array_length(v_manifest) <> v_expected",
            "mark_upload_batch_running",
            "enable row level security",
            "service_role",
        ],
    )

    require(
        "batch resolver helper",
        helper,
        [
            "uniqueBatchIdForStates",
            ".limit(2)",
            "Multiple durable upload batches are active",
            "resolveUploadBatchId",
            "resolveReadyUploadBatchId",
            "No unique size-verified upload batch is ready",
            "registerUploadBatch",
            "refreshUploadBatch",
            "removeSourceUploadsAfterSetupFailure",
            "assertUploadBatchReady",
            "markUploadBatchRunning",
            "releaseUploadBatchAfterDispatchFailure",
        ],
    )

    require(
        "multipart batch registration",
        multipart_start,
        [
            "resolveUploadBatchId",
            "createSourceUploadManifests",
            "attachMultipartSession",
            "registerUploadBatch",
            "additionalFileCount: 1",
            "sourceKind: 'android_external'",
            "removeSourceUploadsAfterSetupFailure",
        ],
    )
    require_order(
        "multipart setup",
        multipart_start,
        [
            "createSourceUploadManifests",
            "attachMultipartSession",
            "registerUploadBatch",
        ],
    )

    require(
        "single PUT batch registration",
        single_start,
        [
            "resolveUploadBatchId",
            "createSourceUploadManifests",
            "registerUploadBatch",
            "additionalFileCount: files.length",
            "sourceKind: 'gallery'",
            "removeSourceUploadsAfterSetupFailure",
        ],
    )

    require(
        "explicit batch endpoint",
        batch_route,
        [
            "additional_file_count",
            "registerUploadBatch",
            "source_kind",
            "grouping_kind",
        ],
    )

    require(
        "pipeline verified batch gate",
        pipeline_start,
        [
            "resolveReadyUploadBatchId",
            "assertUploadBatchReady",
            "input_files: readyBatch.inputManifest",
            "input_manifest_frozen: true",
            "markUploadBatchRunning",
            "releaseUploadBatchAfterDispatchFailure",
            "expected_file_count: readyBatch.expectedFileCount",
        ],
    )
    require_order(
        "pipeline admission",
        pipeline_post,
        [
            "resolveReadyUploadBatchId",
            "assertUploadBatchReady",
            ".from('pipeline_runs')",
            "markUploadBatchRunning",
            "api.github.com/repos",
        ],
    )

    print("Durable verified upload batch gate contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
