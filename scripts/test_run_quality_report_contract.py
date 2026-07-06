#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp_run_quality_report_contract"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def detection(time_sec: float, track_id: int) -> dict:
    return {
        "frame_index": int(time_sec * 10),
        "time_sec": time_sec,
        "bbox_xyxy": [10, 10, 50, 80],
        "frame_width": 100,
        "frame_height": 100,
        "confidence": 0.9,
        "class_id": 0,
        "class_name": "person",
        "track_id": track_id,
    }


def main() -> int:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    debug = TMP / "pipeline-debug"
    source = TMP / "source.mp4"
    draft = TMP / "DRAFT_surfer.mp4"
    duplicate_draft = TMP / "DRAFT_surfer_part_2.mp4"
    source.write_bytes(b"source")
    draft.write_bytes(b"draft")
    duplicate_draft.write_bytes(b"draft2")
    sidecar = TMP / "source.perception.json"
    metadata_path = TMP / "reels_metadata.json"
    trace_path = TMP / "draft_decision_trace.json"
    write_json(
        sidecar,
        {
            "source_video": str(source),
            "status": "ok",
            "backend": "ultralytics",
            "detections": [
                detection(12.5, 7),
                detection(13.5, 7),
                detection(14.5, 8),
                detection(15.5, 8),
                detection(16.5, 9),
            ],
        },
    )
    write_json(
        debug / "summary.json",
        {
            "exit_code": 0,
            "tmp_dir": str(TMP),
            "file_count": 5,
            "sidecar_count": 1,
            "sidecars": [sidecar.name],
            "files": [
                {"path": source.name, "size_bytes": 6},
                {"path": draft.name, "size_bytes": 5},
                {"path": duplicate_draft.name, "size_bytes": 6},
                {"path": sidecar.name, "size_bytes": sidecar.stat().st_size},
                {"path": trace_path.name, "size_bytes": 1},
            ],
        },
    )
    (debug / "run_tracked.log").write_text("Long video: source.mp4\npipeline ok", encoding="utf-8")
    write_json(
        metadata_path,
        {
            "DRAFT_surfer.mp4": {
                "sport": "surfing",
                "events": [
                    {"type": "ride", "score": 9, "start": 12.0, "end": 20.0, "description": "clean ride", "edit": {}}
                ],
                "source_quality": {"width": 1920, "height": 1080, "fps": 30.0},
            },
            "DRAFT_surfer_part_2.mp4": {
                "sport": "surfing",
                "events": [
                    {"type": "ride", "score": 8, "start": 15.0, "end": 22.0, "description": "overlapping ride", "edit": {}}
                ],
                "source_quality": {"width": 1920, "height": 1080, "fps": 30.0},
            },
        },
    )
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        report = json.loads((debug / "run_quality_report.json").read_text(encoding="utf-8"))
        require(report["schema_version"] == "sportreel.run_quality_report.v1", "report schema version missing")
        require(report["metrics"]["draft_count"] == 2, "draft_count metric missing")
        require(report["metrics"]["sidecar_count"] == 1, "sidecar_count metric missing")
        require(report["metrics"]["track_id_missing_rate"] == 0.0, "track id should be present")
        require(report["metrics"]["bbox_out_of_bounds_rate"] == 0.0, "bbox should be valid")
        require(report["status"] in {"fail", "inconclusive"}, "missing decision trace must not pass")
        codes = {item["code"] for item in report["bug_classifications"]}
        require("BUG_SELECTION_BYPASSED_EVIDENCE" in codes, "missing decision trace bug classification")
        require("BUG_RECALL_UNKNOWN" in codes, "missing dropped reasons bug classification")

        subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_draft_decision_trace.py"), str(metadata_path), str(debug / "run_tracked.log"), str(trace_path)],
            cwd=ROOT,
            check=True,
        )
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        require(trace["schema_version"] == "sportreel.draft_decision_trace.v1", "trace schema version missing")
        require(trace["draft_count"] == 2, "trace draft count missing")
        require(trace["drafts"][0]["source_window"]["start"] == 12.0, "trace source window start missing")
        require(trace["drafts"][0]["source_window"]["end"] == 20.0, "trace source window end missing")
        require(trace["drafts"][0]["source_window"]["source_video"] == "source.mp4", "trace source video missing")

        (TMP / "dropped_reasons.json").write_text('{"dropped_reason":"fixture"}', encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        report = json.loads((debug / "run_quality_report.json").read_text(encoding="utf-8"))
        require(report["metrics"]["draft_metadata_count"] == 2, "draft metadata count missing")
        require(report["metrics"]["draft_source_window_coverage_rate"] == 1.0, "source-window coverage missing")
        require(report["draft_decision_trace"]["drafts_with_source_window"] == 2, "trace summary missing")
        require(report["metrics"]["source_window_overlap_pair_count"] == 1, "overlap pair count missing")
        require(report["metrics"]["source_window_overlap_duplicate_rate"] == 1.0, "overlap duplicate rate missing")
        require(report["source_window_overlap_duplicates"][0]["overlap_seconds"] == 5.0, "overlap evidence missing")
        require(report["metrics"]["mixed_subject_likely_window_count"] == 1, "mixed-subject count missing")
        require(report["metrics"]["mixed_subject_violation_rate"] == 0.5, "mixed-subject rate missing")
        require(report["mixed_subject_likely_windows"][0]["primary_track_dominance_ratio"] == 0.4, "mixed-subject dominance missing")
        require(set(report["mixed_subject_likely_windows"][0]["visible_track_ids"]) == {"7", "8", "9"}, "mixed-subject track ids missing")
        codes = {item["code"] for item in report["bug_classifications"]}
        require("BUG_DUPLICATE_MOMENT_LIKELY" in codes, "duplicate moment classification missing")
        require("BUG_MIXED_SUBJECT_LIKELY" in codes, "mixed subject classification missing")
        require(report["implementation_gaps"]["mixed_subject_metric_ready"] is True, "mixed-subject metric readiness missing")
        require(report["status"] == "fail", "duplicate/mixed fixture should fail quality report")
        print("Run quality report contract checks passed")
        return 0
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
