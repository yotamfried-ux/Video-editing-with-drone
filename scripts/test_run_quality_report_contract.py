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
    sys.path.insert(0, str(ROOT))
    from pipeline.stages.selector_candidates import build_selector_candidate_events

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
    upstream_candidates_path = TMP / "selector_candidate_events.json"
    ledger_path = TMP / "candidate_decision_ledger.json"
    fragment_tracks = [detection(30.0 + index, 100 + index) for index in range(10)]
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
                *fragment_tracks,
            ],
        },
    )
    write_json(
        debug / "summary.json",
        {
            "exit_code": 0,
            "tmp_dir": str(TMP),
            "file_count": 7,
            "sidecar_count": 1,
            "sidecars": [sidecar.name],
            "files": [
                {"path": source.name, "size_bytes": 6},
                {"path": draft.name, "size_bytes": 5},
                {"path": duplicate_draft.name, "size_bytes": 6},
                {"path": sidecar.name, "size_bytes": sidecar.stat().st_size},
                {"path": trace_path.name, "size_bytes": 1},
                {"path": upstream_candidates_path.name, "size_bytes": 1},
                {"path": ledger_path.name, "size_bytes": 1},
            ],
        },
    )
    (debug / "run_tracked.log").write_text(
        "Long video: source.mp4\n"
        "QA still failing for DRAFT_surfer.mp4 — uploading FLAGGED for operator review\n"
        "No actionable fix for QA defects — keeping reel as-is\n"
        "PREMATURE_CUT: wave outcome missing\n"
        "DUPLICATE_MOMENT: source window overlaps another draft\n"
        "IDENTITY_MISMATCH: title/person mismatch\n"
        "✅ 3 draft(s) uploaded to REVIEW folder\n"
        "pipeline ok",
        encoding="utf-8",
    )
    write_json(
        metadata_path,
        {
            "DRAFT_surfer.mp4": {
                "sport": "surfing",
                "events": [
                    {
                        "type": "ride", "score": 9, "start": 12.0, "end": 20.0, "description": "clean ride", "edit": {},
                        "athlete_id": "ath_dup_fixture", "athlete_canonical_evidence_status": "strong",
                    }
                ],
                "source_quality": {"width": 1920, "height": 1080, "fps": 30.0},
            },
            "DRAFT_surfer_part_2.mp4": {
                "sport": "surfing",
                "events": [
                    {
                        "type": "ride", "score": 8, "start": 15.0, "end": 22.0, "description": "overlapping ride", "edit": {},
                        "athlete_id": "ath_dup_fixture", "athlete_canonical_evidence_status": "strong",
                    }
                ],
                "source_quality": {"width": 1920, "height": 1080, "fps": 30.0},
            },
        },
    )
    selector_payload = build_selector_candidate_events(
        [
            {
                "id": "person_A",
                "description": "surfer on source fixture",
                "events": [
                    {"type": "ride", "score": 9, "start": 12.0, "end": 20.0, "description": "selected fixture ride"},
                    {"type": "ride", "score": 8, "start": 15.0, "end": 22.0, "description": "second selected ride"},
                    {"type": "ride", "score": 7, "start": 80.0, "end": 90.0, "description": "selected upstream but no draft trace"},
                    {"type": "paddle", "score": 4, "start": 40.0, "end": 47.0, "description": "low value paddle"},
                    {"type": "snap", "score": 8, "start": 50.0, "end": 53.0, "description": "too short fragment"},
                ],
            }
        ],
        source_video="source.mp4",
    )
    write_json(upstream_candidates_path, selector_payload)
    require(selector_payload["schema_version"] == "sportreel.selector_candidate_events.v1", "selector candidate schema missing")
    require(selector_payload["selected_count"] == 3, "selector selected count missing")
    require(selector_payload["discarded_count"] == 2, "selector discarded count missing")
    discard_causes = {item["discard_cause"] for item in selector_payload["candidates"] if item.get("discarded")}
    require(discard_causes == {"score_below_selection_threshold", "fragment_shorter_than_min_event_sec"}, "selector discard causes missing")

    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/append_qa_gate_summary_to_report.py"), str(debug / "run_quality_report.json"), str(debug / "run_tracked.log")],
            cwd=ROOT,
            check=True,
        )
        report = json.loads((debug / "run_quality_report.json").read_text(encoding="utf-8"))
        require(report["schema_version"] == "sportreel.run_quality_report.v1", "report schema version missing")
        require(report["metrics"]["draft_count"] == 2, "draft_count metric missing")
        require(report["metrics"]["sidecar_count"] == 1, "sidecar_count metric missing")
        require(report["metrics"]["track_id_missing_rate"] == 0.0, "track id should be present")
        require(report["metrics"]["bbox_out_of_bounds_rate"] == 0.0, "bbox should be valid")
        require(report["metrics"]["qa_critical_defect_count"] == 3, "QA critical defect count missing")
        require(report["metrics"]["qa_flagged_draft_count"] == 1, "QA flagged draft count missing")
        require(report["metrics"]["uploaded_draft_count"] == 3, "uploaded draft count missing")
        require(report["metrics"]["draft_upload_trace_mismatch_count"] == 1, "draft/upload trace mismatch count missing")
        require(round(report["metrics"]["draft_upload_trace_mismatch_rate"], 3) == 0.333, "draft/upload trace mismatch rate missing")
        require(report["metrics"]["qa_gate_bypass_rate"] == 1.0, "QA gate bypass rate missing")
        require(report["qa_gate_summary"]["qa_critical_defect_counts"]["IDENTITY_MISMATCH"] == 1, "QA identity mismatch count missing")
        codes = {item["code"] for item in report["bug_classifications"]}
        require("BUG_SELECTION_BYPASSED_EVIDENCE" in codes, "missing decision trace bug classification")
        require("BUG_RECALL_UNKNOWN" in codes, "missing dropped reasons bug classification")
        require("BUG_TRACKING_FRAGMENTATION_LIKELY" in codes, "fragmentation classification should be possible without draft trace")
        require("BUG_QA_GATE_BYPASSED" in codes, "QA gate bypass classification missing")
        require("BUG_DRAFT_TRACE_MISMATCH" in codes, "draft trace mismatch classification missing")

        subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_draft_decision_trace.py"), str(metadata_path), str(debug / "run_tracked.log"), str(trace_path)],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_candidate_decision_ledger.py"), str(trace_path), str(ledger_path)],
            cwd=ROOT,
            check=True,
        )
        selected_only_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        require(selected_only_ledger["candidate_count"] == 2, "selected-only ledger candidate count missing")
        require(selected_only_ledger["selected_count"] == 2, "selected-only ledger selected count missing")
        require(selected_only_ledger["discarded_count"] == 0, "selected-only ledger discarded count should be zero")
        require(selected_only_ledger["recall_status"] == "selected_only", "selected-only ledger must not pretend discarded candidates exist")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/build_candidate_decision_ledger.py"), str(trace_path), str(ledger_path), str(upstream_candidates_path)],
            cwd=ROOT,
            check=True,
        )
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        require(ledger["schema_version"] == "sportreel.candidate_decision_ledger.v1", "ledger schema version missing")
        require(ledger["candidate_count"] == 5, "ledger candidate count missing")
        require(ledger["selected_count"] == 2, "ledger selected count missing")
        require(ledger["discarded_count"] == 3, "ledger discarded count missing")
        require(ledger["unmatched_selector_selected_count"] == 1, "unmatched selector selected count missing")
        require(ledger["discard_causes_available"] is True, "ledger discard causes should be complete")
        require(ledger["recall_status"] == "selected_and_discarded", "ledger should report measurable selected and discarded candidates")
        all_discard_causes = {item["discard_cause"] for item in ledger["candidates"] if item.get("discarded")}
        require("selected_by_selector_not_emitted_as_draft" in all_discard_causes, "unmatched selector selection discard cause missing")
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        require(trace["schema_version"] == "sportreel.draft_decision_trace.v1", "trace schema version missing")
        require(trace["draft_count"] == 2, "trace draft count missing")
        require(trace["drafts"][0]["source_window"]["start"] == 12.0, "trace source window start missing")
        require(trace["drafts"][0]["source_window"]["end"] == 20.0, "trace source window end missing")
        require(trace["drafts"][0]["source_window"]["source_video"] == "source.mp4", "trace source video missing")

        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/append_candidate_ledger_summary_to_report.py"), str(debug / "run_quality_report.json"), str(ledger_path)],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/append_qa_gate_summary_to_report.py"), str(debug / "run_quality_report.json"), str(debug / "run_tracked.log")],
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
        require(report["metrics"]["duplicate_athlete_likely_draft_count"] == 1, "duplicate-athlete count missing")
        require(report["metrics"]["duplicate_athlete_violation_rate"] == 0.5, "duplicate-athlete rate missing")
        require(report["duplicate_athlete_likely_drafts"][0]["athlete_id"] == "ath_dup_fixture", "duplicate-athlete id missing")
        require(
            set(report["duplicate_athlete_likely_drafts"][0]["draft_ids"]) == {"DRAFT_surfer.mp4", "DRAFT_surfer_part_2.mp4"},
            "duplicate-athlete draft ids missing",
        )
        require(report["metrics"]["short_track_count"] == 13, "short track count missing")
        require(report["metrics"]["short_track_rate"] == 1.0, "short track rate missing")
        require(report["track_fragmentation"]["track_count"] == 13, "track fragmentation track count missing")
        require(report["track_fragmentation"]["track_duration_distribution"]["max"] < 2.0, "track duration distribution missing")
        require(report["metrics"]["candidate_ledger_count"] == 5, "candidate ledger metric missing")
        require(report["metrics"]["candidate_selected_count"] == 2, "candidate selected metric missing")
        require(report["metrics"]["candidate_discarded_count"] == 3, "candidate discarded metric missing")
        require(report["metrics"]["candidate_unmatched_selector_selected_count"] == 1, "unmatched selector selected metric missing")
        require(report["metrics"]["candidate_discard_cause_coverage_rate"] == 1.0, "candidate discard cause coverage missing")
        require(report["candidate_decision_ledger"]["recall_status"] == "selected_and_discarded", "candidate ledger recall status missing")
        require(report["implementation_gaps"]["candidate_decision_ledger_present"] is True, "candidate ledger presence missing")
        require(report["implementation_gaps"]["candidate_discarded_causes_present"] is True, "candidate discarded cause coverage gap should be closed")
        require(report["implementation_gaps"]["unmatched_selector_selection_metric_ready"] is True, "unmatched selector metric readiness missing")
        require(report["metrics"]["qa_critical_defect_count"] == 3, "QA critical defect count missing after trace")
        require(report["metrics"]["qa_flagged_draft_count"] == 1, "QA flagged draft count missing after trace")
        require(report["metrics"]["uploaded_draft_count"] == 3, "uploaded draft count missing after trace")
        require(report["metrics"]["draft_upload_trace_mismatch_count"] == 1, "draft/upload trace mismatch count missing after trace")
        require(report["implementation_gaps"]["qa_gate_policy_metric_ready"] is True, "QA policy metric readiness missing")
        require(report["implementation_gaps"]["qa_gate_policy_explicit"] is False, "QA policy explicit flag should remain false")
        require(report["implementation_gaps"]["draft_upload_trace_consistency_ready"] is True, "draft/upload trace consistency readiness missing")
        codes = {item["code"] for item in report["bug_classifications"]}
        require("BUG_DUPLICATE_MOMENT_LIKELY" in codes, "duplicate moment classification missing")
        require("BUG_DUPLICATE_ATHLETE_LIKELY" in codes, "duplicate athlete classification missing")
        require("BUG_MIXED_SUBJECT_LIKELY" in codes, "mixed subject classification missing")
        require("BUG_TRACKING_FRAGMENTATION_LIKELY" in codes, "fragmentation classification missing")
        require("BUG_QA_GATE_BYPASSED" in codes, "QA gate bypass classification missing after trace")
        require("BUG_DRAFT_TRACE_MISMATCH" in codes, "draft trace mismatch classification missing after trace")
        require("BUG_RECALL_UNKNOWN" not in codes, "recall unknown should be cleared when discarded candidates have causes")
        require(report["implementation_gaps"]["mixed_subject_metric_ready"] is True, "mixed-subject metric readiness missing")
        require(report["implementation_gaps"]["track_fragmentation_metric_ready"] is True, "fragmentation metric readiness missing")
        require(report["implementation_gaps"]["duplicate_athlete_metric_ready"] is True, "duplicate-athlete metric readiness missing")
        require(report["status"] == "fail", "duplicate/mixed/fragmentation/QA fixture should fail quality report")
        print("Run quality report contract checks passed")
        return 0
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
