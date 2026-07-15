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
from pathlib import Path

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


def _storage_backend_name() -> str:
    return os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _is_revoked_oauth_credentials(exc: Exception) -> bool:
    text = str(exc).lower()
    return "invalid_grant" in text or "expired or revoked" in text


def _get_user_service():
    """User OAuth service for operations on user-owned files.

    When the stored OAuth refresh credentials can no longer refresh, use the
    service account as a fallback. Per-file Drive permission failures are still
    logged later by the reset steps.
    """
    token_file = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")
    if os.path.exists(token_file):
        from google.oauth2.credentials import Credentials
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request

        try:
            creds = Credentials.from_authorized_user_file(token_file, _SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_file, "w") as f:
                    f.write(creds.to_json())
            return build("drive", "v3", credentials=creds)
        except RefreshError as exc:
            if not _is_revoked_oauth_credentials(exc):
                raise
            print(
                "⚠️ Stored Drive OAuth credentials are expired or revoked. "
                "Falling back to the service account for reset operations."
            )
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


def step0_delete_approved(service, user_service, dry_run: bool = False):
    print("\n── Step 0: Delete generated outputs from APPROVED folder ──────────")
    files = _list_folder(service, config.APPROVED_FOLDER_ID)
    mp4s = [f for f in files if "video" in f.get("mimeType", "") or f["name"].endswith(".mp4")]
    if not mp4s:
        print("  No video files found in APPROVED folder.")
        return
    if dry_run:
        for f in mp4s:
            print(f"  [dry-run] Would delete from APPROVED: {f['name']}")
        return
    for f in mp4s:
        deleted = False
        for svc in (user_service, service):
            try:
                svc.files().delete(fileId=f["id"]).execute()
                print(f"  🗑  Deleted from APPROVED: {f['name']}")
                deleted = True
                break
            except Exception:
                pass
        if not deleted:
            try:
                user_service.files().update(fileId=f["id"], body={"trashed": True}).execute()
                print(f"  🗑  Trashed from APPROVED: {f['name']}")
            except Exception as e:
                print(f"  ⚠️  Could not delete/trash {f['name']} from APPROVED: {e}")


def step1_delete_review_drafts(service, user_service, dry_run: bool = False):
    print("\n── Step 1: Delete draft reels from REVIEW folder ─────────────────")
    files = _list_folder(service, config.REVIEW_FOLDER_ID)
    mp4s = [f for f in files if "video" in f.get("mimeType", "") or f["name"].endswith(".mp4")]
    if not mp4s:
        print("  No draft videos found in REVIEW folder.")
        return
    if dry_run:
        for f in mp4s:
            print(f"  [dry-run] Would delete from REVIEW: {f['name']}")
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


def step2_restore_processed_to_raw(service, dry_run: bool = False):
    print("\n── Step 2: Move files from PROCESSED → RAW ────────────────────────")
    files = _list_folder(service, config.PROCESSED_FOLDER_ID)
    # Log everything so we can see what's there even when the filter misses it
    for f in files:
        print(f"  📄 found in PROCESSED: {f['name']} (mimeType={f.get('mimeType', 'unknown')})")
    # Move ALL files — PROCESSED only ever holds processed source footage.
    # A type filter here caused silent skips when mimeType was octet-stream
    # or the extension wasn't in our list.
    videos = files
    if not videos:
        print("  No files found in PROCESSED folder.")
        return
    if dry_run:
        for f in videos:
            print(f"  [dry-run] Would restore to RAW: {f['name']}")
        return

    errors = []
    restored_ids: set[str] = set()
    for f in videos:
        try:
            _move_file(service, f["id"], config.PROCESSED_FOLDER_ID, config.RAW_FOLDER_ID)
            print(f"  ↩️  Restored: {f['name']}")
            restored_ids.add(f["id"])
        except Exception as e:
            print(f"  ❌ Could not move {f['name']}: {e}")
            errors.append(f"{f['name']}: {e}")

    if errors:
        print(f"\n❌ {len(errors)} file(s) failed to restore from PROCESSED → RAW:")
        for err in errors:
            print(f"   • {err}")
        sys.exit(
            "❌ Step 2 failed — aborting reset to prevent a false 'No new videos' on next run.\n"
            "   Fix the Drive permissions above, then run reset_and_rerun.py again."
        )

    # Verify: re-list PROCESSED and confirm all restored videos are gone.
    # _sync_processed_from_drive() in the pipeline will re-add any IDs still in
    # PROCESSED, causing the source to be silently skipped.  Fail hard here if
    # the move didn't stick.
    print("  🔍 Verifying move (re-scanning PROCESSED folder)...")
    remaining = _list_folder(service, config.PROCESSED_FOLDER_ID)
    still_there = [f for f in remaining if f["id"] in restored_ids]
    if still_there:
        names = ", ".join(f["name"] for f in still_there)
        sys.exit(
            f"❌ Verification failed — {len(still_there)} file(s) still in PROCESSED after move: {names}\n"
            "   The pipeline would silently skip them.  Check Drive folder permissions and retry."
        )
    print(f"  ✅ Verified: {len(restored_ids)} video(s) moved to RAW, PROCESSED is clean.")


