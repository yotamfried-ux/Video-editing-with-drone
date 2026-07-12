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
        "frame_index": frame, "time_sec": time_sec, "track_id": track,
        "bbox_xyxy": [10, 10, 50, 80], "frame_width": 100,
        "frame_height": 100, "confidence": 0.9,
    }


def base_report() -> dict:
    return {
        "schema_version": "sportreel.run_quality_report.v1",
        "status": "fail",
        "metrics": {"draft_count": 1, "mixed_subject_likely_window_count": 1, "mixed_subject_violation_rate": 1.0},
        "alerts": [{"metric": "mixed_subject_violation_rate", "severity": "hard_block", "reason": "coarse track-count heuristic"}],
        "bug_classifications": [{"code": "BUG_MIXED_SUBJECT_LIKELY", "evidence": "six tracks across the whole window"}],
        "implementation_gaps": {"mixed_subject_policy_explicit": False, "mixed_subject_uses_final_cut_windows": False},
    }


def gate(decision: str, background_allowed: bool, defect: dict | None = None) -> dict:
    payload = {
        "decision": decision,
        "reason": "primary_actor_continuous_background_people_allowed" if background_allowed else "primary_actor_not_reliably_followable",
        "primary_track_id": "4385",
        "declared_target_track_id": "4385",
        "background_people_allowed": background_allowed,
        "ambiguity_reasons": [] if background_allowed else ["identity_switch"],
    }
    if defect:
        payload["defect"] = defect
    return payload


def trace(subject_gate: dict | None, multi_gate: dict | None = None) -> dict:
    window = {
        "source_video": "source.mp4", "start": 496.0, "end": 521.5,
        "final_cut_start": 496.0, "final_cut_end": 521.5,
        "person_id": "chunk_01:person_A", "athlete_id": "ath_66f922a23a", "track_id": "4385",
    }
    if subject_gate is not None:
        window["subject_isolation_gate"] = subject_gate
    if multi_gate is not None:
        window["multi_person_clip_gate"] = multi_gate
    return {
        "schema_version": "sportreel.draft_decision_trace.v1",
        "draft_count": 1,
        "drafts": [{
            "draft_name": "DRAFT_pink_longboard.mp4",
            "person_id": "chunk_01:person_A", "athlete_id": "ath_66f922a23a",
            "source_windows": [window],
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

        detections = []
        for frame in range(28):
            time_sec = 496.0 + frame * 0.9
            detections.append(detection(frame, time_sec, 4385 if frame < 19 else 4497 + frame))
            if frame in {4, 11}:
                detections.append(detection(frame, time_sec, 4480))
        (sidecars / "source.perception.json").write_text(json.dumps({
            "source_video": "source.mp4", "detections": detections,
        }), encoding="utf-8")

        allowed_gate = gate("allowed_primary_actor_clear", True)
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(trace(allowed_gate)), encoding="utf-8")
        report = module.append_summary(report_path, trace_path, sidecars)
        require(report["status"] == "pass", "allowed background people remained a hard block")
        require(report["metrics"]["mixed_subject_likely_window_count"] == 0, "allowed actor window counted as mixed")
        require(report["metrics"]["mixed_subject_policy_evidence_rate"] == 1.0, "explicit gate evidence not counted")
        require(report["implementation_gaps"]["mixed_subject_policy_explicit"] is True, "policy explicit gap not closed")
        evaluation = report["primary_actor_subject_evaluations"][0]
        require(evaluation["sampled_frame_count"] == 28, "frame-level evidence count is wrong")
        require(evaluation["concurrent_person_frame_count"] == 2, "sequential tracks were treated as concurrent")
        require(evaluation["background_people_allowed"] is True, "primary actor decision not honored")
        require(not any(item.get("code") == "BUG_MIXED_SUBJECT_LIKELY" for item in report["bug_classifications"]), "stale mixed classification remained")

        blocking_defect = {"type": "IDENTITY_SWITCH", "severity": "critical", "blocking": True}
        blocking_gate = gate("review_required", False, blocking_defect)
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(trace(blocking_gate)), encoding="utf-8")
        blocked = module.append_summary(report_path, trace_path, sidecars)
        require(blocked["status"] == "fail", "explicit identity-switch gate did not hard block")
        require(blocked["metrics"]["mixed_subject_likely_window_count"] == 1, "blocking gate violation missing")

        # An allowed subject gate must never hide a blocking multi-person gate.
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(trace(allowed_gate, blocking_gate)), encoding="utf-8")
        conflict = module.append_summary(report_path, trace_path, sidecars)
        require(conflict["status"] == "fail", "allowed gate hid a second blocking gate")
        require(conflict["primary_actor_subject_evaluations"][0]["blocking_gate_count"] == 1, "blocking gate conflict was not recorded")

        # Missing final-window evidence must be inconclusive, never silently pass.
        missing_trace = {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "draft_count": 1,
            "drafts": [{"draft_name": "DRAFT_missing_window.mp4", "source_windows": []}],
        }
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(missing_trace), encoding="utf-8")
        missing = module.append_summary(report_path, trace_path, sidecars)
        require(missing["status"] == "inconclusive", "missing actor evidence was treated as pass")
        require(missing["metrics"]["mixed_subject_unevaluated_window_count"] == 1, "missing final window was not counted")
        require(missing["implementation_gaps"]["mixed_subject_policy_explicit"] is False, "missing policy was marked explicit")

        # Exact fail-safe case from review: the quality report observed one draft,
        # but trace generation returned an empty draft list. Report count is the
        # lower bound and must prevent a false 100% policy-evidence pass.
        empty_trace = {
            "schema_version": "sportreel.draft_decision_trace.v1",
            "draft_count": 0,
            "drafts": [],
        }
        report_path.write_text(json.dumps(base_report()), encoding="utf-8")
        trace_path.write_text(json.dumps(empty_trace), encoding="utf-8")
        empty = module.append_summary(report_path, trace_path, sidecars)
        require(empty["status"] == "inconclusive", "empty trace with an observed draft was treated as pass")
        require(empty["metrics"]["mixed_subject_expected_window_count"] == 1, "report draft count was not used as the evidence lower bound")
        require(empty["metrics"]["mixed_subject_unevaluated_window_count"] == 1, "empty trace evidence gap was not counted")
        require(empty["metrics"]["mixed_subject_policy_evidence_rate"] == 0.0, "empty trace incorrectly reported complete policy evidence")

    runner = (ROOT / "scripts/run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")
    require("append_primary_actor_subject_summary_to_report.py" in runner, "diagnostics runner does not apply subject reconciliation")
    print("primary actor subject report contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
