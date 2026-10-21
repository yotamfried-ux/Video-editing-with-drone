#!/usr/bin/env python3
"""Contract: when QA fails a reel, WHY reaches the database, the gate error and the QA prompt layout note."""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline.publishable_reel_policy as policy  # noqa: E402
import publishable_manifest_contract as contract  # noqa: E402

FAILED_PART = {
    "part_index": 1, "qa_verdict": "FAIL", "qa_engagement_score": 40, "qa_overall": "weak hook and dead time",
    "qa_defects": [
        {"type": "BAD_FIRST_CLIP", "severity": "minor", "note": "The reel opens with the surfer paddling."},
        {"type": "DEAD_TIME", "severity": "critical", "note": "7 s after the ride ends."},
        {"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": "bookkeeping"}],
}


def test_failed_part_reasons_name_score_summary_and_each_defect() -> None:
    reasons = policy.qa_note_reasons(FAILED_PART)
    assert reasons[0] == "qa_score:40/60", reasons
    assert reasons[1].startswith("qa_summary:weak hook"), reasons
    assert "qa_minor:BAD_FIRST_CLIP: The reel opens with the surfer paddling." in reasons, reasons
    assert any(r.startswith("qa_critical:DEAD_TIME") for r in reasons), reasons
    assert not any("QA_REVIEW_REQUIRED" in r for r in reasons), "bookkeeping marker is not a finding"


def test_passing_or_ungraded_parts_add_no_reasons() -> None:
    assert policy.qa_note_reasons({"qa_verdict": "PASS", "qa_engagement_score": 80}) == []
    assert policy.qa_note_reasons({"qa_verdict": None}) == []
    assert policy.qa_note_reasons({}) == []


def test_reasons_are_bounded() -> None:
    part = {"qa_verdict": "FAIL", "qa_engagement_score": 10, "qa_overall": "x",
            "qa_defects": [{"type": f"D{i}", "severity": "minor", "note": "n" * 400} for i in range(30)]}
    reasons = policy.qa_note_reasons(part)
    assert len(reasons) <= 6 and all(len(r) <= 200 for r in reasons), reasons


def test_database_record_carries_the_findings() -> None:
    row = {"athlete_key": "k", "blocking_reasons": ["final_qa_failed:reel.mp4"], "parts": [FAILED_PART]}
    part = {**FAILED_PART, "render_ready": False, "uploaded_to_review": True, "technical_issues": ["final_qa_failed"],
            "qa_evidence_recorded": True, "qa_passed": False, "media_specs_revision": "r"}
    record = policy._draft_publishability_record(row, part, storage_object_id="s", draft_name="D")
    blocked = record["approval_blocked_reasons"]
    assert "final_qa_failed:reel.mp4" in blocked and "qa_score:40/60" in blocked, blocked
    assert any(r.startswith("qa_critical:DEAD_TIME") for r in blocked), blocked


def test_gate_error_names_the_findings_but_keeps_its_prefix() -> None:
    manifest = {"schema_version": contract.SCHEMA_VERSION, "athletes": [{
        "athlete_key": "k", "athlete_label": "Surfer", "athlete_ids": ["a"], "eligible": True,
        "primary_publishable_reel": None, "parts": [{**FAILED_PART, "file_name": "D.mp4"}]}],
        "summary": {}}
    errors = contract.validate_manifest(manifest)
    line = next(e for e in errors if "final QA verdict is not PASS" in e)
    assert line.startswith("Surfer: Part 1 final QA verdict is not PASS"), line
    assert "score 40" in line and "BAD_FIRST_CLIP" in line and "DEAD_TIME" in line, line


def test_qa_prompt_explains_the_blurred_backdrop_layout() -> None:
    sys.modules.setdefault("langsmith", types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn)))
    source = (ROOT / "pipeline" / "stages" / "analyzer.py").read_text()
    runner = (ROOT / "pipeline" / "source_evidence_runner.py").read_text()
    assert "_QA_LAYOUT_NOTE" in source and "deliberate layout" in source
    assert "prompt = _QA_REEL_PROMPT + _QA_LAYOUT_NOTE" in source
    assert '_QA_LAYOUT_NOTE' in runner
    assert "too small to read on a phone" in source, "a genuinely tiny athlete must still be reportable"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS QA findings contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
