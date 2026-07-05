#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.qa_gate_policy import BLOCKING_DEFECT_TYPES, build_qa_diagnostics, critical_defects
    from pipeline.qa_state import mark_review_required, needs_review

    qa = {"verdict": "PASS", "overall": "QA skipped", "defects": [], "engagement_score": 100}
    if not needs_review(qa):
        raise SystemExit("qa should require review")
    qa = mark_review_required(qa)
    if qa.get("verdict") != "FAIL" or qa.get("engagement_score") != 0:
        raise SystemExit("qa should be converted")
    if "QA_REVIEW_REQUIRED" not in BLOCKING_DEFECT_TYPES or len(critical_defects(qa)) != 1:
        raise SystemExit("review required is not blocking")
    diag = build_qa_diagnostics(qa, retry_count=1, decision="flagged_manual_review", reel_path="/tmp/reel.mp4")
    if diag.get("critical_defect_count") != 1 or diag.get("qa_review_required") is not True:
        raise SystemExit("diagnostics missing")
    print("QA review required contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
