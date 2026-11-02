"""Cloudflare R2 storage adapter for the SportReel pipeline."""

from __future__ import annotations

from datetime import timezone
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote

RAW_PREFIX = "raw/"
PROCESSED_PREFIX = "processed/"
REVIEW_PREFIX = "review/"
APPROVED_PREFIX = "approved/"
PENDING_PAYMENT_PREFIX = "pending_payment/"
PENDING_UPLOADS_PREFIX = "pending_uploads/"
PREVIEWS_PREFIX = "previews/"
METADATA_PREFIX = "metadata/"
# "Already processed" state lives in tiny marker objects, never in a moved or copied video. RAW is permanent.
SOURCE_STATE_PREFIX = f"{METADATA_PREFIX}source_state/"

_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".mxf"}


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required R2 environment variable: {name}")
    return value


def _bucket() -> str:
    return os.getenv("R2_BUCKET", "").strip() or "sportreel"


def _endpoint_url() -> str:
    explicit = os.getenv("R2_ENDPOINT_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    account_id = _require_env("R2_ACCOUNT_ID")
    return f"https://{account_id}.r2.cloudflarestorage.com"


def _client():
    import boto3
    from botocore.config import Config

    # Bound every R2 network attempt so storage outages cannot hang a run.
    connect_timeout = int(os.getenv("R2_CONNECT_TIMEOUT_SECONDS", "10"))
    read_timeout = int(os.getenv("R2_READ_TIMEOUT_SECONDS", "60"))
    max_attempts = int(os.getenv("R2_MAX_ATTEMPTS", "4"))

    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID") or os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("SECRET_KEY_ID"),
        config=Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


def _public_base_url() -> str | None:
    value = os.getenv("R2_PUBLIC_BASE_URL", "").strip()
    return value.rstrip("/") if value else None


def _object_url(key: str) -> str:
    base = _public_base_url()
    if base:
        return f"{base}/{quote(key)}"
    expires = int(os.getenv("R2_SIGNED_URL_EXPIRES", "604800"))
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires,
    )


def _content_type(path_or_name: str) -> str:
    guessed, _ = mimetypes.guess_type(path_or_name)
    return guessed or "application/octet-stream"


def _join(prefix: str, name: str) -> str:
    safe_name = Path(name).name
    return f"{prefix}{safe_name}"


def _basename(key: str) -> str:
    return key.rstrip("/").rsplit("/", 1)[-1]


def _is_video_key(key: str, content_type: str | None = None) -> bool:
    return (content_type or "").startswith("video/") or Path(key).suffix.lower() in _VIDEO_EXTS


def _object_to_video(item: dict) -> dict:
    key = item["Key"]
    last_modified = item.get("LastModified")
    created = ""
    if last_modified:
        created = last_modified.astimezone(timezone.utc).isoformat()
    content_type = item.get("ContentType") or _content_type(key)
    return {
        "id": key,
        "key": key,
        "name": _basename(key),
        "size": str(item.get("Size", 0)),
        "createdTime": created,
        "mimeType": content_type,
        "webViewLink": _object_url(key),
    }


def _processed_ids_file() -> str:
    return os.getenv("PROCESSED_IDS_FILE", "processed.json")


def _tmp_dir() -> str:
    return os.getenv("TMP_DIR", "/tmp/dtor")


def _failed_ids_path() -> str:
    base = os.path.dirname(os.path.abspath(_processed_ids_file()))
    return os.path.join(base, "failed_ids.json")


