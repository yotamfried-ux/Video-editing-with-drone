#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _critical_defects(qa_gate: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for defect in qa_gate.get("defects", []) or []:
        if not isinstance(defect, dict):
            continue
        if defect.get("blocking") is True or str(defect.get("severity", "")).lower() == "critical":
            out.append(defect)
    return out


def append_summary(report_path: Path, trace_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    drafts = [draft for draft in trace.get("drafts", []) if isinstance(draft, dict)]
    review_required = [draft for draft in drafts if draft.get("qa_status") == "review_required"]
    qa_blocked = []
    for draft in review_required:
        qa_gate = draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else {}
        if qa_gate.get("qa_review_required") or _critical_defects(qa_gate):
            qa_blocked.append(draft)

    metrics = report.setdefault("metrics", {})
    metrics["qa_review_required_draft_count"] = len(review_required)
    metrics["qa_blocked_draft_count"] = len(qa_blocked)

    qa_summary = report.setdefault("qa_gate_summary", {})
    still_failing = int(qa_summary.get("qa_still_failing_count") or 0)
    policy_explicit = len(qa_blocked) > 0 and len(qa_blocked) >= still_failing
    qa_summary["qa_policy_explicit"] = policy_explicit
    qa_summary["qa_review_required_draft_count"] = len(review_required)
    qa_summary["qa_blocked_draft_count"] = len(qa_blocked)

    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["qa_gate_policy_explicit"] = policy_explicit
        gaps["qa_trace_policy_summary_ready"] = True

    if policy_explicit:
        metrics["qa_gate_bypass_rate"] = 0.0
        qa_summary["qa_gate_bypass_rate"] = 0.0
        report["bug_classifications"] = [
            item for item in report.get("bug_classifications", [])
            if not (isinstance(item, dict) and item.get("code") == "BUG_QA_GATE_BYPASSED")
        ]
        report["alerts"] = [
            item for item in report.get("alerts", [])
            if not (isinstance(item, dict) and item.get("metric") == "qa_gate_bypass_rate")
        ]
    _write_json(report_path, report)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_qa_policy_trace_summary_to_report.py RUN_QUALITY_REPORT_JSON DRAFT_DECISION_TRACE_JSON", file=sys.stderr)
        return 2
    report = append_summary(Path(sys.argv[1]), Path(sys.argv[2]))
    metrics = report.get("metrics", {})
    print(
        "qa policy trace summary "
        f"review_required={metrics.get('qa_review_required_draft_count', 0)} "
        f"blocked={metrics.get('qa_blocked_draft_count', 0)} "
        f"bypass_rate={metrics.get('qa_gate_bypass_rate', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
