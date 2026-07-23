"""Exact byte-level duplicate gate for verified R2 source uploads.

The upload API records and HEAD-verifies each new source. Immediately before any
expensive analysis, this module hashes the downloaded bytes with SHA-256, asks
Postgres to choose the newest verified upload atomically, removes superseded raw
objects, and returns only canonical inputs. Perceptually similar re-exports are
intentionally outside this gate.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


def sha256_file(path: str, *, chunk_bytes: int = _HASH_CHUNK_BYTES) -> str:
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _remove_local(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove local dedup staging file %s", path, exc_info=True)


def prepare_canonical_sources(
    videos: list[dict[str, Any]],
    download_one: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    storage_backend: str | None = None,
    get_upload: Callable[[str], dict[str, Any] | None] | None = None,
    resolve_duplicate: Callable[[str, str], dict[str, Any]] | None = None,
    delete_source: Callable[[str], None] | None = None,
    mark_removed: Callable[[str, str], None] | None = None,
    mark_removal_error: Callable[[str, str, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Download, hash, reconcile, and return only canonical source metadata.

    Legacy raw objects without a manifest remain eligible with a warning so this
    focused change does not silently strand pre-migration footage. Every upload
    created after the migration is fail-closed unless its durable row is verified.
    GAP-015 stays open until legacy backfill and a real R2 duplicate test exist.
    """
    backend = (storage_backend or os.getenv("STORAGE_BACKEND", "drive")).strip().lower()
    if backend != "r2" or not videos:
        return videos

    if any(callback is None for callback in (get_upload, resolve_duplicate, mark_removed, mark_removal_error)):
        from integrations.source_uploads import (
            get_source_upload,
            mark_source_removal_error,
            mark_source_removed,
            resolve_exact_source_duplicate,
        )

        get_upload = get_upload or get_source_upload
        resolve_duplicate = resolve_duplicate or resolve_exact_source_duplicate
        mark_removed = mark_removed or mark_source_removed
        mark_removal_error = mark_removal_error or mark_source_removal_error

    if delete_source is None:
        from integrations.r2_storage import delete_object

        delete_source = delete_object

    assert get_upload is not None
    assert resolve_duplicate is not None
    assert mark_removed is not None
    assert mark_removal_error is not None
    assert delete_source is not None

    prepared_by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for video in videos:
        downloaded = download_one(video)
        if downloaded is None:
            continue
        path = str(downloaded["path"])
        meta = dict(downloaded["meta"])
        key = str(meta.get("id") or meta.get("key") or "")
        if not key:
            _remove_local(path)
            raise RuntimeError("R2 source is missing its immutable storage key")
        order.append(key)

        upload = get_upload(key)
        if upload is None:
            logger.warning(
                "R2 source %s has no durable source_uploads row; allowing legacy input without exact-upload dedup",
                key,
            )
            meta["_local_path"] = path
            prepared_by_key[key] = meta
            continue

        upload_id = str(upload.get("id") or "")
        status = str(upload.get("status") or "")
        canonical_upload_id = str(upload.get("canonical_upload_id") or upload_id)

        if status == "superseded":
            try:
                delete_source(key)
                mark_removed(upload_id, canonical_upload_id)
            except Exception as exc:
                mark_removal_error(upload_id, canonical_upload_id, str(exc))
                logger.error("Superseded R2 source %s could not be deleted; it remains ineligible", key)
            _remove_local(path)
            prepared_by_key.pop(key, None)
            continue

        if status != "verified" or not upload.get("verified_at"):
            _remove_local(path)
            raise RuntimeError(f"R2 source {key} is not durably verified (status={status or 'missing'})")

        actual_size = Path(path).stat().st_size
        verified_size = upload.get("verified_size_bytes")
        if verified_size is not None and int(verified_size) != actual_size:
            _remove_local(path)
            raise RuntimeError(
                f"R2 source {key} changed after verification: verified={verified_size}, downloaded={actual_size}"
            )

        content_sha256 = sha256_file(path)
        decision = resolve_duplicate(upload_id, content_sha256)
        canonical = decision["canonical"]
        canonical_key = str(canonical.get("storage_key") or "")
        canonical_id = str(canonical.get("upload_id") or "")
        if not canonical_key or not canonical_id:
            _remove_local(path)
            raise RuntimeError("Exact-source dedup decision is missing canonical identity")

        for superseded in decision.get("superseded", []):
            old_id = str(superseded.get("upload_id") or "")
            old_key = str(superseded.get("storage_key") or "")
            if not old_id or not old_key or old_id == canonical_id:
                continue
            old_meta = prepared_by_key.pop(old_key, None)
            _remove_local(str(old_meta.get("_local_path")) if old_meta else None)
            try:
                delete_source(old_key)
                mark_removed(old_id, canonical_id)
            except Exception as exc:
                mark_removal_error(old_id, canonical_id, str(exc))
                logger.error(
                    "Superseded R2 source %s could not be deleted; DB eligibility still blocks it",
                    old_key,
                )

        if key == canonical_key:
            meta["_local_path"] = path
            meta["content_sha256"] = content_sha256
            meta["source_upload_id"] = canonical_id
            prepared_by_key[key] = meta
        else:
            _remove_local(path)
            prepared_by_key.pop(key, None)

    return [prepared_by_key[key] for key in order if key in prepared_by_key]
