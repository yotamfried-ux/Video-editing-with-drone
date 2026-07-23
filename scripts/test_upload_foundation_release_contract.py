#!/usr/bin/env python3
"""Static contract for the live upload-foundation release workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/upload-foundation-release.yml"


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
