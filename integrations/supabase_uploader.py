"""Supabase integration — publish reels and track pipeline status."""

import logging
from pathlib import Path
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

    row = _supabase().table("reels").insert({
        "id": reel_id,
        "sport": sport,
        "athlete_desc": athlete_desc,
        "recording_date": recording_date,
        "stream_uid": stream_uid,
        "storage_path": storage_path,
        "source_video": Path(local_path).name,
    }).execute()

    token = row.data[0]["token"]
    domain = getattr(config, "APP_DOMAIN", "sportreel.app")
    return f"https://{domain}/reel/{token}"


def write_pipeline_status(stage: str, progress: float, **meta) -> None:
    """Upsert pipeline_status table (id=1). Called from orchestrator to show progress in app."""
    try:
        _supabase().table("pipeline_status").upsert({
            "id": 1,
            "stage": stage,
            "progress": round(progress, 4),
            "meta": meta,
        }).execute()
    except Exception:
        logger.warning("Failed to write pipeline status (non-critical)")
