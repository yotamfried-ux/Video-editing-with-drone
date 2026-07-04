"""Best-effort helpers for durable pipeline run rows."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

TERMINAL_RUN_STATUSES = {"succeeded", "failed", "no_input", "dispatch_failed"}


def get_run_id() -> str | None:
    value = os.getenv("PIPELINE_RUN_ID", "").strip()
    return value or None


def mark_run(**fields) -> None:
    run_id = get_run_id()
    if not run_id or not fields:
        return
    if fields.get("progress") is not None:
        fields["progress"] = round(float(fields["progress"]), 4)
    if fields.get("status") in TERMINAL_RUN_STATUSES:
        fields["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from integrations.supabase_uploader import _supabase
        _supabase().table("pipeline_runs").update(fields).eq("id", run_id).execute()
    except Exception:
        logger.warning("pipeline_runs update skipped", exc_info=True)


def _global_terminal_signal(status: str, progress: float | None = None) -> tuple[str, float]:
    if status == "succeeded":
        return "done", 1.0
    if status == "no_input":
        return "no_input", 1.0
    if status in {"failed", "dispatch_failed"}:
        return "failed", round(float(progress), 4) if progress is not None else 1.0
    return status, round(float(progress), 4) if progress is not None else 0.0


def mark_terminal_run(
    *,
    status: str,
    stage: str,
    progress: float | None = None,
    error: str | None = None,
    **meta: Any,
) -> None:
    """Finalize both the durable run row and the singleton global live signal.

    `pipeline_runs` remains the source of truth for the specific app-triggered
    run, while `pipeline_status` is only the global live signal displayed in the
    operator UI. The terminal write prevents a completed tracked run from leaving
    a stale intermediate global stage such as `qa` at 46%.
    """
    global_stage, global_progress = _global_terminal_signal(status, progress)
    global_meta: dict[str, Any] = {"terminal_status": status}
    run_id = get_run_id()
    if run_id:
        global_meta["pipeline_run_id"] = run_id
    if error:
        global_meta["error"] = error
    global_meta.update(meta)

    # Write the global singleton first. In run_tracked.py this writer is patched
    # to mirror stage/progress into pipeline_runs, so the final mark_run below
    # intentionally wins and preserves run-scoped stage values like "finished".
    try:
        from integrations.supabase_uploader import write_pipeline_status
        write_pipeline_status(global_stage, global_progress, **global_meta)
    except Exception:
        logger.warning("pipeline_status terminal update skipped", exc_info=True)

    run_fields: dict[str, Any] = {"status": status, "stage": stage, "meta": global_meta}
    if progress is not None or status in {"succeeded", "no_input"}:
        run_fields["progress"] = global_progress
    if error:
        run_fields["error"] = error
    mark_run(**run_fields)
