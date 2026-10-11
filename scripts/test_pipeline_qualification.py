#!/usr/bin/env python3
"""Fast offline positive/negative controls for the pipeline diagnostic auditor."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from qualify_pipeline_diagnostics import evaluate


def valid_fixture() -> dict[str, object]:
    name = "DRAFT_athlete_one.mp4"
    candidate = {"candidate_id": "e1", "selected": True, "discarded": False,
                 "source_video": "source.mp4", "person_id": "person_A", "athlete_id": "athlete_1"}
    return {
        "summary.json": {"sidecar_count": 1, "sidecars": ["source.perception.json"]},
        "candidate_decision_ledger.json": {"candidate_count": 1, "selected_count": 1,
                                           "discarded_count": 0, "candidates": [candidate]},
        "selection_decision_audit.json": {"summary": {"candidate_count": 1, "selected_count": 1,
                                                       "discarded_count": 0}, "candidates": [candidate]},
        "draft_decision_trace.json": {"draft_count": 1, "drafts": [{"draft_name": name}]},
        "athlete_coverage_report.json": {"summary": {"athlete_accountability_rate": 1.0,
                                                       "coverage_gap_cluster_count": 0}},
        "publishable_reel_manifest.json": {"athletes": [{"athlete_ids": ["athlete_1"],
             "parts": [{"review_draft_name": name, "uploaded_to_review": True,
                        "qa_evidence_recorded": True, "qa_verdict": "PASS",
                        "qa_passed": True, "publishable": True}]}]},
        "publishable_reel_gate_result.json": {"passed": True, "errors": []},
        "run_quality_report.json": {"sidecar_schema_errors": [], "mixed_subject_likely_windows": []},
        "sidecars/source.perception.json": {"tracks": []},
    }


def audit(payloads: dict[str, object], *, zipped: bool = False) -> dict:
    with tempfile.TemporaryDirectory() as dirname:
        folder = Path(dirname)
        for name, data in payloads.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        source = folder
        if zipped:
            source = folder.parent / (folder.name + ".zip")
            with zipfile.ZipFile(source, "w") as archive:
                for p in folder.rglob("*"):
                    if p.is_file():
                        archive.write(p, p.relative_to(folder).as_posix())
        try:
            return evaluate(source, run_id="synthetic")
        finally:
            if zipped:
                source.unlink(missing_ok=True)


def assert_fails_with(payloads: dict[str, object], expected: str) -> None:
    report = audit(payloads)
    assert report["offline_status"] == "FAIL", report
    assert expected in report["failed_checks"], report["failed_checks"]


def main() -> None:
    good = valid_fixture()
    for zip_input in (False, True):
        report = audit(good, zipped=zip_input)
        assert report["offline_status"] == "PASS", report
        assert report["system_e2e_status"] == "NOT_TESTED"

    bad = copy.deepcopy(good)
    bad.pop("candidate_decision_ledger.json")
    assert_fails_with(bad, "REQUIRED_ARTIFACTS")

    bad = copy.deepcopy(good)
    bad["summary.json"]["sidecar_count"] = 2
    assert_fails_with(bad, "PERCEPTION_SIDECAR_INVENTORY")

    bad = copy.deepcopy(good)
    bad["publishable_reel_manifest.json"]["athletes"][0]["parts"] = []
    assert_fails_with(bad, "REVIEW_MANIFEST_RECONCILIATION")
    assert_fails_with(bad, "FINAL_QA_EVIDENCE")

    bad = copy.deepcopy(good)
    part = bad["publishable_reel_manifest.json"]["athletes"][0]["parts"][0]
    part["qa_evidence_recorded"] = False
    assert_fails_with(bad, "FINAL_QA_EVIDENCE")
    assert_fails_with(bad, "PUBLISHABILITY_FAIL_CLOSED")

    bad = copy.deepcopy(good)
    bad["athlete_coverage_report.json"]["summary"].update(
        athlete_accountability_rate=0.74, coverage_gap_cluster_count=19)
    assert_fails_with(bad, "ATHLETE_ACCOUNTABILITY")

    bad = copy.deepcopy(good)
    bad["run_quality_report.json"]["mixed_subject_likely_windows"] = [{"draft": "bad.mp4"}]
    assert_fails_with(bad, "PRIMARY_SUBJECT_GATE")

    bad = copy.deepcopy(good)
    bad["publishable_reel_gate_result.json"].update(passed=False, errors=["qa missing"])
    assert_fails_with(bad, "BUSINESS_GATE")

    bad = copy.deepcopy(good)
    row = {"candidate_id": "e2", "selected": False, "discarded": True,
           "discard_cause_detailed": "selected_by_selector_not_emitted_as_draft"}
    bad["candidate_decision_ledger.json"]["candidates"].append(row)
    bad["candidate_decision_ledger.json"].update(candidate_count=2, discarded_count=1)
    bad["selection_decision_audit.json"]["candidates"].append(row)
    bad["selection_decision_audit.json"]["summary"].update(candidate_count=2, discarded_count=1)
    assert_fails_with(bad, "UNEXPLAINED_SELECTOR_DROP")

    print("SportReel pipeline offline evidence controls: PASS (positive, ZIP, and 8 negative cases)")


if __name__ == "__main__":
    sys.exit(main())