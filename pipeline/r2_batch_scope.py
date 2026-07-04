"""Runtime R2 batch scoping for RAW pipeline inputs.

When RAW_BATCH_ID is set, R2 processing is restricted to raw/<batch_id>/ and
processed footage is moved to processed/<batch_id>/ so unrelated uploads stay out
of the current run. With no batch id, the legacy global raw/ behavior is kept.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_INSTALLED_FLAG = "_sportreel_r2_batch_scope_installed"


def safe_batch_id(value: str | None = None) -> str:
    raw = (value if value is not None else os.getenv("RAW_BATCH_ID") or os.getenv("BATCH_ID") or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw).strip("_")
    return safe[:80]


def scoped_prefix(prefix: str, batch_id: str | None = None) -> str:
    batch = safe_batch_id(batch_id)
    return f"{prefix}{batch}/" if batch else prefix


def basename(key: str) -> str:
    return key.rstrip("/").rsplit("/", 1)[-1]


def move_between_prefixes(source_key: str, from_prefix: str, to_prefix: str) -> str:
    if source_key.startswith(from_prefix):
        rest = source_key[len(from_prefix):]
        if rest and "/" in rest:
            return f"{to_prefix}{rest}"
    return f"{to_prefix}{Path(source_key).name}"


def install() -> None:
    import integrations.r2_storage as r2

    if getattr(r2, _INSTALLED_FLAG, False):
        return

    def get_new_videos() -> list[dict[str, Any]]:
        objects = r2.list_objects(scoped_prefix(r2.RAW_PREFIX))
        return [r2._object_to_video(obj) for obj in objects if r2._is_video_key(obj["Key"])]

    def mark_as_processed(file_id_or_key: str) -> None:
        dest_key = move_between_prefixes(file_id_or_key, r2.RAW_PREFIX, r2.PROCESSED_PREFIX)
        r2.move_object(file_id_or_key, dest_key)

    def requeue_video(file_id_or_key: str) -> bool:
        try:
            dest_key = move_between_prefixes(file_id_or_key, r2.PROCESSED_PREFIX, r2.RAW_PREFIX)
            r2.move_object(file_id_or_key, dest_key)
            return True
        except Exception:
            return False

    def restore_processed_to_raw() -> int:
        objects = r2.list_objects(scoped_prefix(r2.PROCESSED_PREFIX))
        restored = 0
        for obj in objects:
            key = obj["Key"]
            r2.move_object(key, move_between_prefixes(key, r2.PROCESSED_PREFIX, r2.RAW_PREFIX))
            restored += 1
        return restored

    r2.get_new_videos = get_new_videos
    r2.mark_as_processed = mark_as_processed
    r2.requeue_video = requeue_video
    r2.restore_processed_to_raw = restore_processed_to_raw
    setattr(r2, _INSTALLED_FLAG, True)
