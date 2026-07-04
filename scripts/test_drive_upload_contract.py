#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(text: str, name: str) -> str:
    marker = f"def {name}("
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"{name} is missing")
    next_def = text.find("\ndef ", start + len(marker))
    return text[start:] if next_def < 0 else text[start:next_def]


def main() -> int:
    drive = (ROOT / "integrations/drive.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    upload_draft = _function_body(drive, "upload_draft")
    upload_preview = _function_body(drive, "upload_preview")

    if "service       = _get_upload_service()" not in upload_draft:
        raise SystemExit("upload_draft must use user OAuth upload credentials")
    if "service       = _get_drive_service()" in upload_draft:
        raise SystemExit("upload_draft must not upload with service-account read credentials")
    if "DRIVE_USER_TOKEN" not in drive:
        raise SystemExit("Drive upload credentials must remain configurable through DRIVE_USER_TOKEN")
    if "service       = _get_upload_service()" not in upload_preview:
        raise SystemExit("upload_preview upload credential contract unexpectedly changed")

    required_upload_error_tokens = [
        "upload_error=str(e)",
        "upload_failed=True",
        "write_pipeline_status(\n                \"uploading\"",
    ]
    missing = [token for token in required_upload_error_tokens if token not in upload_draft]
    if missing:
        raise SystemExit(f"upload_draft must report original Drive upload failures: {missing}")

    required_tracked_error_tokens = [
        "upload_error = _last_observed_meta.get(\"upload_error\")",
        "All draft uploads failed: {upload_error}",
        "meta[\"upload_error\"] = upload_error",
    ]
    missing = [token for token in required_tracked_error_tokens if token not in run_tracked]
    if missing:
        raise SystemExit(f"run_tracked must surface original Drive upload failures: {missing}")

    print("Drive upload credential contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
