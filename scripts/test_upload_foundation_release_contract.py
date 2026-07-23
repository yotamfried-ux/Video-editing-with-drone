#!/usr/bin/env python3
"""Static contract for the live upload-foundation release workflow."""

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
            "push:",
            "branches: [main]",
            "concurrency:",
            "cancel-in-progress: false",
            "SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}",
            "psql \"$SUPABASE_DB_URL\" -v ON_ERROR_STOP=1 -f \"$path\"",
            "Verify required tables, columns, and RPCs",
            "column:source_size_evidence=",
            "real-r2-probe:",
            "needs: migrate-and-verify",
            "Compile the actual Web API R2 signer",
            "src/lib/r2-storage.ts",
            "R2_STORAGE_MODULE:",
            "node scripts/test_real_web_api_r2_signer.cjs",
            "Remove and verify absence of the Web API signer probe object",
            "object still exists after delete",
            "web-api-r2-signer-evidence-${{ github.run_id }}",
            "python scripts/test_real_r2_multipart_upload.py",
            "build-android-preview:",
            "needs: [migrate-and-verify, real-r2-probe]",
            "uses: expo/expo-github-action@v8",
            "eas build --platform android --profile preview --non-interactive --local",
            "eas upload --platform android",
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
            "20260723_source_upload_exact_dedup.sql",
            "20260723_source_upload_multipart_foundation.sql",
            "20260723_single_put_size_evidence.sql",
            "20260723_source_upload_local_cleanup_evidence.sql",
            "20260723_upload_batch_verified_gate.sql",
            "20260723_upload_start_idempotency.sql",
        ],
        "migration dependency order",
    )
    require_order(
        source,
        ["migrate-and-verify:", "real-r2-probe:", "build-android-preview:"],
        "release job order",
    )
    require_order(
        source,
        [
            "Compile the actual Web API R2 signer",
            "Probe R2 through SportReel Web API signing code",
            "Remove and verify absence of the Web API signer probe object",
            "Publish Web API signer evidence",
            "Upload, retry, complete, hash-check, and remove independent probe object",
        ],
        "R2 signer and independent probe order",
    )

    forbidden = [
        "continue-on-error: true",
        "if-no-files-found: ignore",
        "|| true",
    ]
    present = [token for token in forbidden if token in source]
    if present:
        raise SystemExit(f"upload release workflow contains fail-open patterns: {present}")

    print("Upload foundation release contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
