"""Supabase integration — publish reels and track pipeline status."""

import logging
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from supabase import create_client, Client
import config

logger = logging.getLogger(__name__)

_client: Client | None = None
_ACTIVE_REEDIT_STATUSES = ("qa_blocked", "pending", "queued")


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


def _resolve_athlete(athlete_key: str | None, description: str) -> str | None:
    """Persistent athlete id for a pipeline athlete key (`<recording date>:<run athlete id>`).

    Reels cut from one session for one athlete share the key, so they share the athlete. A new key gets a
    new athlete; joining athletes across sessions is an operator decision (web-api athletes merge), never
    automatic: clothing and boards change between days and the product does not use biometrics.
    """
    if not athlete_key:
        return None
    known = (_supabase().table("reels").select("athlete_id").eq("athlete_key", athlete_key)
             .not_.is_("athlete_id", "null").limit(1).execute())
    if known.data:
        return known.data[0]["athlete_id"]
    athlete_id = str(uuid4())
    _supabase().table("athletes").insert({"id": athlete_id, "label": (description or "")[:200]}).execute()
    return athlete_id


def lookup_draft_record(draft_name: str) -> dict:
    """The pipeline's own record of a draft (sport, athlete description, athlete key).

    Delivery runs in a different job from the pipeline, so the pipeline's local reels_metadata.json is not
    there; without this every Discover reel was published as sport "unknown" with no description.
    """
    try:
        res = (_supabase().table("drafts").select("*").eq("draft_name", draft_name).limit(1).execute())
    except Exception as exc:
        logger.warning("Draft record lookup failed for %s: %s", draft_name, exc)
        return {}
    return dict(res.data[0]) if res.data else {}


def publish_reel_approved(
    preview_path: str,
    draft_name: str,
    drive_file_id: str,
    reel_meta: dict,
    full_path: str | None = None,
    preview_duration: float | None = None,
    full_duration: float | None = None,
    athlete_key: str | None = None,
) -> str:
    """Publish an approved reel to Discover at approval time. Returns the new reel_id (UUID string).

    Two objects go to the private `reels` bucket:
      - the preview (short, small, watermarked): `storage_path`, the only file Discover ever streams;
      - the clean full-length reel (`full_path`): `full_storage_path`, signed only after a verified payment.
    """
    # R2 object keys are not Google Drive file IDs. Prefer explicit metadata,
    # then a date encoded in the draft name. Drive keeps its authoritative
    # createdTime lookup.
    if str(drive_file_id).startswith(("approved/", "pending_payment/", "review/", "processed/", "raw/")):
        from datetime import date
        import re
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", draft_name) or re.search(r"_(20\d{2})(\d{2})(\d{2})(?:\D|$)", draft_name)
        encoded = None
        if match:
            encoded = match.group(1) if match.lastindex == 1 else "-".join(match.groups())
        recording_date = str(reel_meta.get("recording_date") or encoded or date.today().isoformat())
    else:
        recording_date = _get_drive_recording_date(drive_file_id)
    reel_id = str(uuid4())
    storage_path = f"{recording_date}/{reel_id}_preview.mp4"
    full_storage_path = f"{recording_date}/{reel_id}_full.mp4" if full_path else None

    # reels.stream_uid is UUID-typed in Supabase, while Cloudflare Stream returns an opaque provider UID.
    # Discover serves the preview from Supabase Storage, so Stream is not used here.
    stream_uid = None

    with open(preview_path, "rb") as f:
        _supabase().storage.from_("reels").upload(
            storage_path,
            f,
            file_options={"content-type": "video/mp4"},
        )
    if full_path:
        with open(full_path, "rb") as f:
            _supabase().storage.from_("reels").upload(
                full_storage_path,
                f,
                file_options={"content-type": "video/mp4"},
            )

    row = {
        "id": reel_id,
        "sport": reel_meta.get("sport", "unknown"),
        "athlete_desc": reel_meta.get("description", ""),
        "recording_date": recording_date,
        "stream_uid": stream_uid,
        "storage_path": storage_path,
        "source_video": draft_name,
        "status": "published",
        # token is a UUID column in the production schema; let Postgres generate it.
        # Do not send token_urlsafe() text here.
    }
    if full_storage_path:
        scoped_key = f"{recording_date}:{athlete_key}" if athlete_key else None
        row.update({
            "full_storage_path": full_storage_path,
            "preview_duration_sec": preview_duration,
            "full_duration_sec": full_duration,
            "athlete_key": scoped_key,
            "athlete_id": _resolve_athlete(scoped_key, str(reel_meta.get("description", ""))),
        })
    _supabase().table("reels").insert(row).execute()

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
                 sport: str, athlete_desc: str, athlete_key: str | None = None) -> None:
    """Upsert the draft → raw-source mapping (drafts table). Enables operator
    reprocess requests to find which raw videos produced a given draft, and gives delivery the draft's sport,
    description and athlete key (delivery runs in another job)."""
    row = {
        "draft_name":   draft_name,
        "sources":      sources,
        "sport":        sport,
        "athlete_desc": athlete_desc,
    }
    if athlete_key:
        try:
            _supabase().table("drafts").upsert({**row, "athlete_key": athlete_key}).execute()
            return
        except Exception as exc:  # drafts.athlete_key not migrated yet: keep the reprocess mapping working
            logger.warning("Draft athlete key not recorded for %s: %s", draft_name, exc)
    _supabase().table("drafts").upsert(row).execute()


