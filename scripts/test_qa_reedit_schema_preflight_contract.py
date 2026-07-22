#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(token: str, text: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"{label} missing {token}")


def main() -> int:
    script = read("scripts/check_qa_reedit_schema.py")
    pipeline_workflow = read(".github/workflows/pipeline-run.yml")
    smoke_workflow = read(".github/workflows/operator-smoke-check.yml")
    docs = read("docs/qa-reedit-migration-smoke.md")
    audit = read("docs/app-pipeline-audit.md")
    pipeline_contract = read("docs/operator-pipeline-contract.md")

    for token in [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "reprocess_requests",
        "approval_blocked_reasons",
        "qa_defects",
        "attempt_count",
        "max_attempts",
        "last_pipeline_run_id",
        "PGRST204",
        "20260708_qa_reedit_tasks.sql",
        "draft_publishability",
        "storage_object_id",
        "qa_evidence_recorded",
        "manifest_revision",
        "20260717_draft_publishability_authority.sql",
    ]:
        require(token, script, "schema preflight script")

    for token in [
        "Preflight QA re-edit Supabase schema",
        "python scripts/check_qa_reedit_schema.py",
        "SUPABASE_URL: ${{ secrets.SUPABASE_URL }}",
        "SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}",
    ]:
        require(token, pipeline_workflow, "pipeline workflow")

    storage_idx = pipeline_workflow.index("Preflight storage access")
    schema_idx = pipeline_workflow.index("Preflight QA re-edit Supabase schema")
    run_idx = pipeline_workflow.index("Run pipeline")
    if not (storage_idx < schema_idx < run_idx):
        raise SystemExit("schema preflight must run after storage preflight and before pipeline execution")

    for token in [
        "scripts/check_qa_reedit_schema.py",
        "scripts/test_qa_reedit_schema_preflight_contract.py",
        "Validate QA re-edit schema preflight contract",
    ]:
        require(token, smoke_workflow, "operator smoke check")

    for token in [
        "28915165774",
        "PGRST204",
        "approval_blocked_reasons",
        "status='qa_blocked'",
        "schema cache",
    ]:
        require(token, docs, "migration smoke docs")

    for token in [
        "GAP-021",
        "QA-blocked re-edit reaches a terminal verdict",
        "qa_blocked",
        "approval_blocked_reasons",
        "Supabase migrations",
    ]:
        require(token, audit, "app pipeline audit")

    for token in [
        "check_qa_reedit_schema.py",
        "20260708_qa_reedit_tasks.sql",
        "QA-blocked draft re-edit loop preflight",
    ]:
        require(token, pipeline_contract, "operator pipeline contract")

    print("QA re-edit schema preflight contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
