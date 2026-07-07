#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".mixed.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _drafts_by_name(trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    drafts: dict[str, dict[str, Any]] = {}
    for draft in trace.get("drafts", []) or []:
        if not isinstance(draft, dict):
            continue
        for key in ("draft_name", "draft_id", "title"):
            value = str(draft.get(key) or "").strip()
            if value:
                drafts[value] = draft
    return drafts


def _qa_gate(draft: dict[str, Any]) -> dict[str, Any]:
    value = draft.get("qa_gate")
    return value if isinstance(value, dict) else {}


def _is_review_blocked(draft: dict[str, Any] | None) -> bool:
    if not draft:
        return False
    if str(draft.get("qa_status") or "").lower() == "review_required":
        return True
    if draft.get("review_required") is True or draft.get("qa_review_required") is True:
        return True
    if draft.get("review_required_reasons") or draft.get("approval_blocked_reasons"):
        return True
    qa_gate = _qa_gate(draft)
    if qa_gate.get("qa_review_required") is True:
        return True
    if str(qa_gate.get("final_verdict") or "").upper() == "FAIL":
        return True
    for defect in qa_gate.get("defects", []) or []:
        if not isinstance(defect, dict):
            continue
        if defect.get("blocking") is True or str(defect.get("severity") or "").lower() == "critical":
            return True
    return False


def _recompute_status(report: dict[str, Any]) -> None:
    alerts = report.get("alerts", []) if isinstance(report.get("alerts"), list) else []
    if any(alert.get("severity") == "hard_block" for alert in alerts if isinstance(alert, dict)):
        report["status"] = "fail"
    elif any(alert.get("severity") == "inconclusive" for alert in alerts if isinstance(alert, dict)):
        report["status"] = "inconclusive"
    else:
        report["status"] = "pass"


def apply_policy_summary(report: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    drafts = _drafts_by_name(trace)
    mixed = [item for item in report.get("mixed_subject_likely_windows", []) or [] if isinstance(item, dict)]
    blocked: list[dict[str, Any]] = []
    unblocked: list[dict[str, Any]] = []
    for item in mixed:
        draft = drafts.get(str(item.get("draft") or ""))
        annotated = {**item, "review_blocked": _is_review_blocked(draft)}
        if annotated["review_blocked"]:
            blocked.append(annotated)
        else:
            unblocked.append(annotated)

    metrics = report.setdefault("metrics", {})
    metrics["mixed_subject_blocked_window_count"] = len(blocked)
    metrics["mixed_subject_unblocked_window_count"] = len(unblocked)
    metrics["mixed_subject_unblocked_rate"] = (len(unblocked) / len(mixed)) if mixed else 0.0
    report["mixed_subject_policy_summary"] = {
        "mixed_window_count": len(mixed),
        "blocked_window_count": len(blocked),
        "unblocked_window_count": len(unblocked),
        "blocked_windows": blocked,
        "unblocked_windows": unblocked,
    }
    gaps = report.setdefault("implementation_gaps", {})
    gaps["mixed_subject_policy_ready"] = True
    gaps["mixed_subject_policy_explicit"] = bool(mixed) and not unblocked

    if mixed and not unblocked:
        report["alerts"] = [
            alert for alert in report.get("alerts", []) or []
            if not (isinstance(alert, dict) and alert.get("metric") == "mixed_subject_violation_rate")
        ]
        report["bug_classifications"] = [
            item for item in report.get("bug_classifications", []) or []
            if not (isinstance(item, dict) and item.get("code") == "BUG_MIXED_SUBJECT_LIKELY")
        ]
    elif unblocked:
        report["bug_classifications"] = [
            item for item in report.get("bug_classifications", []) or []
            if not (isinstance(item, dict) and item.get("code") == "BUG_MIXED_SUBJECT_LIKELY")
        ]
        report.setdefault("bug_classifications", []).append({
            "code": "BUG_MIXED_SUBJECT_LIKELY",
            "evidence": f"{len(unblocked)} unblocked mixed-subject source-window(s)",
        })
    _recompute_status(report)
    return report


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: append_mixed_subject_policy_summary_to_report.py RUN_QUALITY_REPORT_JSON DRAFT_TRACE_JSON", file=sys.stderr)
        return 2
    report_path = Path(sys.argv[1])
    trace_path = Path(sys.argv[2])
    if not report_path.exists() or not trace_path.exists():
        return 0
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    if not isinstance(report, dict) or not isinstance(trace, dict):
        return 0
    _write_json(report_path, apply_policy_summary(report, trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
