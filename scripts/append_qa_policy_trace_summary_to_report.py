#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


_EXPLICIT_FINAL_DECISIONS = {
    "passed",
    "passed_after_reedit",
    "failed_nonblocking",
    "blocked_review_required",
    "flagged_nonblocking_review",
}


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


def _review_blocked(draft: dict[str, Any]) -> bool:
    name = str(draft.get("draft_name") or draft.get("draft_id") or "")
    qa_gate = draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else {}
    return (
        draft.get("qa_status") == "review_required"
        or "QA-FLAGGED" in name
        or "QA-BLOCKED" in name
        or bool(draft.get("approval_blocked_reasons"))
        or bool(draft.get("review_required_reasons"))
        or bool(qa_gate.get("qa_review_required"))
        or bool(_critical_defects(qa_gate))
    )


def _has_multisubject_defect(draft: dict[str, Any]) -> bool:
    qa_gate = draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else {}
    for defect in _critical_defects(qa_gate):
        if str(defect.get("type", "")).upper() == "MULTI_PERSON_CLIP":
            return True
    return False


def _subject_gate_marked_windows(drafts: list[dict[str, Any]]) -> tuple[int, int, int]:
    marked = 0
    blocked = 0
    open_count = 0
    for draft in drafts:
        draft_blocked = _review_blocked(draft)
        draft_marked = False
        for window in draft.get("source_windows", []) or []:
            if not isinstance(window, dict):
                continue
            gate = window.get("subject_isolation_gate")
            if not isinstance(gate, dict) or gate.get("decision") != "review_required":
                continue
            draft_marked = True
            marked += 1
            if draft_blocked:
                blocked += 1
            else:
                open_count += 1
        if not draft_marked and _has_multisubject_defect(draft):
            marked += 1
            if draft_blocked:
                blocked += 1
            else:
                open_count += 1
    return marked, blocked, open_count


def _remove_alert(report: dict[str, Any], metric: str) -> None:
    report["alerts"] = [
        item for item in report.get("alerts", [])
        if not (isinstance(item, dict) and item.get("metric") == metric)
    ]


def _remove_bug(report: dict[str, Any], code: str) -> None:
    report["bug_classifications"] = [
        item for item in report.get("bug_classifications", [])
        if not (isinstance(item, dict) and item.get("code") == code)
    ]


def _recompute_status(report: dict[str, Any]) -> None:
    alerts = report.get("alerts", []) or []
    if any(isinstance(item, dict) and item.get("severity") == "hard_block" for item in alerts):
        report["status"] = "fail"
    elif any(isinstance(item, dict) and item.get("severity") == "inconclusive" for item in alerts):
        report["status"] = "inconclusive"
    else:
        report["status"] = "pass"


def _qa_gate(draft: dict[str, Any]) -> dict[str, Any]:
    return draft.get("qa_gate") if isinstance(draft.get("qa_gate"), dict) else {}


def _final_drafts_policy_explicit(drafts: list[dict[str, Any]], metrics: dict[str, Any]) -> bool:
    """Return True when every final uploaded/traced draft carries a final QA decision.

    The run log contains transient failures from pre-repair drafts. Those are not a
    gate bypass when the final draft trace records, for every uploaded draft, either
    a passing/nonblocking final decision or an explicit review block.
    """
    if not drafts:
        return False
    try:
        uploaded = int(metrics.get("uploaded_draft_count") or 0)
    except (TypeError, ValueError):
        uploaded = 0
    if uploaded and uploaded != len(drafts):
        return False
    for draft in drafts:
        qa_gate = _qa_gate(draft)
        if str(qa_gate.get("decision") or "") not in _EXPLICIT_FINAL_DECISIONS:
            return False
    return True


