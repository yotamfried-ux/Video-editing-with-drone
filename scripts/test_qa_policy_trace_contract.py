#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(token: str, text: str, label: str) -> None:
    if token not in text:
        raise SystemExit(f"{label} missing {token}")


def require_true(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _blocked_draft(index: int) -> dict:
    return {
        "draft_id": f"draft-{index}",
        "draft_name": f"DRAFT_blocked_{index}.mp4",
        "qa_status": "review_required",
        "review_required_reasons": ["MULTI_PERSON_CLIP"],
        "approval_blocked_reasons": ["MULTI_PERSON_CLIP: review required"],
        "qa_gate": {
            "qa_review_required": True,
            "defects": [{"type": "MULTI_PERSON_CLIP", "severity": "critical", "blocking": True}],
        },
        "source_windows": [{"subject_isolation_gate": {"decision": "review_required"}}],
    }


def _base_report() -> dict:
    return {
        "status": "fail",
        "metrics": {
            "draft_count": 3,
            "uploaded_draft_count": 3,
            "qa_gate_bypass_rate": 1.0,
            "mixed_subject_violation_rate": 1.0,
        },
        "alerts": [
            {"metric": "qa_critical_defect_count", "severity": "hard_block"},
            {"metric": "qa_gate_bypass_rate", "severity": "hard_block"},
            {"metric": "mixed_subject_violation_rate", "severity": "hard_block"},
        ],
        "bug_classifications": [
            {"code": "BUG_QA_GATE_BYPASSED"},
            {"code": "BUG_MIXED_SUBJECT_LIKELY"},
        ],
        "qa_gate_summary": {"qa_still_failing_count": 5, "qa_gate_bypass_rate": 1.0},
        "implementation_gaps": {},
    }


def validate_final_blocked_bypass_resolution() -> None:
    from scripts.append_qa_policy_trace_summary_to_report import append_summary

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        report_path = tmp_path / "report.json"
        trace_path = tmp_path / "trace.json"
        report_path.write_text(json.dumps(_base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps({"drafts": [_blocked_draft(1), _blocked_draft(2), _blocked_draft(3)]}), encoding="utf-8")
        report = append_summary(report_path, trace_path)

    metrics = report["metrics"]
    gaps = report["implementation_gaps"]
    alerts = report.get("alerts", [])
    bugs = report.get("bug_classifications", [])
    require_true(metrics["qa_gate_bypass_rate"] == 0.0, "final blocked drafts must clear QA bypass rate")
    require_true(metrics["qa_blocked_draft_count"] == 3, "all final drafts should be counted as blocked")
    require_true(metrics["qa_unblocked_final_draft_count"] == 0, "no unblocked final drafts expected")
    require_true(gaps.get("qa_gate_policy_explicit") is True, "QA policy should be explicit when all final drafts are blocked")
    require_true(not any(item.get("metric") == "qa_gate_bypass_rate" for item in alerts), "qa_gate_bypass_rate alert should be removed")
    require_true(not any(item.get("metric") == "qa_critical_defect_count" for item in alerts), "raw QA critical alert should not hard-block blocked final drafts")
    require_true(not any(item.get("code") == "BUG_QA_GATE_BYPASSED" for item in bugs), "BUG_QA_GATE_BYPASSED should be removed")
    require_true(not any(item.get("code") == "BUG_MIXED_SUBJECT_LIKELY" for item in bugs), "blocked visibility bugs should be removed")


def main() -> int:
    qa_policy = read("pipeline/qa_gate_policy.py")
    trace_builder = read("scripts/build_draft_decision_trace.py")
    review_policy = read("web-api/src/lib/draft-review-policy.ts")
    wrapper = read("scripts/run_pipeline_with_diagnostics.sh")
    report_step = read("scripts/append_qa_policy_trace_summary_to_report.py")

    for token in ["blocked_review_required", "review_required_reasons", "approval_blocked_reasons", "qa_review_required"]:
        require(token, qa_policy, "qa policy")
    for token in ["qa_gate", "review_required_reasons", "approval_blocked_reasons", "qa_status", "final_cut_start", "subject_isolation_gate"]:
        require(token, trace_builder, "draft trace")
    for token in ["QA-FLAGGED", "QA-BLOCKED", "approval_blocked_reasons"]:
        require(token, review_policy, "review policy")
    require("append_qa_policy_trace_summary_to_report.py", wrapper, "diagnostics wrapper")
    for token in ["qa_review_required_draft_count", "qa_blocked_draft_count", "BUG_QA_GATE_BYPASSED", "mixed_subject_policy_marked_window_count", "BUG_MIXED_SUBJECT_LIKELY", "qa_unblocked_final_draft_count", "qa_critical_defect_count"]:
        require(token, report_step, "qa policy report step")

    validate_final_blocked_bypass_resolution()

    print("QA policy trace contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
