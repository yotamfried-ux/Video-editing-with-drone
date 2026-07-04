#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def require_upload_queue_contract(pipeline_screen: str) -> None:
    upload_start = pipeline_screen.index("const uploadFootage")
    upload_end = pipeline_screen.index("const busy", upload_start)
    upload_block = pipeline_screen[upload_start:upload_end]
    if "/api/operator/pipeline/start" in upload_block:
        raise SystemExit("Upload footage must only queue RAW footage; it must not auto-run the pipeline")
    require_tokens(
        "operator upload queue UX",
        upload_block,
        [
            "Uploaded to queue",
            "Upload more footage for this athlete/session",
            "Run pipeline now when the batch is ready",
        ],
    )


def main() -> int:
    storage = _read("integrations/storage.py")
    r2 = _read("integrations/r2_storage.py")
    run_tracked = _read("scripts/run_tracked.py")
    deliver = _read("deliver.py")
    pipeline_screen = _read("mobile/src/app/(operator)/pipeline.tsx")
    requirements = _read("requirements.txt")

    require_tokens(
        "storage router",
        storage,
        [
            'os.getenv("STORAGE_BACKEND", "drive")',
            '"drive": "integrations.drive"',
            '"r2": "integrations.r2_storage"',
            "def get_new_videos()",
            "def download_video(file_id_or_key: str, filename: str)",
            "def upload_draft(draft_path: str, draft_name: str)",
            "def upload_preview(preview_path: str, preview_name: str)",
            "def mark_as_processed(file_id_or_key: str)",
            "def requeue_video(file_id_or_key: str)",
            "def get_pending_payment_drafts()",
            "def move_to_pending_payment(file_id_or_key: str)",
            "def delete_review_drafts()",
            "def restore_processed_to_raw()",
            "def record_failure(file_id_or_key: str, max_failures: int = 3)",
            "def flag_quality_issue(file_id_or_key: str, reasons: str)",
        ],
    )

    require_tokens(
        "r2 adapter",
        r2,
        [
            "RAW_PREFIX = \"raw/\"",
            "PROCESSED_PREFIX = \"processed/\"",
            "REVIEW_PREFIX = \"review/\"",
            "APPROVED_PREFIX = \"approved/\"",
            "PENDING_PAYMENT_PREFIX = \"pending_payment/\"",
            "PREVIEWS_PREFIX = \"previews/\"",
            "METADATA_PREFIX = \"metadata/\"",
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
            "R2_ENDPOINT_URL",
            "R2_PUBLIC_BASE_URL",
            "boto3.client(",
            "generate_presigned_url(",
            "endpoint_url=_endpoint_url()",
            "def upload_object(local_path: str, key: str",
            "def move_object(source_key: str, dest_key: str)",
            "client.head_object(Bucket=_bucket(), Key=dest_key)",
            "def get_new_videos()",
            "def upload_draft(draft_path: str, draft_name: str)",
            "def get_pending_payment_drafts()",
            "def move_to_pending_payment(file_id_or_key: str)",
            "def delete_review_drafts()",
            "def restore_processed_to_raw()",
            "def record_failure(file_id_or_key: str, max_failures: int = 3)",
            "def flag_quality_issue(file_id_or_key: str, reasons: str)",
            "quality_flags",
            "put_object(",
            "def _tmp_dir() -> str:",
            "def _processed_ids_file() -> str:",
        ],
    )
    require_no_tokens(
        "r2 adapter preflight imports",
        r2,
        [
            "import config",
            "config.",
        ],
    )

    require_tokens(
        "tracked pipeline storage routing",
        run_tracked,
        [
            "def _install_storage_backend_alias()",
            'os.getenv("STORAGE_BACKEND", "drive")',
            "if backend == \"drive\":",
            "import integrations.storage as storage",
            'sys.modules["integrations.drive"] = storage',
            "_install_storage_backend_alias()",
            "import pipeline.orchestrator as _orchestrator",
        ],
    )

    require_tokens(
        "delivery storage routing",
        deliver,
        [
            "def _install_storage_backend_alias()",
            "import integrations.storage as storage",
            'sys.modules["integrations.drive"] = storage',
            "_install_storage_backend_alias()",
            "from services.delivery import deliver_preview as main",
        ],
    )

    require_upload_queue_contract(pipeline_screen)

    if "boto3" not in requirements:
        raise SystemExit("requirements.txt must include boto3 for R2 S3-compatible storage")

    print("Storage abstraction contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
