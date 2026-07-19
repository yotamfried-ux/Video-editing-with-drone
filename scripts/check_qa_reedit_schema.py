#!/usr/bin/env python3
"""Fail-fast Supabase schema preflight for QA repair and draft publishability."""
from __future__ import annotations

import os
import sys
from textwrap import dedent

from supabase import create_client

REEDIT_REQUIRED_COLUMNS = (
    "origin",
    "qa_defects",
    "approval_blocked_reasons",
    "attempt_count",
    "max_attempts",
    "last_pipeline_run_id",
)
REEDIT_SELECT_COLUMNS = ",".join((
    "id",
    "draft_name",
    "notes",
    "status",
    *REEDIT_REQUIRED_COLUMNS,
))
PUBLISHABILITY_SELECT_COLUMNS = ",".join((
    "storage_object_id",
    "draft_name",
    "pipeline_run_id",
    "athlete_key",
    "part_index",
    "publishable",
    "qa_evidence_recorded",
    "qa_verdict",
    "qa_passed",
    "technical_issues",
    "approval_blocked_reasons",
    "media_specs_revision",
    "manifest_revision",
))
REEDIT_MIGRATION_PATH = "supabase/migrations/20260708_qa_reedit_tasks.sql"
PUBLISHABILITY_MIGRATION_PATH = "supabase/migrations/20260717_draft_publishability_authority.sql"


def _error(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)


def _schema_failure_message(original_error: str) -> str:
    columns = ", ".join(REEDIT_REQUIRED_COLUMNS)
    return dedent(
        f"""
        SportReel Supabase schema preflight failed.

        The real Supabase project must expose both:
        - reprocess_requests columns required for QA repair: {columns};
        - draft_publishability, the authoritative server-side approval contract.

        Apply {REEDIT_MIGRATION_PATH} and {PUBLISHABILITY_MIGRATION_PATH} in the
        real Supabase project before running the pipeline or deploying the operator
        approval API. If migrations were applied but PostgREST still returns
        PGRST204/PGRST205, reload the Supabase API schema cache and retry.

        Original Supabase/PostgREST error:
        {original_error}
        """
    ).strip()


def main() -> int:
    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not service_key:
        _error("SUPABASE_URL and SUPABASE_SERVICE_KEY are required for schema preflight")
        print(
            f"Required migrations: {REEDIT_MIGRATION_PATH}, {PUBLISHABILITY_MIGRATION_PATH}",
            file=sys.stderr,
        )
        return 2

    try:
        client = create_client(url, service_key)
        client.table("reprocess_requests").select(REEDIT_SELECT_COLUMNS).limit(1).execute()
        client.table("draft_publishability").select(PUBLISHABILITY_SELECT_COLUMNS).limit(1).execute()
    except Exception as exc:  # noqa: BLE001 - Supabase client raises API-specific runtime errors.
        message = str(exc)
        if any(token in message for token in ("PGRST204", "PGRST205", "Could not find", "schema cache")):
            _error("Required Supabase migration is missing or the schema cache is stale")
            print(_schema_failure_message(message), file=sys.stderr)
            return 2
        _error("Could not validate SportReel Supabase schema")
        print(message, file=sys.stderr)
        return 2

    print("QA re-edit and draft publishability Supabase schema preflight ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