def lookup_draft_sources(draft_name: str) -> list[dict]:
    """Return [{"id": drive_file_id, "name": filename}] for a draft, or []."""
    res = (_supabase().table("drafts").select("sources")
           .eq("draft_name", draft_name).limit(1).execute())
    if res.data:
        return res.data[0].get("sources") or []
    return []


def upsert_draft_publishability(record: dict) -> None:
    """Persist the authoritative server-side approval contract for one REVIEW object.

    This write is product-critical. Callers must convert a failure into a blocked
    manifest outcome rather than allowing filename/client inference to approve it.
    """
    required = {"storage_object_id", "draft_name", "part_index", "manifest_revision"}
    missing = sorted(key for key in required if not str(record.get(key) or "").strip())
    if missing:
        raise ValueError(f"draft publishability record missing required fields: {missing}")
    payload = {
        **record,
        "technical_issues": [str(item) for item in record.get("technical_issues", []) or []],
        "approval_blocked_reasons": [
            str(item) for item in record.get("approval_blocked_reasons", []) or []
        ],
    }
    _supabase().table("draft_publishability").upsert(payload).execute()


def _qa_defects(qa_gate: dict) -> list[dict]:
    defects = qa_gate.get("defects") or []
    return [item for item in defects if isinstance(item, dict)]


def _reasons_from_defects(defects: list[dict]) -> list[str]:
    """Derive human-readable block reasons straight from defects.

    Some QA gates (e.g. pipeline/multi_person_clip_gate.py) attach `defects`
    to the qa_gate dict without also setting `approval_blocked_reasons` or
    `review_required_reasons`. Without this fallback those blocks persist
    with an empty approval_blocked_reasons, even though real blocking
    defects exist.
    """
    reasons: list[str] = []
    for defect in defects:
        dtype = str(defect.get("type") or "QA_REVIEW_REQUIRED")
        note = str(defect.get("note") or "").strip()
        reason = f"{dtype}: {note}" if note else dtype
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def _qa_reedit_notes(draft_name: str, qa_gate: dict) -> str:
    defects = _qa_defects(qa_gate)
    reasons = (
        qa_gate.get("approval_blocked_reasons")
        or qa_gate.get("review_required_reasons")
        or _reasons_from_defects(defects)
    )
    lines = [
        f"QA blocked draft: {draft_name}",
        "Regenerate this draft using the QA notes below and run QA again before approval.",
    ]
    if qa_gate.get("overall"):
        lines.append(f"Overall: {qa_gate.get('overall')}")
    for reason in reasons:
        text = str(reason).strip()
        if text:
            lines.append(f"- {text}")
    for defect in defects:
        dtype = str(defect.get("type") or "QA_REVIEW_REQUIRED")
        note = str(defect.get("note") or "").strip()
        at_seconds = defect.get("at_seconds")
        prefix = f"- {dtype}"
        if at_seconds is not None:
            prefix += f" at {at_seconds}s"
        lines.append(f"{prefix}: {note}" if note else prefix)
    return "\n".join(lines)[:2000]


