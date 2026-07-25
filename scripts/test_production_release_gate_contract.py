#!/usr/bin/env python3
"""Deterministic fail-closed contract for GAP-023 production release gating."""
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
        raise AssertionError(f"{label} contains fail-open patterns: {present}")


def require_order(source: str, tokens: list[str], label: str) -> None:
    positions = [source.index(token) for token in tokens]
    if positions != sorted(positions):
        raise AssertionError(f"{label} has unsafe order: {tokens}")


def main() -> int:
    workflow = read(".github/workflows/upload-foundation-release.yml")
    migration_runner = read("scripts/apply_upload_release_migrations.py")
    schema = read("scripts/verify_upload_release_schema.sql")
    membership = read("supabase/migrations/20260723_upload_start_idempotency.sql")
    deploy = read("scripts/verify_production_deployment.py")
    smoke = read("scripts/test_production_upload_api_smoke.py")
    r2 = read("scripts/test_real_r2_multipart_upload.py")
    cors = read("scripts/verify_r2_cors.py")
    eas = read("scripts/record_eas_build_evidence.py")
    status_route = read("web-api/src/app/api/operator/upload/multipart/status/route.ts")
    app = read("mobile/app.json")

    require(
        workflow,
        [
            "workflow_dispatch:",
            "confirm_release",
            "confirm_biometric_removal",
            "environment: production",
            "refs/heads/main",
            "Verify required secret and variable names without printing values",
            "verify-production-deployment:",
            "migrate-and-verify:",
            "real-r2-probe:",
            "production-api-smoke:",
            "build-android-preview:",
            "needs: production-api-smoke",
            "if-no-files-found: error",
            "retention-days: 30",
        ],
        "release workflow",
    )
    require_order(
        workflow,
        [
            "preflight:",
            "verify-production-deployment:",
            "migrate-and-verify:",
            "real-r2-probe:",
            "production-api-smoke:",
            "build-android-preview:",
        ],
        "release job order",
    )
    forbid(workflow, ["continue-on-error: true", "|| true", "if-no-files-found: ignore"], "release workflow")

    require(
        migration_runner,
        [
            'required("SUPABASE_DB_URL")',
            "CONFIRM_BIOMETRIC_REMOVAL",
            "REMOVE_BIOMETRICS",
            "Migration checksum drift",
            "check=True",
            "--check-only",
            "20260721_remove_face_recognition.sql",
            "20260723_upload_start_idempotency.sql",
            "sportreel_release_migrations",
        ],
        "migration runner",
    )
    require_order(
        migration_runner,
        [
            '"20260721_remove_face_recognition.sql"',
            '"20260723_source_upload_exact_dedup.sql"',
            '"20260723_source_upload_multipart_foundation.sql"',
            '"20260723_single_put_size_evidence.sql"',
            '"20260723_source_upload_local_cleanup_evidence.sql"',
            '"20260723_upload_batch_verified_gate.sql"',
            '"20260723_upload_start_idempotency.sql"',
        ],
        "migration dependency order",
    )

    require(
        membership,
        [
            "pg_advisory_xact_lock",
            "v_actual_file_count - v_batch.expected_file_count",
            "v_unreserved_count > 0",
            "greatest(v_actual_file_count, 1)",
            "batch_membership_registered_at is null",
        ],
        "exactly-once reserved batch membership",
    )

    require(
        schema,
        [
            "column:source_uploads.client_upload_id:text",
            "constraint:source_uploads_status_check",
            "fk:source_upload_parts.source_upload_id",
            "index:source_uploads_client_upload_id_unique_idx",
            "rls:source_uploads",
            "policy:upload_tables:no_client_policies",
            "grant:anon:no_upload_table_dml",
            "grant:authenticated:no_upload_table_dml",
            "grant:public:no_upload_table_dml",
            "grant:service_role:upload_tables",
            "grant:client:no_upload_rpc_execute",
            "grant:service_role:upload_rpc_execute",
            "migration-ledger:all-release-files",
            "removed:athlete_profiles.face_embedding",
            "removed:storage_bucket:athlete-photos",
            "case when ok then 'true' else 'false' end",
        ],
        "schema verifier",
    )

    require(
        deploy,
        [
            'required("VERCEL_TOKEN")',
            "No READY Vercel production deployment found",
            "does not contain required commit",
            "is not assigned to deployment",
            "Missing Vercel Production environment variable names",
            "minimum_commit_contained",
            "production_domain_alias_matches",
            "checked_environment_variable_values",
        ],
        "Vercel verifier",
    )
    require(
        smoke,
        [
            "non_operator_missing_auth_rejected",
            "non_operator_wrong_auth_rejected",
            "malformed_input_rejected",
            "cross_batch_start_mismatch_rejected",
            "cross_batch_status_mismatch_rejected",
            "raw_key_status_mismatch_rejected",
            "multipart_abort_confirmed",
            "cleanup_confirmation_recorded",
            "durable_db_state_verified",
            "fixture_cleanup",
            "Production smoke cleanup failed",
        ],
        "production API smoke",
    )
    require(
        status_route,
        [
            "expectedBatchId",
            "expectedStorageKey",
            "Multipart upload batch mismatch",
            "Multipart upload storage key mismatch",
            "status: 409",
        ],
        "status correlation guard",
    )

    require(
        r2,
        [
            "first_etag",
            "completion_etag",
            "latest_successful_etag_used",
            "completion_part_numbers_ascending",
            "multipart_etag_is_not_file_md5",
            "Completed multipart ETag was incorrectly equal",
            "Downloaded R2 object SHA-256 does not match",
            "object still exists after delete",
            "Cleanup failures:",
        ],
        "real R2 probe",
    )
    require(
        cors,
        [
            "native_android_upload_client",
            'required("CLOUDFLARE_API_TOKEN")',
            "wildcard origin",
            "exact origin with PUT and exposed ETag",
        ],
        "R2 CORS verifier",
    )
    require(
        eas,
        [
            "EAS build is not finished successfully",
            "EAS build platform is not ANDROID",
            "EAS build profile is not preview",
            "EAS build commit mismatch",
            "EAS build channel mismatch",
            "artifact_sha256",
            '"installed_on_device": False',
            '"SportReelSourceReader"',
        ],
        "EAS evidence verifier",
    )
    forbid(
        app,
        [
            "capture your face photo for highlight reel matching",
            "select your face photo for highlight reel matching",
        ],
        "mobile permission copy",
    )

    print("PASS: production release gate is ordered, evidence-producing, and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
