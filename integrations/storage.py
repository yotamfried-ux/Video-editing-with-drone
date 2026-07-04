"""Storage backend router for pipeline file operations.

The active pipeline still defaults to Google Drive. Set STORAGE_BACKEND=r2 to
route the same high-level storage contract through Cloudflare R2.
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType
from typing import Any

_BACKEND_MODULES = {
    "drive": "integrations.drive",
    "r2": "integrations.r2_storage",
}


def _backend_name() -> str:
    value = os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"
    if value not in _BACKEND_MODULES:
        allowed = ", ".join(sorted(_BACKEND_MODULES))
        raise ValueError(f"Unsupported STORAGE_BACKEND={value!r}; expected one of: {allowed}")
    return value


def get_backend_name() -> str:
    """Return the normalized active storage backend name."""
    return _backend_name()


def _backend() -> ModuleType:
    return importlib.import_module(_BACKEND_MODULES[_backend_name()])


def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    backend = _backend()
    try:
        func = getattr(backend, name)
    except AttributeError as exc:
        raise NotImplementedError(
            f"Storage backend {_backend_name()!r} does not implement {name}()"
        ) from exc
    return func(*args, **kwargs)


def get_new_videos() -> list[dict]:
    return _call("get_new_videos")


def download_video(file_id_or_key: str, filename: str) -> str:
    return _call("download_video", file_id_or_key, filename)


def upload_draft(draft_path: str, draft_name: str) -> str:
    return _call("upload_draft", draft_path, draft_name)


def upload_preview(preview_path: str, preview_name: str) -> str:
    return _call("upload_preview", preview_path, preview_name)


def mark_as_processed(file_id_or_key: str) -> None:
    return _call("mark_as_processed", file_id_or_key)


def requeue_video(file_id_or_key: str) -> bool:
    return _call("requeue_video", file_id_or_key)


def get_approved_drafts() -> list[dict]:
    return _call("get_approved_drafts")


def mark_draft_delivered(file_id_or_key: str) -> None:
    return _call("mark_draft_delivered", file_id_or_key)


def delete_review_drafts() -> int:
    return _call("delete_review_drafts")


def restore_processed_to_raw() -> int:
    return _call("restore_processed_to_raw")


def record_failure(file_id_or_key: str, max_failures: int = 3) -> bool:
    return _call("record_failure", file_id_or_key, max_failures)


def flag_quality_issue(file_id_or_key: str, reasons: str) -> None:
    return _call("flag_quality_issue", file_id_or_key, reasons)
