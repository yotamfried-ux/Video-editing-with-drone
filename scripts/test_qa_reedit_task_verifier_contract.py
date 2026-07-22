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
    verifier = read("scripts/verify_qa_reedit_tasks.py")
    pipeline_workflow = read(".github/workflows/pipeline-run.yml")
    smoke_workflow = read(".github/workflows/operator-smoke-check.yml")
    smoke_docs = read("docs/qa-reedit-migration-smoke.md")
    audit = read("docs/app-pipeline-audit.md")

    for token in [
        "draft_decision_trace.json",
        "qa_reedit_task_verification.json",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "reprocess_requests",
        "qa_blocked",
        "pending",
        "queued",
        "origin",
        "qa_gate",
        "qa_defects",
        "approval_blocked_reasons",
        "attempt_count",
        "max_attempts",
        "missing active reprocess_requests task",
    ]:
        require(token, verifier, "QA re-edit task verifier")

    for token in [
        "Verify QA re-edit task persistence",
        "python scripts/verify_qa_reedit_tasks.py",
        "SUPABASE_URL: ${{ secrets.SUPABASE_URL }}",
        "SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}",
        "Upload pipeline diagnostics",
    ]:
        require(token, pipeline_workflow, "pipeline workflow")

    run_idx = pipeline_workflow.index("Run pipeline")
    verify_idx = pipeline_workflow.index("Verify QA re-edit task persistence")
    upload_idx = pipeline_workflow.index("Upload pipeline diagnostics")
    if not (run_idx < verify_idx < upload_idx):
        raise SystemExit("QA re-edit task verifier must run after pipeline and before diagnostics upload")

    for token in [
        "scripts/verify_qa_reedit_tasks.py",
        "scripts/test_qa_reedit_task_verifier_contract.py",
        "Validate QA re-edit task verifier contract",
    ]:
        require(token, smoke_workflow, "operator smoke check")

    for token in [
        "qa_reedit_task_verification.json",
        "scripts/verify_qa_reedit_tasks.py",
        "status='qa_blocked'",
        "origin='qa_gate'",
    ]:
        require(token, smoke_docs, "QA re-edit migration smoke docs")

    for token in [
        "GAP-021",
        "QA-blocked re-edit reaches a terminal verdict",
        "qa_blocked",
        "approval_blocked_reasons",
        "attempt_count",
        "max attempts",
    ]:
        require(token, audit, "app pipeline audit")

    print("QA re-edit task verifier contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
