#!/usr/bin/env python3
"""Negative, deterministic fail-closed checks for the production release gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise AssertionError(f"{label} missing negative gates: {missing}")


def expect_failure(command: list[str], env: dict[str, str], label: str) -> None:
    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if completed.returncode == 0:
        raise AssertionError(f"{label} unexpectedly succeeded")


def main() -> int:
    workflow = read(".github/workflows/upload-foundation-release.yml")
    schema = read("scripts/verify_upload_release_schema.sql")
    migration = read("scripts/apply_upload_release_migrations.py")
    deployment = read("scripts/verify_production_deployment.py")
    r2 = read("scripts/test_real_r2_multipart_upload.py")
    eas = read("scripts/record_eas_build_evidence.py")
    smoke = read("scripts/test_production_upload_api_smoke.py")

    require(workflow, [
        "Missing required GitHub Actions secret/variable names",
        "confirm_release must equal RELEASE",
        "confirm_biometric_removal must equal REMOVE_BIOMETRICS",
        "Upload release schema verifier returned false",
        "Core schema or biometric-removal verifier returned false",
        "needs: verify-production-deployment",
        "needs: migrate-and-verify",
        "needs: real-r2-probe",
        "needs: production-api-smoke",
        "Expected EAS CLI 18.9.1",
        "Pinned EAS CLI does not support build:download --build-id.",
        "if-no-files-found: error",
    ], "workflow fail-closed ordering and EAS compatibility")
    require(schema, [
        "constraint:source_uploads_status_check",
        "rls:source_uploads",
        "policy:upload_tables:no_client_policies",
        "grant:anon:no_upload_table_dml",
        "grant:authenticated:no_upload_table_dml",
        "grant:public:no_upload_table_dml",
        "grant:client:no_upload_rpc_execute",
        "removed:storage_bucket:athlete-photos",
        "case when ok then 'true' else 'false' end",
    ], "missing schema/RLS/policy")
    require(migration, ["Migration checksum drift", "check=True", "--check-only"], "migration failure/order")
    require(deployment, [
        "No READY Vercel production deployment found",
        "does not contain required commit",
        "is not assigned to deployment",
    ], "deployment commit/alias")
    require(r2, [
        "R2 part response did not expose an ETag",
        "R2 HEAD size mismatch",
        "Downloaded R2 object SHA-256 does not match",
        "Completed multipart ETag was incorrectly equal",
        "object still exists after delete",
        "Cleanup failures:",
    ], "R2 ETag/size/hash/cleanup")
    require(eas, [
        "EAS build is not finished successfully",
        "EAS build commit mismatch",
        "Downloaded APK artifact is missing or empty",
    ], "APK build")
    require(smoke, [
        "expected HTTP",
        "cross-batch idempotency mismatch",
        "status cross-batch mismatch",
        "status raw-key mismatch",
        "Production smoke cleanup failed",
    ], "production smoke")

    clean_env = {"PATH": os.environ.get("PATH", "")}
    expect_failure([sys.executable, "scripts/apply_upload_release_migrations.py"], clean_env, "missing database secret")

    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        apk = temp / "fixture.apk"
        apk.write_bytes(b"apk")
        build_json = temp / "build.json"
        build_json.write_text(json.dumps({
            "id": "build-fixture",
            "status": "ERRORED",
            "platform": "ANDROID",
            "buildProfile": "preview",
            "gitCommitHash": "0" * 40,
            "runtimeVersion": "fixture",
            "channel": "preview",
            "distribution": "INTERNAL",
        }), encoding="utf-8")
        env = {**clean_env, "GITHUB_SHA": "0" * 40}
        expect_failure([
            sys.executable, "scripts/record_eas_build_evidence.py",
            "--build-json", str(build_json), "--apk", str(apk),
            "--evidence", str(temp / "evidence.json"),
        ], env, "failed EAS build")

    print("PASS: negative production release cases remain fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
