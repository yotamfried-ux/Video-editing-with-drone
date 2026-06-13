"""Supabase integration — publish reels and track pipeline status."""

import logging
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from supabase import create_client, Client
import config

logger = logging.getLogger(__name__)

_client: Client | None = None


def _supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client


def _get_drive_recording_date(file_id: str) -> str:
    """Return YYYY-MM-DD from Drive file createdTime metadata."""
    from integrations.drive import _get_drive_service
    svc = _get_drive_service()
    meta = svc.files().get(fileId=file_id, fields="createdTime").execute()
    return meta["createdTime"][:10]


def publish_reel_approved(
    preview_path: str,
    draft_name: str,
    drive_file_id: str,
    reel_meta: dict,
) -> str:
    """Upload 480p preview to Cloudflare Stream + Supabase Storage at approval time.

    Called from Phase 2a so reels appear in Discover immediately after operator approval,
    before payment. Returns the new reel_id (UUID string).
    """
    from integrations.cloudflare_stream import upload_to_stream

    recording_date = _get_drive_recording_date(drive_file_id)
    reel_id = str(uuid4())
    storage_path = f"{recording_date}/{reel_id}_preview.mp4"

    stream_uid = None
    try:
        stream_uid = upload_to_stream(preview_path)
    except Exception:
        logger.warning("Cloudflare Stream upload failed for preview %s", preview_path)

    with open(preview_path, "rb") as f:
        _supabase().storage.from_("reels").upload(storage_path, f)

    _supabase().table("reels").insert({
        "id": reel_id,
        "sport": reel_meta.get("sport", "unknown"),
        "athlete_desc": reel_meta.get("description", ""),
        "recording_date": recording_date,
        "stream_uid": stream_uid,
        "storage_path": storage_path,
        "source_video": draft_name,
        "status": "published",
        "token": token_urlsafe(8),
    }).execute()

    return reel_id


def publish_reel(local_path: str, athlete_desc: str, sport: str, drive_file_id: str) -> str:
    """Upload reel to Cloudflare Stream + Supabase Storage, insert DB row. Returns share URL."""
    from integrations.cloudflare_stream import upload_to_stream

    recording_date = _get_drive_recording_date(drive_file_id)
    reel_id = str(uuid4())
    storage_path = f"{recording_date}/{reel_id}.mp4"

    try:
        stream_uid = upload_to_stream(local_path)
    except Exception:
        logger.exception("Cloudflare Stream upload failed for %s", local_path)
        stream_uid = None

    with open(local_path, "rb") as f:
        _supabase().storage.from_("reels").upload(storage_path, f)

    share_token = token_urlsafe(8)
    _supabase().table("reels").insert({
        "id": reel_id,
        "sport": sport,
        "athlete_desc": athlete_desc,
        "recording_date": recording_date,
        "stream_uid": stream_uid,
        "storage_path": storage_path,
        "source_video": Path(local_path).name,
        "status": "published",
        "token": share_token,
    }).execute()

    domain = getattr(config, "APP_DOMAIN", "sportreel.app")
    return f"https://{domain}/reel/{share_token}"


def record_draft(draft_name: str, sources: list[dict],
                 sport: str, athlete_desc: str) -> None:
    """Upsert the draft → raw-source mapping (drafts table). Enables operator
    reprocess requests to find which raw videos produced a given draft."""
    _supabase().table("drafts").upsert({
        "draft_name":   draft_name,
        "sources":      sources,
        "sport":        sport,
        "athlete_desc": athlete_desc,
    }).execute()


def lookup_draft_sources(draft_name: str) -> list[dict]:
    """Return [{"id": drive_file_id, "name": filename}] for a draft, or []."""
    res = (_supabase().table("drafts").select("sources")
           .eq("draft_name", draft_name).limit(1).execute())
    if res.data:
        return res.data[0].get("sources") or []
    return []


def fetch_pending_reprocess() -> list[dict]:
    """Operator reprocess requests not yet acted on."""
    res = (_supabase().table("reprocess_requests").select("*")
           .eq("status", "pending").order("created_at").execute())
    return res.data or []


def mark_reprocess(req_id: str, status: str) -> None:
    from datetime import datetime, timezone
    _supabase().table("reprocess_requests").update({
        "status":       status,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", req_id).execute()


def close_queued_reprocess() -> None:
    """Mark all 'queued' requests as done — called after a successful run that
    consumed them (their sources were processed in this run)."""
    from datetime import datetime, timezone
    _supabase().table("reprocess_requests").update({
        "status":       "done",
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("status", "queued").execute()


def write_pipeline_status(stage: str, progress: float, **meta) -> None:
    """Upsert pipeline_status table (id=1). Called from orchestrator to show progress in app."""
    try:
        from pipeline.run_context import get_run_id
        rid = get_run_id()
        if rid:
            meta = {**meta, "run_id": rid}
        _supabase().table("pipeline_status").upsert({
            "id": 1,
            "stage": stage,
            "progress": round(progress, 4),
            "meta": meta,
        }).execute()
    except Exception:
        logger.warning("Failed to write pipeline status (non-critical)")
