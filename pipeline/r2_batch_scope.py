"""Runtime R2 batch scoping for RAW pipeline inputs.

RAW is permanent: a source video under raw/ is read, never moved, replaced or deleted. "Already
processed" is a tiny marker object under metadata/source_state/ (see integrations.r2_storage), so a
re-run skips finished sources and Reset simply forgets the markers.

When RAW_BATCH_ID is set, R2 processing is restricted to raw/<batch_id>/. Before returning the scoped
list, verified uploads are SHA-256 reconciled so byte-identical sources cannot both reach analysis
(excluded from the run, never deleted).
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
        # The app uploads into raw/<batch>/, so batchless mode means raw/ at any depth. Sources that
        # were already processed carry a marker (the video itself stays in raw/) and are not listed here.
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
        else:
            objects = r2.unprocessed_sources(objects)
        videos = [r2._object_to_video(obj) for obj in objects if r2._is_video_key(obj["Key"])]
        if not videos:
            return []

        from pipeline.source_upload_dedup import prepare_canonical_sources

        canonical = prepare_canonical_sources(
            videos,
            download_for_dedup,
            storage_backend="r2",
            # Original RAW objects are never deleted, in any mode: duplicate candidates are only excluded
            # from this run. delete_source is kept for API compatibility and is never called.
            delete_source=r2.delete_object,
            preserve_sources=True,
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
        # Record the state, leave the footage exactly where it is (raw/ is permanent).
        if not str(file_id_or_key).startswith(r2.RAW_PREFIX):
            raise RuntimeError("Cannot mark a non-RAW object as processed")
        r2.mark_source_processed(file_id_or_key)

    def requeue_video(file_id_or_key: str) -> bool:
        # Reprocess = forget the marker (a legacy source only in processed/ is COPIED back first).
        return r2.requeue_video_impl(file_id_or_key)

    def restore_processed_to_raw() -> int:
        # Manifest-driven and batch-scoped only; never a global sweep.
        return ensure_frozen_inputs().restored

    r2.get_new_videos = get_new_videos
    r2.download_video = download_video
    r2.mark_as_processed = mark_as_processed
    r2.requeue_video = requeue_video
    r2.restore_processed_to_raw = restore_processed_to_raw
    setattr(r2, _INSTALLED_FLAG, True)
