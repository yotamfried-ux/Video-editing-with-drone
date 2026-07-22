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
    migration = read("supabase/migrations/20260708_qa_reedit_tasks.sql")
    uploader = read("integrations/supabase_uploader.py")
    qa_policy = read("pipeline/qa_gate_policy.py")
    performance_policy = read("pipeline/performance_reel_policy.py")
    reprocess_route = read("web-api/src/app/api/operator/reprocess/route.ts")
    drafts_route = read("web-api/src/app/api/operator/drafts/route.ts")
    approve_handler = read("web-api/src/lib/operator-draft-approve.ts")
    review_screen = read("mobile/src/app/(operator)/review.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")
    api_docs = read("docs/operator-api-contracts.md")
    pipeline_docs = read("docs/operator-pipeline-contract.md")
    audit = read("docs/app-pipeline-audit.md")

    for token in [
        "status='qa_blocked'",
        "origin text not null default 'operator'",
        "qa_defects jsonb",
        "approval_blocked_reasons jsonb",
        "attempt_count integer",
        "reprocess_requests_active_qa_block_idx",
    ]:
        require(token, migration, "qa re-edit migration")

    for token in [
        "upsert_qa_reedit_task",
        '"status": "qa_blocked"',
        '"origin": "qa_gate"',
        "qa_defects",
        "approval_blocked_reasons",
        "Regenerate this draft using the QA notes below",
        "_active_reedit_task",
    ]:
        require(token, uploader, "qa re-edit persistence")

    for token in [
        "_persist_qa_reedit_task",
        "upsert_qa_reedit_task",
        "qa_reedit_status",
        "task_created",
    ]:
        require(token, qa_policy, "qa policy task creation")

    for token in [
        "QA_FAIL: Reel did not pass final quality review.",
        '"qa_review_required": True',
        '"decision": "blocked_review_required"',
    ]:
        require(token, performance_policy, "all final QA failures block approval")

    for token in [
        "reprocess_request_id",
        "findActiveQaTask",
        "IN_FLIGHT_QA_STATUSES",
        "inFlightResponse",
        "status: 'pending'",
        "attempt_count: currentAttempts + 1",
        "failed_max_attempts",
        "qa_reedit_task: Boolean(existingTask)",
    ]:
        require(token, reprocess_route, "reprocess route")

    for token in [
        "ACTIVE_REEDIT_STATUSES",
        "reedit_task",
        "activeReeditTasks",
        "review_required: Boolean(task)",
    ]:
        require(token, drafts_route, "drafts route")

    for token in [
        "activeReeditTask",
        "ACTIVE_REEDIT_STATUSES",
        "Boolean(reeditTask)",
        "Could not verify QA re-edit status",
    ]:
        require(token, approve_handler, "approval route")

    for token in [
        "did not pass final QA",
        "QA failed · re-edit required",
        "Send QA notes to re-edit",
        "reprocess_request_id: reeditTarget.reedit_task?.id",
        "reeditNotesForDraft",
    ]:
        require(token, review_screen, "operator review UI")

    for token in [
        "reedit_task?: ReprocessRow | null",
        "qa_defects?: unknown",
        "attempt_count?: number | null",
        "max_attempts?: number | null",
    ]:
        require(token, contracts, "mobile contracts")

    for token in [
        "QA-blocked drafts are persisted",
        "reprocess_request_id?: string",
        "reedit_task?: ReprocessRow | null",
    ]:
        require(token, api_docs, "operator api docs")

    for token in [
        "QA-blocked draft re-edit loop",
        "status='qa_blocked'",
        "Send QA notes to re-edit",
        "max_attempts",
    ]:
        require(token, pipeline_docs, "operator pipeline docs")

    for token in [
        "GAP-021",
        "QA-blocked re-edit reaches a terminal verdict",
        "qa_blocked",
        "Send QA notes to re-edit",
    ]:
        require(token, audit, "app pipeline audit")

    print("QA re-edit loop contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
