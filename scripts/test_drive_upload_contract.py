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

    print("Drive upload credential contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
