"""
integrations/drive.py — Google Drive integration.
סורק תיקיית RAW, מוריד סרטונים חדשים, מעלה קליפים מוכנים.
"""

import json
import logging
import os
import ssl
import time as _time
from pathlib import Path

# Bypass self-signed cert in this environment
ssl._create_default_https_context = ssl._create_unverified_context
import httplib2 as _httplib2
_orig_http_init = _httplib2.Http.__init__
def _http_init_no_verify(self, *args, **kwargs):
    kwargs.setdefault("disable_ssl_certificate_validation", True)
    _orig_http_init(self, *args, **kwargs)
_httplib2.Http.__init__ = _http_init_no_verify

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import config

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

# ── Retry wrapper ─────────────────────────────────────────────────────────

def _drive_retry(fn, attempts: int = 3, base_delay: int = 5):
    """Retry on transient Drive API errors (429 / 503 / quota) with exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            transient = any(x in str(exc).lower()
                            for x in ["429", "503", "quota", "timeout", "unavailable"])
            if not transient or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Drive API retry %d/%d in %ds: %s", attempt, attempts, delay, exc)
            _time.sleep(delay)


# ── Auth ───────────────────────────────────────────────────────────────────

_USER_TOKEN_FILE = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")


def _get_drive_service():
    """Service-account credentials — used for read-only operations (list, download)."""
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=_SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def _get_upload_service():
    """User OAuth2 credentials — used for uploads so files count against the user's quota.

    Falls back to service-account if no token file exists (will fail for large uploads,
    but allows the pipeline to run in read-only / test scenarios).
    Run scripts/auth_drive_user.py once to generate the token.
    """
    if os.path.exists(_USER_TOKEN_FILE):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(_USER_TOKEN_FILE, _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(_USER_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        return build("drive", "v3", credentials=creds)
    logger.warning("No user OAuth token found (%s) — falling back to service account for uploads", _USER_TOKEN_FILE)
    return _get_drive_service()


# ── Processed-IDs local state ──────────────────────────────────────────────

def _failed_ids_path() -> str:
    base = os.path.dirname(os.path.abspath(config.PROCESSED_IDS_FILE))
    return os.path.join(base, "failed_ids.json")


def _load_failed_ids() -> dict[str, int]:
    """Returns {file_id: fail_count}."""
    try:
        with open(_failed_ids_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_failed_ids(failed: dict[str, int]) -> None:
    path = _failed_ids_path()
    tmp  = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(failed, f, indent=2)
    os.replace(tmp, path)


def record_failure(file_id: str, max_failures: int = 3) -> bool:
    """Increment fail count for file_id. Returns True when limit is reached."""
    failed = _load_failed_ids()
    failed[file_id] = failed.get(file_id, 0) + 1
    _save_failed_ids(failed)
    if failed[file_id] >= max_failures:
        logger.warning(
            "Video %s failed %d time(s) — will be permanently skipped",
            file_id, failed[file_id],
        )
        return True
    return False


def _load_processed_ids() -> set[str]:
    if not Path(config.PROCESSED_IDS_FILE).exists():
        return set()
    try:
        with open(config.PROCESSED_IDS_FILE) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_processed_ids(ids: set[str]) -> None:
    tmp = config.PROCESSED_IDS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(list(ids), f, indent=2)
    os.replace(tmp, config.PROCESSED_IDS_FILE)  # atomic on POSIX


class DriveMoveError(RuntimeError):
    """Raised when a Drive folder transition cannot be verified."""


def _parents(meta: dict) -> set[str]:
    return {p for p in meta.get("parents", []) if p}


def _move_file_between_folders(service, file_id: str, from_folder_id: str,
                               to_folder_id: str, action: str) -> str:
    """Move a Drive file and verify that the expected folder transition happened.

    Google Drive folder movement is implemented as a parent update. A failed or
    partially applied parent update must not be treated as success because the
    pipeline uses Drive folder membership as durable processing state.
    """
    file_meta = _drive_retry(lambda: service.files().get(
        fileId=file_id,
        fields="id, name, parents",
        supportsAllDrives=True,
    ).execute())
    name = file_meta.get("name", file_id)
    current = _parents(file_meta)

    if to_folder_id in current and from_folder_id not in current:
        logger.info("Drive %s already complete for %s (%s)", action, name, file_id)
        return name

    if from_folder_id not in current:
        raise DriveMoveError(
            f"Drive {action} refused for '{name}' ({file_id}): expected source "
            f"folder {from_folder_id}, current parents={sorted(current) or '[]'}"
        )

    updated = _drive_retry(lambda: service.files().update(
        fileId=file_id,
        addParents=to_folder_id,
        removeParents=",".join(sorted(current)),
        fields="id, name, parents",
        supportsAllDrives=True,
    ).execute())
    updated_parents = _parents(updated)
    if to_folder_id not in updated_parents or from_folder_id in updated_parents:
        raise DriveMoveError(
            f"Drive {action} did not complete for '{name}' ({file_id}): "
            f"parents after update={sorted(updated_parents) or '[]'}"
        )
    return updated.get("name", name)


def _move_with_available_credentials(file_id: str, from_folder_id: str,
                                     to_folder_id: str, action: str) -> str:
    """Try both Drive credential paths before failing the operator-visible state."""
    errors: list[str] = []
    for label, factory in (
        ("user OAuth/upload service", _get_upload_service),
        ("service account", _get_drive_service),
    ):
        try:
            service = factory()
            moved_name = _move_file_between_folders(
                service,
                file_id,
                from_folder_id,
                to_folder_id,
                action,
            )
            logger.info("Drive %s succeeded with %s for %s", action, label, file_id)
            return moved_name
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("Drive %s failed with %s for %s: %s", action, label, file_id, exc)
    raise DriveMoveError(f"Drive {action} failed with all credentials: {' | '.join(errors)}")


def _mark_processed_cache(file_id: str) -> None:
    ids = _load_processed_ids()
    ids.add(file_id)
    _save_processed_ids(ids)


def _sync_processed_from_drive(service) -> set[str]:
    """
    Query PROCESSED_FOLDER_ID and return the set of file IDs found there.
    Drive is source of truth; processed.json is a local cache.
    Returns an empty set silently on failure.
    """
    try:
        query = f"'{config.PROCESSED_FOLDER_ID}' in parents and trashed = false"
        ids: set[str] = set()
        page_token: str | None = None
        while True:
            kwargs: dict = dict(
                q=query,
                fields="nextPageToken, files(id)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            page = service.files().list(**kwargs).execute()
            ids.update(f["id"] for f in page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return ids
    except Exception as e:
        logger.warning("⚠️ Could not sync processed IDs from Drive: %s", e)
        return set()


# ── Public API ─────────────────────────────────────────────────────────────

def get_new_videos() -> list[dict]:
    """
    Scan RAW_FOLDER_ID for video files.
    Skip any file IDs already recorded in processed.json or found in PROCESSED_FOLDER_ID.
    Returns list of Drive file metadata dicts.
    """
    print("📁 Scanning RAW folder for new videos...")
    already_done = _load_processed_ids()

    try:
        service = _get_drive_service()

        # Recover IDs that are in Drive PROCESSED folder but missing from the local cache.
        # WARNING: if reset_and_rerun.py Step 2 (PROCESSED→RAW) failed silently, videos
        # left in PROCESSED will be re-added here and silently skipped this run.
        drive_ids = _sync_processed_from_drive(service)
        recovered = drive_ids - already_done
        if recovered:
            print(
                f"⚠️  Re-synced {len(recovered)} ID(s) from Drive PROCESSED folder "
                "(were missing from local processed.json — this is normal after a CI restart, "
                "but means those videos will NOT be re-processed this run)."
            )
            logger.info("Recovered %d processed IDs from Drive PROCESSED folder", len(recovered))
            _save_processed_ids(already_done | recovered)
            already_done |= recovered

        # No mimeType filter in the query — some files uploaded directly to Drive
        # get mimeType = "application/octet-stream" instead of "video/*", so we'd
        # miss them. We filter client-side by mimeType OR file extension instead.
        query = f"'{config.RAW_FOLDER_ID}' in parents and trashed = false"
        all_files: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict = dict(
                q=query,
                fields="nextPageToken, files(id, name, size, createdTime, mimeType)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            page = service.files().list(**kwargs).execute()
            all_files.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        logger.exception("❌ Failed to list Drive folder: %s", e)
        print(f"❌ Failed to list Drive folder: {e}")
        return []

    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".mxf"}
    video_files = [
        f for f in all_files
        if "video" in f.get("mimeType", "")
        or Path(f["name"]).suffix.lower() in _VIDEO_EXTS
    ]
    new_files = [f for f in video_files if f["id"] not in already_done]
    print(f"✅ Found {len(new_files)} new video(s) (skipped {len(video_files) - len(new_files)} already processed)")
    return new_files


def download_video(file_id: str, filename: str) -> str:
    """
    Download a Drive file to TMP_DIR.
    Writes to filename.part first, then renames atomically — a partial file is
    never visible under the final name. Returns the local file path.
    """
    os.makedirs(config.TMP_DIR, exist_ok=True)
    local_path = os.path.join(config.TMP_DIR, filename)
    tmp_path   = local_path + ".part"
    print(f"📁 Downloading '{filename}' → {local_path}")

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass

    try:
        service = _get_drive_service()
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        with open(tmp_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                pct = int(status.progress() * 100)
                print(f"  ⬇️  {pct}%", end="\r")
        os.replace(tmp_path, local_path)
        print(f"\n✅ Download complete: {local_path}")
        return local_path
    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        logger.error("❌ Failed to download %s: %s", filename, e)
        print(f"❌ Download failed for '{filename}': {e}")
        raise


def upload_draft(draft_path: str, draft_name: str) -> str:
    """Upload a draft reel to REVIEW_FOLDER_ID. Returns webViewLink."""
    print(f"📋 Uploading draft '{draft_name}' to REVIEW folder...")
    try:
        service       = _get_upload_service()
        file_metadata = {"name": draft_name, "parents": [config.REVIEW_FOLDER_ID]}
        media         = MediaFileUpload(draft_path, mimetype="video/mp4", resumable=True)
        uploaded      = _drive_retry(lambda: service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute())
        file_id = uploaded.get("id", "")
        link    = uploaded.get("webViewLink", "")
        try:
            _drive_retry(lambda: service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
                supportsAllDrives=True,
            ).execute())
        except Exception as perm_err:
            logger.warning("⚠️ Could not set public permission on draft %s: %s", draft_name, perm_err)
        print(f"✅ Draft ready for review: {link}")
        logger.info("Draft uploaded %s → %s", draft_name, link)
        return link
    except Exception as e:
        logger.error("❌ Failed to upload draft %s: %s", draft_name, e)
        print(f"❌ Draft upload failed for '{draft_name}': {e}")
        raise


def get_approved_drafts() -> list[dict]:
    """Scan APPROVED_FOLDER_ID with pagination. Returns [{id, name, webViewLink}]."""
    print("📋 Scanning APPROVED folder for ready-to-deliver reels...")
    try:
        service    = _get_drive_service()
        query      = f"'{config.APPROVED_FOLDER_ID}' in parents and trashed = false"
        files: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict = dict(
                q=query,
                fields="nextPageToken, files(id, name, webViewLink)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            page       = service.files().list(**kwargs).execute()
            files.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        print(f"✅ Found {len(files)} approved reel(s)")
        return files
    except Exception as e:
        logger.error("❌ Failed to scan APPROVED folder: %s", e)
        print(f"❌ Failed to scan APPROVED folder: {e}")
        return []


def mark_draft_delivered(file_id: str) -> None:
    """Move a delivered reel from APPROVED to PROCESSED folder."""
    try:
        _move_with_available_credentials(
            file_id,
            config.APPROVED_FOLDER_ID,
            config.PROCESSED_FOLDER_ID,
            "mark delivered draft",
        )
        logger.info("Moved delivered draft %s to PROCESSED", file_id)
    except Exception as e:
        logger.warning("⚠️ Could not move delivered draft %s: %s", file_id, e)


def upload_preview(preview_path: str, preview_name: str) -> str:
    """Upload a 480p watermarked preview to PREVIEW_FOLDER_ID. Returns webViewLink."""
    if not config.PREVIEW_FOLDER_ID:
        raise ValueError("PREVIEW_FOLDER_ID not configured — set it in .env")
    print(f"🔍 Uploading preview '{preview_name}'...")
    try:
        service       = _get_upload_service()
        file_metadata = {"name": preview_name, "parents": [config.PREVIEW_FOLDER_ID]}
        media         = MediaFileUpload(preview_path, mimetype="video/mp4", resumable=True)
        uploaded      = _drive_retry(lambda: service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute())
        file_id = uploaded.get("id", "")
        link    = uploaded.get("webViewLink", "")
        try:
            _drive_retry(lambda: service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
                supportsAllDrives=True,
            ).execute())
        except Exception as perm_err:
            logger.warning("⚠️ Could not set public permission on preview %s: %s", preview_name, perm_err)
        print(f"✅ Preview link: {link}")
        logger.info("Preview uploaded %s → %s", preview_name, link)
        return link
    except Exception as e:
        logger.error("❌ Failed to upload preview %s: %s", preview_name, e)
        raise


def move_to_pending_payment(file_id: str) -> None:
    """Move a reel from APPROVED_FOLDER_ID → PENDING_PAYMENT_FOLDER_ID."""
    if not config.PENDING_PAYMENT_FOLDER_ID:
        logger.warning("⚠️ PENDING_PAYMENT_FOLDER_ID not configured — skipping move for %s", file_id)
        return
    try:
        _move_with_available_credentials(
            file_id,
            config.APPROVED_FOLDER_ID,
            config.PENDING_PAYMENT_FOLDER_ID,
            "move reel to pending payment",
        )
        logger.info("Moved reel %s → PENDING_PAYMENT", file_id)
    except Exception as e:
        logger.warning("⚠️ Could not move %s to PENDING_PAYMENT: %s", file_id, e)


def get_pending_payment_drafts() -> list[dict]:
    """Scan PENDING_PAYMENT_FOLDER_ID for reels awaiting payment. Returns [{id, name, webViewLink}]."""
    if not config.PENDING_PAYMENT_FOLDER_ID:
        logger.warning("⚠️ PENDING_PAYMENT_FOLDER_ID not configured")
        return []
    print("💳 Scanning PENDING_PAYMENT folder for reels awaiting payment...")
    try:
        service    = _get_drive_service()
        query      = f"'{config.PENDING_PAYMENT_FOLDER_ID}' in parents and trashed = false"
        files: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict = dict(
                q=query,
                fields="nextPageToken, files(id, name, webViewLink)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            page       = service.files().list(**kwargs).execute()
            files.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        print(f"✅ Found {len(files)} reel(s) awaiting payment")
        return files
    except Exception as e:
        logger.error("❌ Failed to scan PENDING_PAYMENT folder: %s", e)
        return []


def mark_as_processed(file_id: str) -> None:
    """
    Move the original to PROCESSED_FOLDER_ID and only then record file_id in
    processed.json so a failed Drive archive never creates a skipped RAW file.
    """
    try:
        moved_name = _move_with_available_credentials(
            file_id,
            config.RAW_FOLDER_ID,
            config.PROCESSED_FOLDER_ID,
            "archive processed raw",
        )
    except Exception as e:
        logger.error(
            "❌ Could not archive processed raw %s. Not updating %s: %s",
            file_id,
            config.PROCESSED_IDS_FILE,
            e,
        )
        print(
            f"❌ Could not move original {file_id} to PROCESSED. "
            "It was not marked as processed, so the next run can retry."
        )
        raise

    _mark_processed_cache(file_id)
    print(f"📁 Moved original '{moved_name}' ({file_id}) to PROCESSED folder")
    print(f"✅ Marked {file_id} as processed")


def requeue_video(file_id: str) -> bool:
    """Reverse of mark_as_processed: move a raw video PROCESSED → RAW and remove
    its ID from processed.json so the next scan picks it up again. Used by the
    operator 'reprocess this reel' flow. Returns True on success."""
    try:
        moved_name = _move_with_available_credentials(
            file_id,
            config.PROCESSED_FOLDER_ID,
            config.RAW_FOLDER_ID,
            "requeue processed raw",
        )
        ids = _load_processed_ids()
        ids.discard(file_id)
        _save_processed_ids(ids)
        print(f"↩️  Re-queued '{moved_name}' for reprocessing")
        return True
    except Exception as e:
        logger.warning("⚠️ Could not requeue file %s: %s", file_id, e)
        return False


def flag_quality_issue(file_id: str, reasons: str) -> None:
    """Update the raw video's Drive description with a quality flag for operator visibility."""
    try:
        service = _get_drive_service()
        _drive_retry(lambda: service.files().update(
            fileId=file_id,
            body={"description": f"[QUALITY FLAG: {reasons}]"},
            fields="id, description",
            supportsAllDrives=True,
        ).execute())
        logger.info("Drive quality flag set on %s: %s", file_id, reasons)
    except Exception as exc:
        logger.warning("Could not set Drive quality flag on %s: %s", file_id, exc)