def _load_failed_ids() -> dict[str, int]:
    try:
        with open(_failed_ids_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_failed_ids(failed: dict[str, int]) -> None:
    path = _failed_ids_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(failed, f, indent=2)
    os.replace(tmp, path)


def _list_objects(prefix: str) -> list[dict]:
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    items: list[dict] = []
    for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if key and not key.endswith("/"):
                items.append(item)
    return items


def list_objects(prefix: str) -> list[dict]:
    return _list_objects(prefix)


def download_object(key: str, local_path: str) -> str:
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(_bucket(), key, local_path)
    return local_path


def upload_object(local_path: str, key: str, content_type: str | None = None) -> str:
    extra_args = {"ContentType": content_type or _content_type(local_path)}
    _client().upload_file(local_path, _bucket(), key, ExtraArgs=extra_args)
    return _object_url(key)


def copy_object(source_key: str, dest_key: str) -> None:
    _client().copy_object(
        Bucket=_bucket(),
        CopySource={"Bucket": _bucket(), "Key": source_key},
        Key=dest_key,
    )


def copy_object_if_absent(source_key: str, dest_key: str) -> None:
    """Create a destination atomically, without overwriting concurrent writers.

    S3 CopyObject has source preconditions but no destination If-None-Match.
    A conditional PutObject provides destination create-if-absent semantics.
    Stream the source to avoid loading a full video into process memory.
    R2 must support IfNoneMatch='*'; unsupported preconditions fail closed.
    """
    from botocore.exceptions import ClientError
    client = _client()
    bucket = _bucket()
    source = client.get_object(Bucket=bucket, Key=source_key)
    body = source["Body"]
    try:
        try:
            client.put_object(
                Bucket=bucket,
                Key=dest_key,
                Body=body,
                ContentLength=source["ContentLength"],
                ContentType=source.get("ContentType") or _content_type(source_key),
                IfNoneMatch="*",
            )
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in (409, 412):
                raise RuntimeError(f"Destination already exists or concurrent write: {dest_key}") from exc
            raise
    finally:
        body.close()


def _head(key: str) -> dict | None:
    from botocore.exceptions import ClientError
    try:
        return _client().head_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404 or \
                exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def _sha256_of(key: str) -> bytes:
    import hashlib
    body = _client().get_object(Bucket=_bucket(), Key=key)["Body"]
    digest = hashlib.sha256()
    try:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            if chunk:
                digest.update(chunk)
    finally:
        body.close()
    return digest.digest()


def same_object_bytes(key_a: str, key_b: str) -> bool:
    """True when both objects exist with identical content.

    Equal size and equal ETag is conclusive for a server-side copy (the copy preserves the
    ETag); otherwise the bodies are hashed so a streamed copy is still verified byte for byte.
    """
    a, b = _head(key_a), _head(key_b)
    if a is None or b is None or a["ContentLength"] != b["ContentLength"]:
        return False
    if a.get("ETag") and a.get("ETag") == b.get("ETag"):
        return True
    # Hash both bodies at the same time: the check is network-bound, so this halves its wall time.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        hash_a, hash_b = pool.submit(_sha256_of, key_a), pool.submit(_sha256_of, key_b)
        return hash_a.result() == hash_b.result()


def copy_object_verified(source_key: str, dest_key: str) -> str:
    """Copy source -> dest without ever overwriting, and prove the copy is identical.

    Returns "copied", or "present" when dest already holds identical bytes (an interrupted
    earlier attempt). Raises, changing nothing, when dest exists with different bytes.
    """
    if _head(source_key) is None:
        raise RuntimeError(f"Source object is missing: {source_key}")
    if _head(dest_key) is not None:
        if same_object_bytes(source_key, dest_key):
            return "present"
        raise RuntimeError(f"Destination already exists with different content: {dest_key}")
    from botocore.exceptions import ClientError
    try:
        # Server-side copy: no download, preserves bytes and ETag. Destination was just
        # checked absent, and runs are single-flight, so nothing can be overwritten.
        _client().copy_object(
            Bucket=_bucket(), Key=dest_key,
            CopySource={"Bucket": _bucket(), "Key": source_key},
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in ("InvalidRequest", "EntityTooLarge", "InvalidArgument"):
            raise
        # Objects above the single-copy size limit use the streamed conditional copy.
        copy_object_if_absent(source_key, dest_key)
    if not same_object_bytes(source_key, dest_key):
        raise RuntimeError(f"Copy verification failed: {source_key} -> {dest_key}")
    return "copied"


def move_object_verified(source_key: str, dest_key: str) -> str:
    """Move a DERIVED object (e.g. a draft one stage on): verified copy first, delete the source only after.

    Original source videos can never be moved; use copy_object_verified for them.
    """
    assert_not_protected_source(source_key, "move")
    outcome = copy_object_verified(source_key, dest_key)
    delete_object(source_key)
    return outcome


class ProtectedSourceError(RuntimeError):
    """An operation would delete or move away an original source video. Always refused, no override."""


def is_protected_source_key(key: str) -> bool:
    """Original footage: anything under raw/, and any video under processed/ (legacy stage folder that may
    hold the only copy of a source)."""
    k = str(key or "")
    return k.startswith(RAW_PREFIX) or (k.startswith(PROCESSED_PREFIX) and _is_video_key(k))


def assert_not_protected_source(key: str, action: str) -> None:
    if is_protected_source_key(key):
        raise ProtectedSourceError(
            f"Refusing to {action} original source object {key!r}: source videos are never deleted or moved"
        )


def delete_object(key: str) -> None:
    """Delete a derived object (review/, approved/, previews/, markers...). Never an original source."""
    assert_not_protected_source(key, "delete")
    _client().delete_object(Bucket=_bucket(), Key=key)


def move_object(source_key: str, dest_key: str) -> None:
    """Move = copy + delete of the source, so the source must not be an original video."""
    assert_not_protected_source(source_key, "move")
    client = _client()
    client.copy_object(
        Bucket=_bucket(),
        CopySource={"Bucket": _bucket(), "Key": source_key},
        Key=dest_key,
    )
    client.head_object(Bucket=_bucket(), Key=dest_key)
    client.delete_object(Bucket=_bucket(), Key=source_key)


def get_new_videos() -> list[dict]:
    objects = unprocessed_sources(_list_objects(RAW_PREFIX))
    return [_object_to_video(obj) for obj in objects if _is_video_key(obj["Key"])]


def download_video(file_id_or_key: str, filename: str) -> str:
    local_path = os.path.join(_tmp_dir(), filename)
    return download_object(file_id_or_key, local_path)


def upload_draft(draft_path: str, draft_name: str) -> str:
    """Upload to REVIEW and return the canonical immutable R2 object key."""
    key = _join(REVIEW_PREFIX, draft_name)
    upload_object(draft_path, key, "video/mp4")
    return key


def upload_preview(preview_path: str, preview_name: str) -> str:
    key = _join(PREVIEWS_PREFIX, preview_name)
    return upload_object(preview_path, key, "video/mp4")


def _state_key(source_key: str) -> str:
    import hashlib
    return f"{SOURCE_STATE_PREFIX}{hashlib.sha256(str(source_key).encode('utf-8')).hexdigest()}.json"


def mark_source_processed(source_key: str, run_id: str | None = None) -> None:
    """Record that this raw object was processed, WITHOUT touching the video. The marker pins the object's
    size and ETag so a re-uploaded/changed file is not mistaken for an already processed one."""
    head = _head(source_key)
    if head is None:
        raise RuntimeError(f"Cannot mark a missing source as processed: {source_key}")
    from datetime import datetime
    body = json.dumps({
        "source_key": source_key, "size": head["ContentLength"], "etag": head.get("ETag"),
        "run_id": run_id or os.getenv("GITHUB_RUN_ID") or None,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }, sort_keys=True).encode("utf-8")
    _client().put_object(Bucket=_bucket(), Key=_state_key(source_key), Body=body, ContentType="application/json")


def processed_markers() -> dict[str, dict]:
    """source_key -> marker for every recorded processed source (small JSON reads, no video bytes)."""
    out: dict[str, dict] = {}
    client = _client()
    for item in _list_objects(SOURCE_STATE_PREFIX):
        try:
            marker = json.loads(client.get_object(Bucket=_bucket(), Key=item["Key"])["Body"].read())
        except Exception:
            continue
        if isinstance(marker, dict) and marker.get("source_key"):
            out[str(marker["source_key"])] = marker
    return out


def is_marker_current(marker: dict | None, obj: dict) -> bool:
    """The marker applies only to the exact bytes that were processed (same size and ETag)."""
    return bool(marker) and marker.get("size") == obj.get("Size") and marker.get("etag") == obj.get("ETag")


def unprocessed_sources(objects: list[dict]) -> list[dict]:
    """Filter a raw/ listing down to sources that still need processing."""
    markers = processed_markers()
    return [o for o in objects if not is_marker_current(markers.get(o["Key"]), o)]


def clear_source_processed(source_key: str | None = None) -> int:
    """Forget processed state (one source, or all). Deletes marker objects only, never a video."""
    removed = 0
    if source_key is not None:
        keys = [_state_key(source_key)] if _head(_state_key(source_key)) else []
    else:
        keys = [item["Key"] for item in _list_objects(SOURCE_STATE_PREFIX)]
    for key in keys:
        delete_object(key)  # a marker under metadata/, which the guard allows
        removed += 1
    return removed


def mark_as_processed(file_id_or_key: str) -> None:
    mark_source_processed(file_id_or_key)


def ensure_raw_copy(source_key: str, raw_key: str) -> str:
    """Make sure raw_key holds this source: verified server-side COPY, never overwrite, never delete the source."""
    return copy_object_verified(source_key, raw_key)


def requeue_video_impl(file_id_or_key: str) -> bool:
    """Reprocess a source: forget its processed marker. A legacy source that only exists under processed/ is
    COPIED back to raw/ first (the processed/ copy is kept). Nothing is deleted or moved."""
    try:
        raw_key = file_id_or_key if str(file_id_or_key).startswith(RAW_PREFIX) else _join(RAW_PREFIX, _basename(file_id_or_key))
        if _head(raw_key) is None:
            legacy = _join(PROCESSED_PREFIX, _basename(file_id_or_key))
            if _head(legacy) is None:
                return False
            ensure_raw_copy(legacy, raw_key)
        clear_source_processed(raw_key)
        return True
    except ProtectedSourceError:
        raise
    except Exception:
        return False


def requeue_video(file_id_or_key: str) -> bool:
    return requeue_video_impl(file_id_or_key)


def get_approved_drafts() -> list[dict]:
    objects = _list_objects(APPROVED_PREFIX)
    return [_object_to_video(obj) for obj in objects if _is_video_key(obj["Key"])]


def get_pending_payment_drafts() -> list[dict]:
    objects = _list_objects(PENDING_PAYMENT_PREFIX)
    return [_object_to_video(obj) for obj in objects if _is_video_key(obj["Key"])]


def move_to_pending_payment(file_id_or_key: str) -> None:
    dest_key = _join(PENDING_PAYMENT_PREFIX, _basename(file_id_or_key))
    move_object(file_id_or_key, dest_key)


def mark_draft_delivered(file_id_or_key: str) -> None:
    dest_key = _join(PROCESSED_PREFIX, _basename(file_id_or_key))
    move_object(file_id_or_key, dest_key)


def delete_review_drafts() -> int:
    objects = [obj for obj in _list_objects(REVIEW_PREFIX) if _is_video_key(obj["Key"])]
    for obj in objects:
        delete_object(obj["Key"])
    return len(objects)


def restore_processed_to_raw() -> int:
    """Global processed/ -> raw/ sweep (legacy, batch-less runs only), by verified COPY.

    Sources are never moved or deleted: processed/ keeps its copy. A batch-scoped run must restore
    from its frozen manifest instead (pipeline.r2_batch_restore).
    """
    if os.getenv("RAW_BATCH_ID", "").strip() or os.getenv("BATCH_ID", "").strip():
        raise RuntimeError(
            "global processed/ restore is forbidden when a batch id is set; "
            "use the manifest-driven batch restore"
        )
    restored = 0
    for obj in _list_objects(PROCESSED_PREFIX):
        key = obj["Key"]
        if not _is_video_key(key):
            continue
        # Preserve the relative path: flattening processed/<batch>/x to raw/x is what
        # once stranded a verified batch outside its raw/<batch>/ namespace.
        dest_key = RAW_PREFIX + key[len(PROCESSED_PREFIX):]
        ensure_raw_copy(key, dest_key)
        restored += 1
    return restored


def record_failure(file_id_or_key: str, max_failures: int = 3) -> bool:
    failed = _load_failed_ids()
    failed[file_id_or_key] = failed.get(file_id_or_key, 0) + 1
    _save_failed_ids(failed)
    return failed[file_id_or_key] >= max_failures


def flag_quality_issue(file_id_or_key: str, reasons: str) -> None:
    key = f"{METADATA_PREFIX}quality_flags/{quote(file_id_or_key, safe='')}.json"
    body = json.dumps(
        {"source_key": file_id_or_key, "reasons": reasons},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=body,
        ContentType="application/json",
    )