def _active_reedit_task(draft_name: str) -> dict | None:
    for status in _ACTIVE_REEDIT_STATUSES:
        res = (_supabase().table("reprocess_requests")
               .select("id,status")
               .eq("draft_name", draft_name)
               .eq("status", status)
               .limit(1)
               .execute())
        if res.data:
            return res.data[0]
    return None


def upsert_qa_reedit_task(draft_name: str, qa_gate: dict, *, max_attempts: int = 3) -> None:
    """Create or refresh an operator-visible QA re-edit task for a blocked draft.

    The task starts as status='qa_blocked'. It is intentionally not consumed by
    the pipeline until the operator presses Send to re-edit in the app, which
    promotes it to status='pending' through the operator API.
    """
    if not draft_name or not qa_gate.get("qa_review_required"):
        return
    defects = _qa_defects(qa_gate)
    reasons = (
        qa_gate.get("approval_blocked_reasons")
        or qa_gate.get("review_required_reasons")
        or _reasons_from_defects(defects)
    )
    payload = {
        "draft_name": draft_name,
        "notes": _qa_reedit_notes(draft_name, qa_gate),
        "status": "qa_blocked",
        "origin": "qa_gate",
        "qa_defects": defects,
        "approval_blocked_reasons": [str(item) for item in reasons if str(item).strip()],
        "max_attempts": max_attempts,
    }
    existing = _active_reedit_task(draft_name)
    if existing:
        if existing.get("status") == "qa_blocked":
            _supabase().table("reprocess_requests").update(payload).eq("id", existing["id"]).execute()
        return
    _supabase().table("reprocess_requests").insert(payload).execute()


def fetch_recent_draft_feedback(limit: int = 500) -> list[dict]:
    """Structured operator feedback rows (draft_feedback table), most recent first.

    Consumed by pipeline/stages/feedback.py to fold negative labels (BORING,
    CUT_TOO_EARLY, WRONG_ATHLETE, etc.) into the existing prompt-injection
    learning loop, and by the missed-good-moment recall report.
    """
    res = (_supabase().table("draft_feedback").select("*")
           .order("created_at", desc=True).limit(limit).execute())
    return res.data or []


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


REPROCESS_DONE = "done"
REPROCESS_UNVERIFIED = "reprocessed_unverified"


def close_reprocess_requests(outcomes: dict[str, bool]) -> dict[str, str]:
    """Close exactly the reprocess requests this run consumed, each by its own result.

    `outcomes` maps a request id to whether the run produced a publishable draft from that request's sources.
    A request whose re-edit did not pass is `reprocessed_unverified`, never `done`. Nothing else is touched.

    Before this, every row with status 'queued' was set to 'done' whenever any run with a reprocess note
    finished: requests of other runs, and requests whose re-edit failed QA, were closed as repaired.
    """
    from datetime import datetime, timezone

    written: dict[str, str] = {}
    for req_id, verified in (outcomes or {}).items():
        if not req_id:
            continue
        status = REPROCESS_DONE if verified is True else REPROCESS_UNVERIFIED
        _supabase().table("reprocess_requests").update({
            "status":       status,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", req_id).eq("status", "queued").execute()
        written[req_id] = status
    return written


def close_queued_reprocess(request_ids: list[str] | None = None) -> None:
    """Kept for callers of the old name. Without ids it does nothing: a global close is never correct."""
    if not request_ids:
        logger.warning("close_queued_reprocess called without request ids: nothing closed")
        return
    close_reprocess_requests({req_id: False for req_id in request_ids})


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
