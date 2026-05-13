"""
pipeline/drive.py — Google Drive integration.
סורק תיקיית RAW, מוריד סרטונים חדשים, מעלה קליפים מוכנים.
"""

import json
import logging
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import config

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

# ── Auth ───────────────────────────────────────────────────────────────────

def _get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=_SCOPES,
    )
    return build("drive", "v3", credentials=creds)


# ── Processed-IDs local state ──────────────────────────────────────────────

def _load_processed_ids() -> set[str]:
    if not Path(config.PROCESSED_IDS_FILE).exists():
        return set()
    try:
        with open(config.PROCESSED_IDS_FILE) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_processed_ids(ids: set[str]) -> None:
    with open(config.PROCESSED_IDS_FILE, "w") as f:
        json.dump(list(ids), f, indent=2)


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

        # Recover IDs that are in Drive PROCESSED folder but missing from the local cache
        drive_ids = _sync_processed_from_drive(service)
        recovered = drive_ids - already_done
        if recovered:
            logger.info("Recovered %d processed IDs from Drive PROCESSED folder", len(recovered))
            _save_processed_ids(already_done | recovered)
            already_done |= recovered

        query = (
            f"'{config.RAW_FOLDER_ID}' in parents "
            "and mimeType contains 'video/' "
            "and trashed = false"
        )
        all_files: list[dict] = []
        page_token: str | None = None
        while True:
            kwargs: dict = dict(
                q=query,
                fields="nextPageToken, files(id, name, size, createdTime)",
                pageSize=1000,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            page = service.files().list(**kwargs).execute()
            all_files.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        logger.error("❌ Failed to list Drive folder: %s", e)
        print(f"❌ Failed to list Drive folder: {e}")
        return []

    new_files = [f for f in all_files if f["id"] not in already_done]
    print(f"✅ Found {len(new_files)} new video(s) (skipped {len(all_files) - len(new_files)} already processed)")
    return new_files


def download_video(file_id: str, filename: str) -> str:
    """
    Download a Drive file to TMP_DIR.
    Returns the local file path.
    """
    os.makedirs(config.TMP_DIR, exist_ok=True)
    local_path = os.path.join(config.TMP_DIR, filename)
    print(f"📁 Downloading '{filename}' → {local_path}")

    try:
        service = _get_drive_service()
        request = service.files().get_media(fileId=file_id)
        with open(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                pct = int(status.progress() * 100)
                print(f"  ⬇️  {pct}%", end="\r")
        print(f"\n✅ Download complete: {local_path}")
        return local_path
    except Exception as e:
        logger.error("❌ Failed to download %s: %s", filename, e)
        print(f"❌ Download failed for '{filename}': {e}")
        raise


def upload_clip(clip_path: str, clip_name: str) -> str:
    """
    Upload a finished clip to CLIPS_FOLDER_ID.
    Returns the shareable Drive web link.
    """
    print(f"📁 Uploading clip '{clip_name}'...")
    try:
        service = _get_drive_service()
        file_metadata = {
            "name": clip_name,
            "parents": [config.CLIPS_FOLDER_ID],
        }
        media = MediaFileUpload(clip_path, mimetype="video/mp4", resumable=True)
        uploaded = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
        file_id = uploaded.get("id", "")
        link    = uploaded.get("webViewLink", "")

        # Grant "anyone with the link" viewer access so the client can open it
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
            ).execute()
        except Exception as perm_err:
            logger.warning("⚠️ Could not set public permission on %s: %s", clip_name, perm_err)

        print(f"✅ Clip uploaded (public link): {link}")
        logger.info("Uploaded clip %s → %s", clip_name, link)
        return link
    except Exception as e:
        logger.error("❌ Failed to upload %s: %s", clip_name, e)
        print(f"❌ Upload failed for '{clip_name}': {e}")
        raise


def mark_as_processed(file_id: str) -> None:
    """
    Record file_id in processed.json so it won't be picked up again.
    Also moves the original to PROCESSED_FOLDER_ID in Drive.
    """
    ids = _load_processed_ids()
    ids.add(file_id)
    _save_processed_ids(ids)
    print(f"✅ Marked {file_id} as processed")

    # Move original to the PROCESSED archive folder
    try:
        service = _get_drive_service()
        file_meta = service.files().get(fileId=file_id, fields="parents").execute()
        current_parents = ",".join(file_meta.get("parents", []))
        service.files().update(
            fileId=file_id,
            addParents=config.PROCESSED_FOLDER_ID,
            removeParents=current_parents,
            fields="id, parents",
        ).execute()
        print(f"📁 Moved original {file_id} to PROCESSED folder")
    except Exception as e:
        logger.warning("⚠️ Could not move file %s to PROCESSED folder: %s", file_id, e)
        print(f"⚠️ Could not move original to PROCESSED folder: {e}")
