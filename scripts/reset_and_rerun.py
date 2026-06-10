"""
scripts/reset_and_rerun.py
---------------------------
1. Delete all MP4 files from the REVIEW folder (draft reels from prior run).
2. Move files back from PROCESSED folder → RAW folder (so they can be re-processed).
3. Clear processed.json (local state cache).
4. Invoke the pipeline.
"""

import json
import os
import sys
import ssl
import time

# Bypass self-signed cert in this environment
ssl._create_default_https_context = ssl._create_unverified_context
import httplib2 as _httplib2
_orig_http_init = _httplib2.Http.__init__
def _http_init_no_verify(self, *args, **kwargs):
    kwargs.setdefault("disable_ssl_certificate_validation", True)
    _orig_http_init(self, *args, **kwargs)
_httplib2.Http.__init__ = _http_init_no_verify

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import config
from google.oauth2 import service_account
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _get_user_service():
    """User OAuth service for operations on user-owned files (delete, move)."""
    token_file = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")
    if os.path.exists(token_file):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(token_file, _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        return build("drive", "v3", credentials=creds)
    return _get_service()


def _list_folder(service, folder_id: str) -> list[dict]:
    files = []
    page_token = None
    while True:
        kwargs = dict(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=1000,
        )
        if page_token:
            kwargs["pageToken"] = page_token
        page = service.files().list(**kwargs).execute()
        files.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    return files


def _move_file(service, file_id: str, from_folder: str, to_folder: str) -> None:
    service.files().update(
        fileId=file_id,
        addParents=to_folder,
        removeParents=from_folder,
        fields="id, parents",
    ).execute()


def step1_delete_review_drafts(service, user_service):
    print("\n── Step 1: Delete draft reels from REVIEW folder ─────────────────")
    files = _list_folder(service, config.REVIEW_FOLDER_ID)
    mp4s = [f for f in files if "video" in f.get("mimeType", "") or f["name"].endswith(".mp4")]
    if not mp4s:
        print("  No draft videos found in REVIEW folder.")
        return
    for f in mp4s:
        deleted = False
        for svc in (user_service, service):
            try:
                svc.files().delete(fileId=f["id"]).execute()
                print(f"  🗑  Deleted: {f['name']}")
                deleted = True
                break
            except Exception:
                pass
        if not deleted:
            # Trash it as fallback
            try:
                user_service.files().update(fileId=f["id"], body={"trashed": True}).execute()
                print(f"  🗑  Trashed: {f['name']}")
            except Exception as e:
                print(f"  ⚠️  Could not delete/trash {f['name']}: {e}")


def step2_restore_processed_to_raw(service):
    print("\n── Step 2: Move files from PROCESSED → RAW ────────────────────────")
    files = _list_folder(service, config.PROCESSED_FOLDER_ID)
    videos = [f for f in files if "video" in f.get("mimeType", "") or
              any(f["name"].lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mkv"))]
    if not videos:
        print("  No video files found in PROCESSED folder.")
        return
    for f in videos:
        try:
            _move_file(service, f["id"], config.PROCESSED_FOLDER_ID, config.RAW_FOLDER_ID)
            print(f"  ↩️  Restored: {f['name']}")
        except Exception as e:
            print(f"  ⚠️  Could not move {f['name']}: {e}")


def step3_clear_local_state():
    print("\n── Step 3: Clear local processed.json ─────────────────────────────")
    with open(config.PROCESSED_IDS_FILE, "w") as f:
        json.dump([], f)
    print("  ✅ processed.json cleared")

    failed_path = os.path.join(
        os.path.dirname(os.path.abspath(config.PROCESSED_IDS_FILE)),
        "failed_ids.json"
    )
    if os.path.exists(failed_path):
        with open(failed_path, "w") as f:
            json.dump({}, f)
        print("  ✅ failed_ids.json cleared")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Reset the pipeline so the same RAW footage can be re-processed "
                    "without re-uploading, then (optionally) run it."
    )
    parser.add_argument("--reset-only", action="store_true",
                        help="Reset Drive folders + local state but do NOT run the pipeline.")
    parser.add_argument("--keep-drafts", action="store_true",
                        help="Do not delete existing draft reels in the REVIEW folder.")
    parser.add_argument("--no-restore", action="store_true",
                        help="Do not move files from PROCESSED back to RAW "
                             "(use when the raw video is already in RAW).")
    args = parser.parse_args()

    service = _get_service()
    user_service = _get_user_service()
    if not args.keep_drafts:
        step1_delete_review_drafts(service, user_service)
    if not args.no_restore:
        step2_restore_processed_to_raw(user_service)
    step3_clear_local_state()

    if args.reset_only:
        print("\n✅ Reset complete (--reset-only) — pipeline NOT run.")
        return

    print("\n✅ Reset complete — running pipeline...\n")
    print("=" * 60)

    # Run pipeline inline
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE),
        ],
    )
    from integrations.observability import init_sentry
    init_sentry()
    from pipeline.orchestrator import main as pipeline_main
    pipeline_main()


if __name__ == "__main__":
    main()