def append_summary(report_path: Path, trace_path: Path) -> dict[str, Any]:
    report = _read_json(report_path)
    trace = _read_json(trace_path)
    drafts = [draft for draft in trace.get("drafts", []) if isinstance(draft, dict)]
    qa_blocked = [draft for draft in drafts if _review_blocked(draft)]
    review_required = list(qa_blocked)

    metrics = report.setdefault("metrics", {})
    metrics["qa_review_required_draft_count"] = len(review_required)
    metrics["qa_blocked_draft_count"] = len(qa_blocked)
    metrics["qa_unblocked_final_draft_count"] = max(0, len(drafts) - len(qa_blocked))

    decision_counts = Counter(str(_qa_gate(draft).get("decision") or "missing") for draft in drafts)
    metrics["qa_final_decision_counts"] = dict(decision_counts)
    metrics["qa_final_explicit_draft_count"] = sum(
        1 for draft in drafts if str(_qa_gate(draft).get("decision") or "") in _EXPLICIT_FINAL_DECISIONS
    )
    metrics["qa_final_blocking_defect_count"] = sum(
        len(_critical_defects(_qa_gate(draft))) for draft in drafts
    )
    metrics["qa_retry_count_total"] = sum(
        int(_qa_gate(draft).get("retry_count") or 0) for draft in drafts
    )

    qa_summary = report.setdefault("qa_gate_summary", {})
    still_failing = int(qa_summary.get("qa_still_failing_count") or 0)
    policy_explicit = _final_drafts_policy_explicit(drafts, metrics)
    qa_summary["qa_policy_explicit"] = policy_explicit
    qa_summary["qa_review_required_draft_count"] = len(review_required)
    qa_summary["qa_blocked_draft_count"] = len(qa_blocked)
    qa_summary["qa_unblocked_final_draft_count"] = metrics["qa_unblocked_final_draft_count"]
    qa_summary["qa_still_failing_count"] = still_failing
    qa_summary["qa_final_decision_counts"] = dict(decision_counts)
    qa_summary["qa_final_explicit_draft_count"] = metrics["qa_final_explicit_draft_count"]
    qa_summary["qa_final_blocking_defect_count"] = metrics["qa_final_blocking_defect_count"]
    qa_summary["qa_retry_count_total"] = metrics["qa_retry_count_total"]

    marked, marked_blocked, marked_open = _subject_gate_marked_windows(drafts)
    metrics["mixed_subject_policy_marked_window_count"] = marked
    metrics["mixed_subject_policy_blocked_window_count"] = marked_blocked
    metrics["mixed_subject_policy_unblocked_window_count"] = marked_open

    gaps = report.setdefault("implementation_gaps", {})
    if isinstance(gaps, dict):
        gaps["qa_gate_policy_explicit"] = policy_explicit
        gaps["qa_trace_policy_summary_ready"] = True
        gaps["mixed_subject_policy_explicit"] = marked > 0 and marked_open == 0
        gaps["mixed_subject_uses_final_cut_windows"] = marked > 0

    # Once every final draft has an explicit final QA state, transient defects in
    # the log are no longer enough to claim a bypass. Blocking final drafts must be
    # review-blocked; repaired/nonblocking final drafts may remain unblocked.
    if policy_explicit:
        unsafe_unblocked = [
            draft for draft in drafts
            if _critical_defects(_qa_gate(draft)) and not _review_blocked(draft)
        ]
        if not unsafe_unblocked:
            metrics["qa_gate_bypass_rate"] = 0.0
            qa_summary["qa_gate_bypass_rate"] = 0.0
            _remove_bug(report, "BUG_QA_GATE_BYPASSED")
            _remove_alert(report, "qa_gate_bypass_rate")
            _remove_alert(report, "qa_critical_defect_count")

    if marked > 0 and marked_open == 0:
        metrics["mixed_subject_violation_rate"] = 0.0
        metrics["mixed_subject_unblocked_window_count"] = 0
        metrics["mixed_subject_blocked_window_count"] = marked_blocked
        _remove_bug(report, "BUG_MIXED_SUBJECT_LIKELY")
        _remove_alert(report, "mixed_subject_violation_rate")

    _recompute_status(report)
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
        f"unblocked={metrics.get('qa_unblocked_final_draft_count', 0)} "
        f"explicit={metrics.get('qa_final_explicit_draft_count', 0)} "
        f"retries={metrics.get('qa_retry_count_total', 0)} "
        f"bypass_rate={metrics.get('qa_gate_bypass_rate', 0)} "
        f"visibility_marked={metrics.get('mixed_subject_policy_marked_window_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
