#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations import run_status  # noqa: E402


class FakeQuery:
    def __init__(self, updates: list[dict[str, Any]], table_name: str):
        self.updates = updates
        self.table_name = table_name
        self.fields: dict[str, Any] | None = None
        self.filters: list[tuple[str, Any]] = []

    def update(self, fields: dict[str, Any]) -> "FakeQuery":
        self.fields = dict(fields)
        return self

    def eq(self, key: str, value: Any) -> "FakeQuery":
        self.filters.append((key, value))
        return self

    def execute(self) -> None:
        self.updates.append(
            {
                "table": self.table_name,
                "fields": self.fields,
                "filters": self.filters,
            }
        )


class FakeSupabase:
    def __init__(self, updates: list[dict[str, Any]]):
        self.updates = updates

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self.updates, name)


def validate_terminal_run_mirrors_global_status() -> None:
    updates: list[dict[str, Any]] = []
    global_writes: list[dict[str, Any]] = []

    def fake_supabase() -> FakeSupabase:
        return FakeSupabase(updates)

    def fake_write_pipeline_status(stage: str, progress: float, **meta: Any) -> None:
        global_writes.append({"stage": stage, "progress": progress, "meta": meta})

    fake_module = types.SimpleNamespace(
        _supabase=fake_supabase,
        write_pipeline_status=fake_write_pipeline_status,
    )

    previous_env = os.environ.get("PIPELINE_RUN_ID")
    previous_module = sys.modules.get("integrations.supabase_uploader")
    os.environ["PIPELINE_RUN_ID"] = "run_abc123"
    sys.modules["integrations.supabase_uploader"] = fake_module

    try:
        run_status.mark_terminal_run(status="succeeded", stage="finished", progress=1.0)
        run_status.mark_terminal_run(status="no_input", stage="no_input", progress=1.0)
        run_status.mark_terminal_run(
            status="failed",
            stage="all_draft_uploads_failed",
            error="All draft uploads failed after QA.",
            error_code="all_draft_uploads_failed",
            no_drafts_reason="all_draft_uploads_failed",
        )
    finally:
        if previous_env is None:
            os.environ.pop("PIPELINE_RUN_ID", None)
        else:
            os.environ["PIPELINE_RUN_ID"] = previous_env
        if previous_module is None:
            sys.modules.pop("integrations.supabase_uploader", None)
        else:
            sys.modules["integrations.supabase_uploader"] = previous_module

    if global_writes[0]["stage"] != "done" or global_writes[0]["progress"] != 1.0:
        raise SystemExit("succeeded terminal run did not write done/100 to pipeline_status")
    if global_writes[0]["meta"].get("pipeline_run_id") != "run_abc123":
        raise SystemExit("pipeline_status terminal metadata is missing pipeline_run_id")
    if global_writes[0]["meta"].get("terminal_status") != "succeeded":
        raise SystemExit("pipeline_status terminal metadata is missing terminal_status")

    first_run_update = updates[0]["fields"]
    if first_run_update.get("status") != "succeeded":
        raise SystemExit("pipeline_runs was not marked succeeded")
    if first_run_update.get("stage") != "finished":
        raise SystemExit("pipeline_runs did not preserve the run-scoped finished stage")
    if first_run_update.get("progress") != 1.0:
        raise SystemExit("pipeline_runs terminal progress was not 100%")
    if not first_run_update.get("finished_at"):
        raise SystemExit("pipeline_runs terminal update did not set finished_at")

    if global_writes[1]["stage"] != "no_input" or global_writes[1]["progress"] != 1.0:
        raise SystemExit("no_input terminal run did not write no_input/100 to pipeline_status")

    no_output_update = updates[2]["fields"]
    if no_output_update.get("status") != "failed":
        raise SystemExit("no-output terminal run was not marked failed")
    if no_output_update.get("stage") != "all_draft_uploads_failed":
        raise SystemExit("post-QA no-output run did not preserve the upload failure stage")
    if not no_output_update.get("error"):
        raise SystemExit("no-output terminal run did not persist a visible error")
    if no_output_update.get("meta", {}).get("error_code") != "all_draft_uploads_failed":
        raise SystemExit("post-QA no-output run did not persist the upload failure error code")
    if no_output_update.get("meta", {}).get("no_drafts_reason") != "all_draft_uploads_failed":
        raise SystemExit("post-QA no-output run did not persist the upload failure reason")


def validate_run_tracked_no_output_contract() -> None:
    script = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    required = [
        "_produced_review_drafts",
        "drafts_created",
        "_last_observed_stage",
        "_last_observed_progress",
        "_last_observed_meta",
        "_no_drafts_failure",
        "all_draft_uploads_failed",
        "last_observed_stage",
        "last_observed_meta",
        "sys.exit(1)",
        "mark_terminal_run(status=\"failed\", stage=stage",
    ]
    missing = [token for token in required if token not in script]
    if missing:
        raise SystemExit(f"run_tracked is missing no-output diagnostic contract tokens: {missing}")


def validate_status_endpoint_contract() -> None:
    route = (ROOT / "web-api/src/app/api/operator/pipeline/status/route.ts").read_text(encoding="utf-8")
    required = [
        "pipeline_runs",
        "global_live_stale",
        "global_live_stale_reason",
        "latest_run",
        "STALE_GLOBAL_AFTER_MS",
        "TERMINAL_RUN_STATUSES",
    ]
    missing = [token for token in required if token not in route]
    if missing:
        raise SystemExit(f"operator pipeline status route is missing stale contract tokens: {missing}")


def validate_mobile_stale_ui_contract() -> None:
    screen = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text(encoding="utf-8")
    hook = (ROOT / "mobile/src/features/operator/hooks/usePipelineStatus.ts").read_text(encoding="utf-8")
    types = (ROOT / "mobile/src/features/operator/types/contracts.ts").read_text(encoding="utf-8")

    required_screen = [
        "globalLiveStale",
        "Global live signal is stale",
        "displayStage",
        "displayProgress",
        "latest run",
    ]
    required_hook = ["latestRun", "globalLiveStale", "globalLiveStaleReason"]
    required_types = ["latest_run?: PipelineRun | null", "global_live_stale?: boolean"]

    for label, text, required in [
        ("pipeline screen", screen, required_screen),
        ("pipeline status hook", hook, required_hook),
        ("operator contracts", types, required_types),
    ]:
        missing = [token for token in required if token not in text]
        if missing:
            raise SystemExit(f"{label} is missing stale UI contract tokens: {missing}")


def main() -> int:
    validate_terminal_run_mirrors_global_status()
    validate_run_tracked_no_output_contract()
    validate_status_endpoint_contract()
    validate_mobile_stale_ui_contract()
    print("Pipeline status stale contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