def step3_clear_local_state(dry_run: bool = False):
    print("\n── Step 3: Clear local processed.json ─────────────────────────────")
    if dry_run:
        print(f"  [dry-run] Would clear: {config.PROCESSED_IDS_FILE}")
        failed_path = os.path.join(
            os.path.dirname(os.path.abspath(config.PROCESSED_IDS_FILE)),
            "failed_ids.json"
        )
        if os.path.exists(failed_path):
            print(f"  [dry-run] Would clear: {failed_path}")
        return
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


def _r2_delete_prefix(prefix: str, label: str, dry_run: bool = False) -> int:
    from integrations import r2_storage

    objects = r2_storage.list_objects(prefix)
    videos = [obj for obj in objects if r2_storage._is_video_key(obj["Key"])]
    if not videos:
        print(f"  No video files found in {label}.")
        return 0
    if dry_run:
        for obj in videos:
            print(f"  [dry-run] Would delete from {label}: {obj['Key']}")
        return 0
    for obj in videos:
        r2_storage.delete_object(obj["Key"])
        print(f"  🗑  Deleted from {label}: {obj['Key']}")
    return len(videos)


def _reset_r2(args) -> bool:
    if _storage_backend_name() == "drive":
        return False
    if _storage_backend_name() != "r2":
        raise RuntimeError(f"Unsupported STORAGE_BACKEND for reset: {_storage_backend_name()}")

    from integrations import r2_storage
    print("\n☁️  R2 reset mode")
    if args.full_clean:
        print("\n── Step 0: Delete generated outputs from approved/ ────────────────")
        _r2_delete_prefix(r2_storage.APPROVED_PREFIX, "approved/", dry_run=args.dry_run)
    if not args.keep_drafts:
        print("\n── Step 1: Delete draft reels from review/ ────────────────────────")
        _r2_delete_prefix(r2_storage.REVIEW_PREFIX, "review/", dry_run=args.dry_run)
    if not args.no_restore:
        print("\n── Step 2: Move objects from processed/ → raw/ ────────────────────")
        if args.dry_run:
            processed = r2_storage.list_objects(r2_storage.PROCESSED_PREFIX)
            if not processed:
                print("  No objects found in processed/.")
            for obj in processed:
                print(f"  [dry-run] Would restore to raw/: {obj['Key']}")
        else:
            restored = r2_storage.restore_processed_to_raw()
            print(f"  ✅ Restored {restored} object(s) to raw/.")
    step3_clear_local_state(dry_run=args.dry_run)
    return True


def _run_pipeline_inline() -> None:
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
    from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches
    install_pre_orchestrator_patches()
    from pipeline.orchestrator import main as pipeline_main
    install_post_orchestrator_patches()
    pipeline_main()


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
    parser.add_argument("--full-clean", action="store_true",
                        help="Also delete generated outputs from the APPROVED folder "
                             "(use for a complete test reset including previously approved reels).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be deleted/moved without making any changes.")
    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN — no changes will be made\n")

    if _reset_r2(args):
        if args.dry_run:
            print("\n✅ Dry run complete — nothing was changed.")
            return
        if args.reset_only:
            print("\n✅ Reset complete (--reset-only) — pipeline NOT run.")
            return
        _run_pipeline_inline()
        return

    service = _get_service()
    user_service = _get_user_service()

    if args.full_clean:
        step0_delete_approved(service, user_service, dry_run=args.dry_run)
    if not args.keep_drafts:
        step1_delete_review_drafts(service, user_service, dry_run=args.dry_run)
    if not args.no_restore:
        step2_restore_processed_to_raw(service, dry_run=args.dry_run)
    step3_clear_local_state(dry_run=args.dry_run)

    if args.dry_run:
        print("\n✅ Dry run complete — nothing was changed.")
        return

    if args.reset_only:
        print("\n✅ Reset complete (--reset-only) — pipeline NOT run.")
        return

    _run_pipeline_inline()


if __name__ == "__main__":
    main()
