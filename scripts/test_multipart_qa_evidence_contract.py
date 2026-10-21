#!/usr/bin/env python3
"""Regression: later render invocations for the same athlete must not wipe earlier Parts' QA evidence,
and a real graded QA result flagged for review keeps its score/summary (not "qa_result_unavailable")."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.publishable_pending_scope as pending_scope
import pipeline.publishable_qa_evidence as evidence
import pipeline.publishable_reel_policy as policy
import pipeline.publishable_runtime_integrity as integrity
import pipeline.silent_output_policy as silent
from pipeline.qa_state import mark_review_required

SPECS = {"has_audio": False, "duration": 20.0, "width": 2160, "height": 3840, "aspect": 9 / 16}
LABEL = "man in a black top on a white longboard"


def qa(verdict: str, score: int = 70):
    defects = [] if verdict == "PASS" else [{"type": "NO_VISIBLE_ACTION", "severity": "critical", "note": "x"}]
    return {"verdict": verdict, "engagement_score": score, "overall": "graded", "defects": defects}


def render_and_gate(tmp: Path, name: str, result: dict) -> str:
    """One render invocation + QA gate for the same athlete label (one Part)."""
    path = str(tmp / name)
    token = pending_scope.pending_key("surfing", LABEL)
    policy.record_athlete_outcome(
        sport="surfing", athlete_label=LABEL, final_reels=[path],
        events_by_reel={path: [{"athlete_id": "A1", "type": "ride", "start": 0, "end": 8, "_src": "s.mp4"}]},
        flagged_paths=set(), specs_getter=lambda _p: SPECS)
    evidence.record_qa_result(path, result, invocation_token=token)
    evidence.apply_final_qa_evidence(sport="surfing", athlete_label=LABEL, final_reels=[path], invocation_token=token)
    return path


def test_earlier_parts_keep_qa_evidence() -> None:
    policy.social_ready_issues = silent.silent_social_ready_issues
    pending_scope.install()
    integrity.install()
    with tempfile.TemporaryDirectory(prefix="sportreel-multipart-") as directory:
        tmp = Path(directory)
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(tmp / "manifest.json")
        policy.reset_manifest()
        verdicts = {"a.mp4": "PASS", "b.mp4": "FAIL", "c.mp4": "PASS", "d.mp4": "FAIL"}
        for name, verdict in verdicts.items():
            render_and_gate(tmp, name, qa(verdict))
        rows = json.loads((tmp / "manifest.json").read_text())["athletes"]
        assert len(rows) == 1 and len(rows[0]["parts"]) == 4, rows
        for part in rows[0]["parts"]:
            name = Path(part["local_path"]).name
            assert part["qa_evidence_recorded"] is True, (name, part)
            assert part["qa_verdict"] == verdicts[name], (name, part)
            assert ("missing_final_qa_evidence" in part["technical_issues"]) is False, (name, part)
        passing = [p for p in rows[0]["parts"] if p["qa_verdict"] == "PASS"]
        assert all(p["qa_passed"] is True for p in passing)


def test_graded_review_required_result_keeps_its_grade() -> None:
    graded = {"verdict": "FAIL", "engagement_score": 58, "overall": "weak hook",
              "defects": [{"type": "SOFT_FOCUS", "severity": "critical", "note": "blurry"}],
              "qa_review_required": True}
    out = mark_review_required(graded)
    assert out["verdict"] == "FAIL" and out["engagement_score"] == 58 and out["overall"] == "weak hook", out
    assert any(d["type"] == "QA_REVIEW_REQUIRED" for d in out["defects"]), out
    assert sum(1 for d in out["defects"] if d["type"] == "QA_REVIEW_REQUIRED") == 1
    again = mark_review_required(out)
    assert sum(1 for d in again["defects"] if d["type"] == "QA_REVIEW_REQUIRED") == 1, again


def test_ungraded_result_is_still_unavailable() -> None:
    out = mark_review_required({"verdict": "PASS", "overall": "QA skipped", "defects": [], "engagement_score": 100})
    assert out["verdict"] == "FAIL" and out["engagement_score"] == 0 and out["overall"] == "qa_result_unavailable", out


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS multipart QA evidence contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
