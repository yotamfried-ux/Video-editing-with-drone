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
    qa_policy = read("pipeline/qa_gate_policy.py")
    trace_builder = read("scripts/build_draft_decision_trace.py")
    review_policy = read("web-api/src/lib/draft-review-policy.ts")
    wrapper = read("scripts/run_pipeline_with_diagnostics.sh")
    report_step = read("scripts/append_qa_policy_trace_summary_to_report.py")

    for token in ["blocked_review_required", "review_required_reasons", "approval_blocked_reasons", "qa_review_required"]:
        require(token, qa_policy, "qa policy")
    for token in ["qa_gate", "review_required_reasons", "approval_blocked_reasons", "qa_status"]:
        require(token, trace_builder, "draft trace")
    for token in ["QA-FLAGGED", "QA-BLOCKED", "approval_blocked_reasons"]:
        require(token, review_policy, "review policy")
    require("append_qa_policy_trace_summary_to_report.py", wrapper, "diagnostics wrapper")
    for token in ["qa_review_required_draft_count", "qa_blocked_draft_count", "BUG_QA_GATE_BYPASSED"]:
        require(token, report_step, "qa policy report step")

    print("QA policy trace contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
