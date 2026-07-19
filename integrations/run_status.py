"""Helpers for durable pipeline run rows and terminal-state convergence."""

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


def _normalized_run_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(fields)
    if normalized.get("progress") is not None:
        normalized["progress"] = round(float(normalized["progress"]), 4)
    if normalized.get("status") in TERMINAL_RUN_STATUSES:
        normalized["finished_at"] = datetime.now(timezone.utc).isoformat()
    return normalized


def mark_run_strict(**fields: Any) -> None:
    """Write one run-scoped update and surface persistence failures."""
    run_id = get_run_id()
    if not run_id or not fields:
        return
    from integrations.supabase_uploader import _supabase

    response = (
        _supabase()
        .table("pipeline_runs")
        .update(_normalized_run_fields(fields))
        .eq("id", run_id)
        .execute()
    )
    if getattr(response, "data", None) == []:
        raise RuntimeError(f"pipeline_runs update matched no row for {run_id}")


def mark_run(**fields: Any) -> None:
    """Best-effort live progress update; terminal correction uses strict helpers."""
    try:
        mark_run_strict(**fields)
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


def _terminal_payload(
    *,
    status: str,
    stage: str,
    progress: float | None,
    error: str | None,
    meta: dict[str, Any],
) -> tuple[str, float, dict[str, Any], dict[str, Any]]:
    global_stage, global_progress = _global_terminal_signal(status, progress)
    global_meta: dict[str, Any] = {"terminal_status": status}
    run_id = get_run_id()
    if run_id:
        global_meta["pipeline_run_id"] = run_id
    if error:
        global_meta["error"] = error
    global_meta.update(meta)
    run_fields: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "meta": global_meta,
    }
    if progress is not None or status in {"succeeded", "no_input"}:
        run_fields["progress"] = global_progress
    if error:
        run_fields["error"] = error
    return global_stage, global_progress, global_meta, run_fields


def mark_terminal_run_strict(
    *,
    status: str,
    stage: str,
    progress: float | None = None,
    error: str | None = None,
    **meta: Any,
) -> None:
    """Persist both operator and run-scoped terminal state without swallowing errors."""
    from integrations.supabase_uploader import _supabase

    global_stage, global_progress, global_meta, run_fields = _terminal_payload(
        status=status,
        stage=stage,
        progress=progress,
        error=error,
        meta=meta,
    )
    _supabase().table("pipeline_status").upsert({
        "id": 1,
        "stage": global_stage,
        "progress": global_progress,
        "meta": global_meta,
    }).execute()
    mark_run_strict(**run_fields)


def mark_terminal_run(
    *,
    status: str,
    stage: str,
    progress: float | None = None,
    error: str | None = None,
    **meta: Any,
) -> None:
    """Best-effort live terminal update used during the running pipeline.

    The post-run business gate deliberately calls ``mark_terminal_run_strict``
    and verifies read-back. Keeping this path best-effort preserves progress
    reporting when observability is temporarily unavailable.
    """
    global_stage, global_progress, global_meta, run_fields = _terminal_payload(
        status=status,
        stage=stage,
        progress=progress,
        error=error,
        meta=meta,
    )
    try:
        from integrations.supabase_uploader import write_pipeline_status

        write_pipeline_status(global_stage, global_progress, **global_meta)
    except Exception:
        logger.warning("pipeline_status terminal update skipped", exc_info=True)
    mark_run(**run_fields)


def read_terminal_state() -> dict[str, Any]:
    """Read back run-scoped and operator terminal state for convergence checks."""
    from integrations.supabase_uploader import _supabase

    client = _supabase()
    run_row: dict[str, Any] | None = None
    run_id = get_run_id()
    if run_id:
        response = (
            client.table("pipeline_runs")
            .select("id,status,stage,progress,error,meta,finished_at")
            .eq("id", run_id)
            .limit(1)
            .execute()
        )
        if getattr(response, "data", None):
            run_row = response.data[0]
    global_response = (
        client.table("pipeline_status")
        .select("id,stage,progress,meta,updated_at")
        .eq("id", 1)
        .limit(1)
        .execute()
    )
    global_row = global_response.data[0] if getattr(global_response, "data", None) else None
    return {"run": run_row, "global": global_row}
