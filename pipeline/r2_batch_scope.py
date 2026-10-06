"""Runtime R2 batch scoping for RAW pipeline inputs.

When RAW_BATCH_ID is set, R2 processing is restricted to raw/<batch_id>/ and
processed footage is moved to processed/<batch_id>/ so unrelated uploads stay out
of the current run. Before returning the scoped list, verified uploads are
SHA-256 reconciled so byte-identical sources cannot both reach analysis.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

_INSTALLED_FLAG = "_sportreel_r2_batch_scope_installed"
_PRELOADED_PATHS: dict[str, str] = {}


def _store_factory():
    """Overridable in tests; production uses the real R2 client."""
    from pipeline.r2_batch_restore import R2Store

    return R2Store()


def ensure_frozen_inputs(*, restore: bool = True):
    """Reconcile raw/<batch>/ with the frozen manifest (restoring from processed/<batch>/).

    Fails closed unless an explicit batch id and a frozen manifest are present.
    """
    from pipeline.r2_batch_restore import FrozenInputError, load_manifest_from_env, reconcile_frozen_inputs

    batch = safe_batch_id()
    if not batch:
        raise RuntimeError("frozen input restore requires an explicit RAW_BATCH_ID")
    try:
        return reconcile_frozen_inputs(_store_factory(), load_manifest_from_env(), batch, restore=restore)
    except FrozenInputError as exc:
        raise RuntimeError(f"Frozen input manifest cannot be satisfied: {exc}") from exc


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


def _manifest_keys() -> set[str]:
    raw = (os.getenv("SPORTREEL_INPUT_MANIFEST_JSON") or "").strip()
    encoded = (os.getenv("SPORTREEL_INPUT_MANIFEST_B64") or "").strip()
    if not raw and encoded:
        try:
            raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("SPORTREEL_INPUT_MANIFEST_B64 is invalid") from exc
    if not raw:
        return set()
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SPORTREEL_INPUT_MANIFEST_JSON is invalid JSON") from exc
    if not isinstance(manifest, list):
        raise RuntimeError("SPORTREEL_INPUT_MANIFEST_JSON must be a list")
    keys: set[str] = set()
    for item in manifest:
        if not isinstance(item, dict):
            continue
        key = str(item.get("storage_key") or item.get("key") or "").strip()
        if key:
            keys.add(key)
    if not keys:
        raise RuntimeError("Frozen pipeline input manifest contains no storage keys")
    return keys


def install() -> None:
    import integrations.r2_storage as r2

    if getattr(r2, _INSTALLED_FLAG, False):
        return

    original_download_video = r2.download_video

    def download_for_dedup(video: dict[str, Any]) -> dict[str, Any] | None:
        path = original_download_video(video["id"], video["name"])
        return {"path": path, "meta": video}

    def get_new_videos() -> list[dict[str, Any]]:
        allowed = _manifest_keys()
        if allowed:
            # A previous attempt may have moved the frozen inputs to processed/<batch>/.
            # Restore exactly those objects (idempotent) before admitting anything.
            ensure_frozen_inputs()
        objects = r2.list_objects(scoped_prefix(r2.RAW_PREFIX))
        if allowed:
            present = {str(obj.get("Key") or "") for obj in objects}
            missing = sorted(allowed - present)
            if missing:
                raise RuntimeError(f"Frozen input manifest is missing {len(missing)} raw object(s): {missing[:3]}")
            objects = [obj for obj in objects if str(obj.get("Key") or "") in allowed]
            if len(objects) != len(allowed):
                raise RuntimeError(
                    f"Frozen input manifest expected {len(allowed)} objects but admitted {len(objects)}"
                )
        videos = [r2._object_to_video(obj) for obj in objects if r2._is_video_key(obj["Key"])]
        if not videos:
            return []

        from pipeline.source_upload_dedup import prepare_canonical_sources

        canonical = prepare_canonical_sources(
            videos,
            download_for_dedup,
            storage_backend="r2",
            delete_source=r2.delete_object,
        )
        for video in canonical:
            key = str(video.get("id") or "")
            local_path = str(video.pop("_local_path", "") or "")
            if key and local_path:
                _PRELOADED_PATHS[key] = local_path
        return canonical

    def download_video(file_id_or_key: str, filename: str) -> str:
        preloaded = _PRELOADED_PATHS.pop(file_id_or_key, "")
        if preloaded and os.path.exists(preloaded):
            return preloaded
        return original_download_video(file_id_or_key, filename)

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
        # Manifest-driven and batch-scoped only; never a global processed/ -> raw/ sweep.
        return ensure_frozen_inputs().restored

    r2.get_new_videos = get_new_videos
    r2.download_video = download_video
    r2.mark_as_processed = mark_as_processed
    r2.requeue_video = requeue_video
    r2.restore_processed_to_raw = restore_processed_to_raw
    setattr(r2, _INSTALLED_FLAG, True)
