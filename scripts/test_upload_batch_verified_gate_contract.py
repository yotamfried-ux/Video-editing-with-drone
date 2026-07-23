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
    idempotency = read("supabase/migrations/20260723_upload_start_idempotency.sql")
    size_evidence = read("supabase/migrations/20260723_single_put_size_evidence.sql")
    helper = read("web-api/src/lib/upload-batch-manifest.ts")
    multipart_manifest = read("web-api/src/lib/multipart-upload-manifest.ts")
    multipart_start = read("web-api/src/app/api/operator/upload/multipart/start/route.ts")
    multipart_setup = multipart_start[multipart_start.index("orphanMultipartUploadId = await"):]
    single_start = read("web-api/src/app/api/operator/upload/route.ts")
    batch_route = read("web-api/src/app/api/operator/upload/batch/route.ts")
    pipeline_start = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    pipeline_post = pipeline_start[pipeline_start.index("export async function POST"):]
    mobile_ledger = read("mobile/src/features/operator/lib/multipartUploadLedger.ts")
    mobile_client = read("mobile/src/features/operator/lib/multipartUploadClient.ts")

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
        "single PUT size evidence migration",
        size_evidence,
        [
            "source_size_evidence",
            "r2_head_adopted",
            "v_upload.upload_protocol <> 'single_put'",
            "source_size_bytes = p_verified_size_bytes",
            "verified_at = coalesce(verified_at, now())",
        ],
    )

    require(
        "idempotent source membership migration",
        idempotency,
        [
            "client_upload_id",
            "source_uploads_client_upload_id_unique_idx",
            "batch_membership_registered_at",
            "register_source_upload_batch_membership",
            "v_upload.batch_membership_registered_at is null",
            "register_upload_batch",
            "refresh_upload_batch_state",
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
        "atomic multipart manifest",
        multipart_manifest,
        [
            "createMultipartSourceManifest",
            "client_upload_id: input.clientUploadId",
            "upload_protocol: 'r2_multipart_v1'",
            "findMultipartSessionByClientUploadId",
            "registerMultipartBatchMembership",
            "register_source_upload_batch_membership",
            "error?.code === '23505'",
        ],
    )

    require(
        "multipart batch registration",
        multipart_start,
        [
            "client_upload_id",
            "findMultipartSessionByClientUploadId",
            "resolveUploadBatchId",
            "createMultipartSourceManifest",
            "registerMultipartBatchMembership",
            "resumed_existing_start",
            "orphanMultipartUploadId",
            "Once the durable source row owns the R2 UploadId",
        ],
    )
    if "removeSourceUploadsAfterSetupFailure" in multipart_start:
        raise SystemExit("multipart start must preserve a durable recoverable source row")
    require_order(
        "multipart setup",
        multipart_setup,
        [
            "createR2MultipartUpload",
            "createMultipartSourceManifest",
            "registerMultipartBatchMembership",
        ],
    )

    require(
        "mobile start idempotency",
        mobile_ledger + mobile_client,
        [
            "pendingStarts",
            "getOrCreatePendingMultipartStart",
            "removePendingMultipartStart",
            "client_upload_id: pendingStart.requestId",
            "started.client_upload_id !== pendingStart.requestId",
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
