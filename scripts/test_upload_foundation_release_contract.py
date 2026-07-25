#!/usr/bin/env python3
"""Static contract for the protected upload-foundation production release workflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/upload-foundation-release.yml"
R2_PROBE = ROOT / "scripts/test_real_r2_multipart_upload.py"
WEB_API_SIGNER_PROBE = ROOT / "scripts/test_real_web_api_r2_signer.cjs"


def require_tokens(source: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise SystemExit(f"{label} missing: {missing}")


def require_order(source: str, tokens: list[str], label: str) -> None:
    positions = [source.index(token) for token in tokens]
    if positions != sorted(positions):
        raise SystemExit(f"{label} has unsafe order: {tokens}")


def main() -> int:
    source = WORKFLOW.read_text(encoding="utf-8")
    probe = R2_PROBE.read_text(encoding="utf-8")
    signer_probe = WEB_API_SIGNER_PROBE.read_text(encoding="utf-8")

    require_tokens(
        source,
        [
            "workflow_dispatch:",
            "confirm_release:",
            "confirm_biometric_removal:",
            "concurrency:",
            "cancel-in-progress: false",
            "environment: production",
            "SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}",
            "python scripts/apply_upload_release_migrations.py",
            "--check-only",
            "scripts/verify_upload_release_schema.sql",
            "grep -q '=false$'",
            "supabase/verify_schema.sql",
            "verify-production-deployment:",
            "scripts/verify_production_deployment.py",
            "real-r2-probe:",
            "needs: migrate-and-verify",
            "scripts/verify_r2_cors.py",
            "Compile the actual Web API R2 signer",
            "src/lib/r2-storage.ts",
            "R2_STORAGE_MODULE:",
            "node scripts/test_real_web_api_r2_signer.cjs",
            "Remove and verify absence of the Web API signer probe object",
            "object still exists after delete",
            "python scripts/test_real_r2_multipart_upload.py",
            "production-api-smoke:",
            "python scripts/test_production_upload_api_smoke.py",
            "build-android-preview:",
            "needs: production-api-smoke",
            "uses: expo/expo-github-action@v8",
            "eas build --platform android --profile preview --non-interactive --wait --json",
            "eas build:download --build-id",
            "scripts/record_eas_build_evidence.py",
            "if-no-files-found: error",
        ],
        "upload release workflow",
    )

    require_tokens(
        signer_probe,
        [
            "createR2MultipartUpload",
            "createR2MultipartPartUploadUrl",
            "completeR2MultipartUpload",
            "verifyR2Object",
            "createR2SignedGetUrl",
            "abortR2MultipartUpload",
            "expected_sha256",
            "download_sha256",
            "probe_succeeded",
            "R2_STORAGE_MODULE",
            "R2_WEB_API_EVIDENCE_PATH",
        ],
        "actual Web API R2 signer probe",
    )

    require_tokens(
        probe,
        [
            'evidence["cleanup"] = "confirmed" if not cleanup_errors else "failed"',
            'evidence["probe_succeeded"] = probe_succeeded',
            "multipart_etag_is_not_file_md5",
            "completion_part_numbers_ascending",
            "if cleanup_errors:",
            "raise RuntimeError(message)",
            'if not probe_succeeded:',
            'raise RuntimeError("R2 probe did not reach verified completion")',
        ],
        "independent R2 probe fail-closed cleanup",
    )

    require_order(
        source,
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
    require_order(
        source,
        [
            "Compile the actual Web API R2 signer",
            "Probe R2 through SportReel Web API signing code",
            "Remove and verify absence of the Web API signer probe object",
            "Upload, retry, complete, hash-check, and remove independent probe object",
        ],
        "R2 signer and independent probe order",
    )

    forbidden = ["continue-on-error: true", "if-no-files-found: ignore", "|| true"]
    present = [token for token in forbidden if token in source]
    if present:
        raise SystemExit(f"upload release workflow contains fail-open patterns: {present}")

    print("Upload foundation release contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
