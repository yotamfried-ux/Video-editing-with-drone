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


def _restore_r2_sources_to_raw(*, dry_run: bool = False) -> int:
    """Recover processed source videos to flat raw/; never overwrite a RAW file."""
    from integrations import r2_storage as r2
    # Source locations include legacy batch directories under both prefixes.
    raw_objects = r2.list_objects(r2.RAW_PREFIX)
    existing = {obj["Key"] for obj in raw_objects
                if "/" not in obj["Key"][len(r2.RAW_PREFIX):]}
    sources = [
        obj for obj in r2.list_objects(r2.PROCESSED_PREFIX)
        if r2._is_video_key(obj["Key"])
    ] + [
        obj for obj in raw_objects
        if r2._is_video_key(obj["Key"])
        and "/" in obj["Key"][len(r2.RAW_PREFIX):]
    ]
    # Fail closed: processed/ may also hold generated outputs.
    from integrations.source_uploads import get_source_upload
    for obj in sources:
        key = obj["Key"]
        if key.startswith(r2.PROCESSED_PREFIX):
            source_suffix = key.removeprefix(r2.PROCESSED_PREFIX)
            evidence = get_source_upload(f"{r2.RAW_PREFIX}{source_suffix}") or get_source_upload(key)
            if not evidence or str(evidence.get("status") or "") not in {"verified", "superseded", "removed"}:
                raise RuntimeError(f"Unverified processed source provenance: {key}; reset aborted")
    planned = {}
    for obj in sources:
        source = obj["Key"]
        dest = r2.RAW_PREFIX + source.rsplit("/", 1)[-1]
        if dest in planned:
            raise RuntimeError(f"RAW restore collision at {dest}; no files were changed")
        planned[dest] = source
    # An existing destination is never overwritten. Identical bytes mean a
    # previous restore already completed; differing bytes are a hard collision.
    # Hash the R2 bodies rather than trusting ContentLength or multipart ETags.
    def sha256(key):
        import hashlib
        stream = r2._client().get_object(Bucket=r2._bucket(), Key=key)["Body"]
        digest = hashlib.sha256()
        try:
            for chunk in stream.iter_chunks(chunk_size=1024 * 1024):
                if chunk:
                    digest.update(chunk)
        finally:
            stream.close()
        return digest.digest()
    for dest, source in list(planned.items()):
        if dest in existing:
            if sha256(source) != sha256(dest):
                raise RuntimeError(f"RAW restore collision at {dest}; no files were changed")
            del planned[dest]
    if dry_run:
        for dest, source in planned.items():
            print(f"  [dry-run] Would restore {source} -> {dest}")
        return len(planned)
    # Preserve originals until every destination is copied and size-verified.
    for dest, source in planned.items():
        r2.copy_object(source, dest)
        client = r2._client()
        src_head = client.head_object(Bucket=r2._bucket(), Key=source)
        dst_head = client.head_object(Bucket=r2._bucket(), Key=dest)
        if src_head["ContentLength"] != dst_head["ContentLength"]:
            raise RuntimeError(f"Restore size mismatch: {source} -> {dest}")
        if sha256(source) != sha256(dest):
            raise RuntimeError(f"Restore checksum mismatch: {source} -> {dest}")
    # Retain the source objects: a successful copy must never be treated as
    # permission to delete original footage. Repeated resets with colliding
    # destination names fail closed until provenance can be reconciled.
    return len(planned)


def _reset_r2(args) -> bool:
    if _storage_backend_name() == "drive":
        return False
    if _storage_backend_name() != "r2":
        raise RuntimeError(f"Unsupported STORAGE_BACKEND for reset: {_storage_backend_name()}")
    from integrations import r2_storage
    # Recover all originals before deleting any generated outputs.
    if not args.no_restore:
        if os.getenv("RAW_BATCH_ID") or os.getenv("BATCH_ID"):
            from pipeline.r2_batch_scope import ensure_frozen_inputs
            report = ensure_frozen_inputs(restore=not args.dry_run)
            print(f"  Frozen inputs: {report.summary()}")
        else:
            restored = _restore_r2_sources_to_raw(dry_run=args.dry_run)
            print(f"  Restored or planned {restored} source videos to RAW")
    if args.full_clean:
        _r2_delete_prefix(r2_storage.APPROVED_PREFIX, "approved/", dry_run=args.dry_run)
    if not args.keep_drafts:
        _r2_delete_prefix(r2_storage.REVIEW_PREFIX, "review/", dry_run=args.dry_run)
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
