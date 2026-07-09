#!/usr/bin/env python3
"""Verify QA-blocked drafts created durable Supabase re-edit tasks.

This runs after the pipeline and before diagnostics are uploaded. It turns the
GAP-012 persistence invariant into an artifact-backed check: when the draft
trace contains QA-blocked drafts, each draft must have an active
`reprocess_requests` row created by the QA gate.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from supabase import create_client

ACTIVE_REEDIT_STATUSES = ("qa_blocked", "pending", "queued")
SELECT_COLUMNS = ",".join(
    (
        "id",
        "draft_name",
        "status",
        "origin",
        "notes",
        "qa_defects",
        "approval_blocked_reasons",
        "attempt_count",
        "max_attempts",
        "last_pipeline_run_id",
        "created_at",
        "processed_at",
    )
)
DEFAULT_DEBUG_DIR = "/tmp/dtor/pipeline-debug"
REPORT_NAME = "qa_reedit_task_verification.json"


def _debug_dir() -> Path:
    return Path(os.getenv("PIPELINE_DEBUG_DIR") or os.getenv("TMP_DIR", "/tmp/dtor")) / (
        "pipeline-debug" if os.getenv("PIPELINE_DEBUG_DIR") is None else ""
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def _is_blocking_defect(defect: Any) -> bool:
    return isinstance(defect, dict) and bool(defect.get("blocking"))


def _qa_blocked_drafts(trace: dict[str, Any]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    drafts = trace.get("drafts") or []
    if not isinstance(drafts, list):
        return blocked

    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        qa_gate = draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else {}
        defects = qa_gate.get("defects") or []
        blocking_defects = [item for item in defects if _is_blocking_defect(item)] if isinstance(defects, list) else []
        qa_status = str(draft.get("qa_status") or "").lower()
        final_verdict = str(qa_gate.get("final_verdict") or "").upper()
        decision = str(qa_gate.get("decision") or "").lower()
        review_required_reasons = draft.get("review_required_reasons") or []

        blocked_by_qa = any(
            (
                qa_gate.get("qa_review_required") is True,
                final_verdict == "FAIL" and bool(blocking_defects),
                qa_status in {"review_required", "qa_blocked", "blocked"},
                "review_required" in decision,
                bool(review_required_reasons),
            )
        )
        if blocked_by_qa:
            name = draft.get("draft_name") or draft.get("draft_id") or draft.get("title")
            if name:
                blocked.append(
                    {
                        "draft_name": str(name),
                        "qa_status": qa_status or None,
                        "final_verdict": final_verdict or None,
                        "decision": decision or None,
                        "blocking_defect_count": len(blocking_defects),
                    }
                )
    return blocked


def _supabase_client():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(url, key)


def _latest_active_task(client: Any, draft_name: str) -> dict[str, Any] | None:
    # Keep the query compatible with the supabase-py version used by the repo by
    # avoiding `.in_()`, which has changed names across releases.
    rows: list[dict[str, Any]] = []
    for status in ACTIVE_REEDIT_STATUSES:
        response = (
            client.table("reprocess_requests")
            .select(SELECT_COLUMNS)
            .eq("draft_name", draft_name)
            .eq("status", status)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            rows.extend(response.data)
    if not rows:
        return None
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]


def _validate_task(blocked_draft: dict[str, Any], task: dict[str, Any] | None) -> list[str]:
    draft_name = blocked_draft["draft_name"]
    failures: list[str] = []
    if not task:
        return [f"missing active reprocess_requests task for QA-blocked draft {draft_name!r}"]

    status = task.get("status")
    if status not in ACTIVE_REEDIT_STATUSES:
        failures.append(f"task for {draft_name!r} has non-active status {status!r}")
    if task.get("origin") != "qa_gate":
        failures.append(f"task for {draft_name!r} has origin {task.get('origin')!r}, expected 'qa_gate'")
    if not str(task.get("notes") or "").strip():
        failures.append(f"task for {draft_name!r} has empty notes")
    defects = task.get("qa_defects")
    if blocked_draft.get("blocking_defect_count", 0) > 0 and not defects:
        failures.append(f"task for {draft_name!r} has no qa_defects despite blocking QA defects")
    reasons = task.get("approval_blocked_reasons")
    if blocked_draft.get("blocking_defect_count", 0) > 0 and not reasons:
        failures.append(f"task for {draft_name!r} has empty approval_blocked_reasons despite blocking QA defects")
    if task.get("attempt_count") is None:
        failures.append(f"task for {draft_name!r} has null attempt_count")
    if task.get("max_attempts") is None:
        failures.append(f"task for {draft_name!r} has null max_attempts")
    return failures


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    debug_dir = _debug_dir()
    if str(debug_dir).endswith("/"):
        debug_dir = Path(str(debug_dir).rstrip("/"))
    trace_path = debug_dir / "draft_decision_trace.json"
    report_path = debug_dir / REPORT_NAME

    report: dict[str, Any] = {
        "schema_version": "sportreel.qa_reedit_task_verification.v1",
        "status": "pending",
        "debug_dir": str(debug_dir),
        "draft_trace_path": str(trace_path),
        "blocked_draft_count": 0,
        "verified_task_count": 0,
        "blocked_drafts": [],
        "tasks": [],
        "failures": [],
    }

    try:
        if not trace_path.exists():
            report["status"] = "skipped_no_draft_trace"
            _write_report(report_path, report)
            print(f"QA re-edit task verification skipped: missing {trace_path}")
            return 0

        trace = _load_json(trace_path)
        blocked_drafts = _qa_blocked_drafts(trace)
        report["blocked_draft_count"] = len(blocked_drafts)
        report["blocked_drafts"] = blocked_drafts

        if not blocked_drafts:
            report["status"] = "pass_no_qa_blocked_drafts"
            _write_report(report_path, report)
            print("QA re-edit task verification ok: no QA-blocked drafts in this run")
            return 0

        client = _supabase_client()
        failures: list[str] = []
        tasks: list[dict[str, Any]] = []
        for blocked_draft in blocked_drafts:
            task = _latest_active_task(client, blocked_draft["draft_name"])
            task_failures = _validate_task(blocked_draft, task)
            failures.extend(task_failures)
            if task:
                tasks.append(task)

        report["tasks"] = tasks
        report["verified_task_count"] = len(tasks)
        report["failures"] = failures
        report["status"] = "fail" if failures else "pass"
        _write_report(report_path, report)

        if failures:
            for failure in failures:
                print(f"::error::{failure}", file=sys.stderr)
            print(f"QA re-edit task verification failed; see {report_path}", file=sys.stderr)
            return 2

        print(
            "QA re-edit task verification ok: "
            f"{len(tasks)} active qa_gate task(s) verified for {len(blocked_drafts)} QA-blocked draft(s)"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - this is a CI diagnostic boundary.
        report["status"] = "error"
        report["failures"] = [str(exc)]
        _write_report(report_path, report)
        print(f"::error::QA re-edit task verification errored: {exc}", file=sys.stderr)
        print(f"See {report_path}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
