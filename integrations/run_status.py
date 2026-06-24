"""Best-effort helpers for durable pipeline run rows."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os

logger = logging.getLogger(__name__)


def get_run_id() -> str | None:
    value = os.getenv("PIPELINE_RUN_ID", "").strip()
    return value or None


def mark_run(**fields) -> None:
    run_id = get_run_id()
    if not run_id or not fields:
        return
    if fields.get("progress") is not None:
        fields["progress"] = round(float(fields["progress"]), 4)
    if fields.get("status") in {"succeeded", "failed", "no_input"}:
        fields["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from integrations.supabase_uploader import _supabase
        _supabase().table("pipeline_runs").update(fields).eq("id", run_id).execute()
    except Exception:
        logger.warning("pipeline_runs update skipped", exc_info=True)
