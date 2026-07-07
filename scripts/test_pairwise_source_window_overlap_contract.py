#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp_pairwise_source_window_overlap_contract"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from scripts.append_pairwise_source_window_overlap_to_report import append_summary

    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    report_path = TMP / "run_quality_report.json"
    trace_path = TMP / "draft_decision_trace.json"

    write_json(
        report_path,
        {
            "status": "fail",
            "metrics": {
                "source_window_overlap_pair_count": 1,
                "source_window_overlap_duplicate_rate": 1.0,
            },
            "alerts": [
                {"metric": "source_window_overlap_duplicate_rate", "severity": "hard_block", "reason": "aggregate false positive"},
                {"metric": "mixed_subject_violation_rate", "severity": "hard_block", "reason": "still real"},
            ],
            "bug_classifications": [
                {"code": "BUG_DUPLICATE_MOMENT_LIKELY", "evidence": "aggregate false positive"},
                {"code": "BUG_MIXED_SUBJECT_LIKELY", "evidence": "still real"},
            ],
            "source_window_overlap_duplicates": [
                {"left_window": {"start": 11.0, "end": 148.0}, "right_window": {"start": 39.0, "end": 106.0}}
            ],
            "implementation_gaps": {},
        },
    )
    write_json(
        trace_path,
        {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "drafts": [
                {
                    "draft_id": "a",
                    "draft_name": "a.mp4",
                    "source_window": {"source_video": "source.mp4", "start": 11.0, "end": 148.0},
                    "source_windows": [
                        {"source_video": "source.mp4", "start": 11.0, "end": 38.0},
                        {"source_video": "source.mp4", "start": 121.0, "end": 148.0},
                    ],
                },
                {
                    "draft_id": "b",
                    "draft_name": "b.mp4",
                    "source_window": {"source_video": "source.mp4", "start": 39.0, "end": 106.0},
                    "source_windows": [
                        {"source_video": "source.mp4", "start": 39.0, "end": 106.0},
                    ],
                },
            ],
        },
    )
    report = append_summary(report_path, trace_path)
    codes = {item["code"] for item in report["bug_classifications"]}
    require(report["metrics"]["source_window_overlap_pair_count"] == 0, "aggregate-only overlap should not count")
    require(report["metrics"]["source_window_overlap_duplicate_rate"] == 0.0, "aggregate-only overlap rate should be zero")
    require(report["source_window_overlap_duplicates"] == [], "aggregate-only duplicate evidence should be cleared")
    require("BUG_DUPLICATE_MOMENT_LIKELY" not in codes, "aggregate-only duplicate classification should be cleared")
    require("BUG_MIXED_SUBJECT_LIKELY" in codes, "unrelated classifications must remain")
    require(report["status"] == "fail", "other hard-block alerts must still fail the report")
    require(report["implementation_gaps"]["source_window_overlap_pairwise_metric_ready"] is True, "pairwise readiness missing")

    write_json(
        trace_path,
        {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "drafts": [
                {"draft_id": "a", "draft_name": "a.mp4", "source_windows": [{"source_video": "source.mp4", "start": 10.0, "end": 20.0}]},
                {"draft_id": "b", "draft_name": "b.mp4", "source_windows": [{"source_video": "source.mp4", "start": 15.0, "end": 22.0}]},
            ],
        },
    )
    write_json(report_path, {"status": "pass", "metrics": {}, "alerts": [], "bug_classifications": [], "implementation_gaps": {}})
    report = append_summary(report_path, trace_path)
    codes = {item["code"] for item in report["bug_classifications"]}
    require(report["metrics"]["source_window_overlap_pair_count"] == 1, "concrete overlap should count")
    require("BUG_DUPLICATE_MOMENT_LIKELY" in codes, "concrete overlap classification missing")
    require(report["status"] == "fail", "concrete overlap should hard-block")

    shutil.rmtree(TMP, ignore_errors=True)
    print("pairwise source-window overlap contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
