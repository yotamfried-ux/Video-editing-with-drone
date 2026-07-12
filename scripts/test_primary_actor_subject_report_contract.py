#!/usr/bin/env python3
"""Regression coverage for run 29194242123 mixed-subject false positive."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module():
    path = ROOT / "scripts/append_primary_actor_subject_summary_to_report.py"
    spec = importlib.util.spec_from_file_location("primary_actor_subject_report", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load primary actor report appender")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def detection(frame: int, time_sec: float, track: int) -> dict:
    return {
        "frame_index": frame,
        "time_sec": time_sec,
        "track_id": track,
        "bbox_xyxy": [10, 10, 50, 80],
        "frame_width": 100,
        "frame_height": 100,
        "confidence": 0.9,
    }


def base_report() -> dict:
    return {
        "schema_version": "sportreel.run_quality_report.v1",
        "status": "fail",
        "metrics": {
            "draft_count": 1,
            "mixed_subject_likely_window_count": 1,
            "mixed_subject_violation_rate": 1.0,
        },
        "alerts": [{
            "metric": "mixed_subject_violation_rate",
            "severity": "hard_block",
            "reason": "coarse track-count heuristic",
        }],
        "bug_classifications": [{
            "code": "BUG_MIXED_SUBJECT_LIKELY",
            "evidence": "six tracks across the whole window",
        }],
        "implementation_gaps": {
            "mixed_subject_policy_explicit": False,
            "mixed_subject_uses_final_cut_windows": False,
        },
    }


def trace(decision: str, background_allowed: bool, defect: dict | None = None) -> dict:
    gate = {
        "decision": decision,
        "reason": "primary_actor_continuous_background_people_allowed" if background_allowed else "primary_actor_not_reliably_followable",
        "primary_track_id": "4385",
        "declared_target_track_id": "4385",
        "background_people_allowed": background_allowed,
        "ambiguity_reasons": [] if background_allowed else ["identity_switch"],
    }
    if defect:
        gate["defect"] = defect
    return {
        "schema_version": "sportreel.draft_decision_trace.v1",
        "drafts": [{
            "draft_name": "DRAFT_pink_longboard.mp4",
            "person_id": "chunk_01:person_A",
            "athlete_id": "ath_66f922a23a",
            "source_windows": [{
                "source_video": "source.mp4",
                "start": 496.0,
                "end": 521.5,
                "final_cut_start": 496.0,
                "final_cut_end": 521.5,
                "person_id": "chunk_01:person_A",
                "athlete_id": "ath_66f922a23a",
                "track_id": "4385",
                "subject_isolation_gate": gate,
            }],
        }],
    }


def main() -> int:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        report_path = root / "run_quality_report.json"
        trace_path = root / "draft_decision_trace.json"
        sidecars = root / "sidecars"
        sidecars.mkdir()

        # 28 sampled frames. The primary actor appears in 19. Only two frames
        # contain two people simultaneously; the other track IDs occur at
        # different times and must not be aggregated into a mixed-subject block.
        detections = []
        for frame in range(28):
            time_sec = 496.0 + frame * 0.9
            if frame < 19:
                detections.append(detection(frame, time_sec, 4385))
            else:
                detections.append(detection(frame, time_sec, 4497 + frame))
            if frame in {4, 11}:
                detections.append(detection(frame, time_sec, 4480))
        (sidecars / "source.perception.json").write_text(json.dumps({
            "source_video": "source.mp4",
            "detections": detections,
        }), encoding="utf-8")

        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(trace("allowed_primary_actor_clear", True)), encoding="utf-8")
        report = module.append_summary(report_path, trace_path, sidecars)
        require(report["status"] == "pass", "allowed background people remained a hard block")
        require(report["metrics"]["mixed_subject_likely_window_count"] == 0, "allowed actor window counted as mixed")
        require(report["metrics"]["mixed_subject_policy_evidence_rate"] == 1.0, "explicit gate evidence not counted")
        require(report["implementation_gaps"]["mixed_subject_policy_explicit"] is True, "policy explicit gap not closed")
        require(report["implementation_gaps"]["mixed_subject_uses_final_cut_windows"] is True, "final-cut window gap not closed")
        evaluation = report["primary_actor_subject_evaluations"][0]
        require(evaluation["sampled_frame_count"] == 28, "frame-level evidence count is wrong")
        require(evaluation["concurrent_person_frame_count"] == 2, "sequential tracks were treated as concurrent")
        require(evaluation["background_people_allowed"] is True, "primary actor decision not honored")
        require(not any(item.get("code") == "BUG_MIXED_SUBJECT_LIKELY" for item in report["bug_classifications"]), "stale mixed-subject classification remained")

        blocking_defect = {"type": "IDENTITY_SWITCH", "severity": "critical", "blocking": True}
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(trace("review_required", False, blocking_defect)), encoding="utf-8")
        blocked = module.append_summary(report_path, trace_path, sidecars)
        require(blocked["status"] == "fail", "explicit identity-switch gate did not hard block")
        require(blocked["metrics"]["mixed_subject_likely_window_count"] == 1, "blocking gate violation missing")
        require(blocked["mixed_subject_likely_windows"][0]["policy_decision"] == "review_required", "blocking policy evidence missing")

    runner = (ROOT / "scripts/run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")
    require("append_primary_actor_subject_summary_to_report.py" in runner, "diagnostics runner does not apply subject reconciliation")
    print("primary actor subject report contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
