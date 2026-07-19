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

    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID") or os.getenv("ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("SECRET_KEY_ID"),
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


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=_bucket(), Key=key)


def move_object(source_key: str, dest_key: str) -> None:
    client = _client()
    client.copy_object(
        Bucket=_bucket(),
        CopySource={"Bucket": _bucket(), "Key": source_key},
        Key=dest_key,
    )
    client.head_object(Bucket=_bucket(), Key=dest_key)
    client.delete_object(Bucket=_bucket(), Key=source_key)


def get_new_videos() -> list[dict]:
    objects = _list_objects(RAW_PREFIX)
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


def mark_as_processed(file_id_or_key: str) -> None:
    dest_key = _join(PROCESSED_PREFIX, _basename(file_id_or_key))
    move_object(file_id_or_key, dest_key)


def requeue_video(file_id_or_key: str) -> bool:
    """Reverse of mark_as_processed: move a video processed/ -> raw/.

    The caller (operator "reprocess this reel" flow) passes back the source
    id recorded in the `drafts` table at draft-creation time, which reflects
    the object's raw/ key *before* the original run's mark_as_processed moved
    it to processed/. Unlike Drive file ids, R2 keys encode location, so this
    must always source from processed/ (mirroring the Drive adapter, which
    hardcodes PROCESSED_FOLDER_ID -> RAW_FOLDER_ID) rather than trusting
    whatever prefix happens to be on the passed-in id.
    """
    try:
        basename = _basename(file_id_or_key)
        source_key = _join(PROCESSED_PREFIX, basename)
        dest_key = _join(RAW_PREFIX, basename)
        move_object(source_key, dest_key)
        return True
    except Exception:
        return False


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
    objects = _list_objects(PROCESSED_PREFIX)
    restored = 0
    for obj in objects:
        key = obj["Key"]
        dest_key = _join(RAW_PREFIX, _basename(key))
        move_object(key, dest_key)
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
