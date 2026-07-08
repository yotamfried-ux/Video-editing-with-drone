#!/usr/bin/env python3
"""Fail-fast Supabase schema preflight for the QA re-edit loop."""
from __future__ import annotations

import os
import sys
from textwrap import dedent

from supabase import create_client

REQUIRED_COLUMNS = (
    "origin",
    "qa_defects",
    "approval_blocked_reasons",
    "attempt_count",
    "max_attempts",
    "last_pipeline_run_id",
)

SELECT_COLUMNS = ",".join((
    "id",
    "draft_name",
    "notes",
    "status",
    *REQUIRED_COLUMNS,
))

MIGRATION_PATH = "supabase/migrations/20260708_qa_reedit_tasks.sql"


def _error(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)


def _schema_failure_message(original_error: str) -> str:
    columns = ", ".join(REQUIRED_COLUMNS)
    return dedent(
        f"""
        QA re-edit Supabase schema preflight failed.

        The real Supabase project does not expose the columns required for the
        persistent QA-blocked draft repair loop: {columns}.

        Apply {MIGRATION_PATH} in the real Supabase project before running the
        pipeline again. If the migration was already applied but Supabase REST
        still returns PGRST204, reload/restart the Supabase API schema cache and
        run this preflight again.

        Original Supabase/PostgREST error:
        {original_error}
        """
    ).strip()


def main() -> int:
    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not service_key:
        _error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required for QA re-edit schema preflight")
        print(
            f"Set both secrets before running the production pipeline. Required migration: {MIGRATION_PATH}",
            file=sys.stderr,
        )
        return 2

    try:
        create_client(url, service_key).table("reprocess_requests").select(SELECT_COLUMNS).limit(1).execute()
    except Exception as exc:  # noqa: BLE001 - Supabase client raises API-specific runtime errors.
        message = str(exc)
        if "PGRST204" in message or "Could not find" in message or "schema cache" in message:
            _error("QA re-edit Supabase migration is missing or the schema cache is stale")
            print(_schema_failure_message(message), file=sys.stderr)
            return 2
        _error("Could not validate QA re-edit Supabase schema")
        print(message, file=sys.stderr)
        return 2

    print("QA re-edit Supabase schema preflight ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
