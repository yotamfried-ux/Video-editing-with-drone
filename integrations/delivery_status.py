"""Best-effort delivery run status updates for Deliver Preview workflow."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {"succeeded", "failed", "dispatch_failed"}


def _delivery_run_id() -> str:
    return os.getenv("DELIVERY_RUN_ID", "").strip()


def mark_delivery_run(**fields) -> None:
    """Update the current delivery_runs row if DELIVERY_RUN_ID is configured.

    This helper is intentionally best-effort: delivery should not fail only because
    status telemetry could not be written.
    """
    run_id = _delivery_run_id()
    if not run_id or not fields:
      return

    try:
        from integrations.supabase_uploader import _supabase

        now = datetime.now(timezone.utc).isoformat()
        if fields.get("status") == "running":
            fields.setdefault("started_at", now)
        if fields.get("status") in _TERMINAL_STATUSES:
            fields.setdefault("finished_at", now)

        _supabase().table("delivery_runs").update(fields).eq("id", run_id).execute()
    except Exception as exc:  # pragma: no cover - telemetry must not break delivery
        logger.warning("Failed to update delivery run %s: %s", run_id, exc)
