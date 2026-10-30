#!/usr/bin/env python3
"""Contract: a run publishes the reels that passed final QA; only integrity errors or an empty result fail it.

`strict` keeps the historical behaviour (every Part of every athlete must pass). `partial` (the default of
scripts/run_pipeline_with_diagnostics.sh) withholds reels that failed QA, reports them, and fails the run only when
something other than QA is wrong or no athlete has a publishable reel. Fixtures follow the real run 39726001357:
failed Parts carry `final_qa_failed` technical issues and a non-PASS verdict.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import publishable_manifest_contract as contract  # noqa: E402
from scripts import record_publishable_business_gate_status as recorder  # noqa: E402

_spec = importlib.util.spec_from_file_location("print_run_diagnostics", ROOT / "scripts" / "print_run_diagnostics.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

CHECKER = ROOT / "scripts" / "check_publishable_reel_manifest.py"
WRAPPER = (ROOT / "scripts" / "run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")


def part(index: int, name: str, *, passed: bool = True, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "part_index": index,
        "file_name": name,
        "storage_object_id": f"review/{name}",
        "authoritative_publishability_required": True,
        "authoritative_publishability_persisted": True,
        "authoritative_manifest_revision": f"rev-{name}",
        "uploaded_to_review": True,
        "upload_error": None,
        "publishable": passed,
        "qa_evidence_recorded": True,
        "qa_verdict": "PASS" if passed else "FAIL",
        "qa_passed": passed,
        "qa_engagement_score": 70 if passed else 35,
        "qa_defects": [] if passed else [{"type": "DEAD_TIME"}, {"type": "BAD_FIRST_CLIP"}],
        "has_audio": False,
        "technical_issues": [] if passed else ["final_qa_failed"],
        "duration": 20.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }
    base.update(overrides)
    return base


def athlete(key: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    names = [p["file_name"] for p in parts if p.get("publishable") is True]
    return {
        "athlete_key": f"key_{key}",
        "athlete_ids": [f"id_{key}"],
        "athlete_label": f"athlete {key}",
        "eligible": True,
        "primary_publishable_reel": names[0] if names else None,
        "supplemental_publishable_reels": names[1:],
        "parts": parts,
    }


def manifest(*rows: dict[str, Any]) -> dict[str, Any]:
    rows_l = list(rows)
    return {
        "schema_version": contract.SCHEMA_VERSION,
        "athletes": rows_l,
        "summary": {
            "eligible_athlete_count": len(rows_l),
            "publishable_athlete_count": sum(1 for r in rows_l if r["primary_publishable_reel"]),
            "primary_publishable_reel_count": sum(1 for r in rows_l if r["primary_publishable_reel"]),
            "supplemental_publishable_reel_count": sum(len(r["supplemental_publishable_reels"]) for r in rows_l),
            "coverage_gap_count": sum(1 for r in rows_l if not r["primary_publishable_reel"]),
        },
    }


def mixed() -> dict[str, Any]:
    """A passes; B fails QA entirely; C has Part 1 passing and Part 2 failing."""
    return manifest(
        athlete("A", [part(1, "A1.mp4")]),
        athlete("B", [part(1, "B1.mp4", passed=False)]),
        athlete("C", [part(1, "C1.mp4"), part(2, "C2.mp4", passed=False)]),
    )


def test_all_pass_is_complete_in_both_modes() -> None:
    data = manifest(athlete("A", [part(1, "A1.mp4")]), athlete("B", [part(1, "B1.mp4"), part(2, "B2.mp4")]))
    for mode in contract.GATE_MODES:
        result = contract.evaluate_gate(data, mode=mode)
        assert result["passed"] and result["outcome"] == "complete" and not result["qa_gaps"], (mode, result)
        assert result["published_part_count"] == 3


def test_strict_mode_is_unchanged_and_fails_on_withheld_reels() -> None:
    data = mixed()
    strict = contract.evaluate_gate(data, mode="strict")
    assert not strict["passed"] and strict["outcome"] == "failed"
    # Same findings, same order, as the historical validator; QaGap is invisible to old callers.
    assert strict["errors"] == [str(item) for item in contract.validate_manifest(data)]
    assert json.dumps(contract.validate_manifest(data))
    assert any(isinstance(item, contract.QaGap) for item in contract.validate_manifest(data))
    assert any("final QA verdict is not PASS (score 35; DEAD_TIME, BAD_FIRST_CLIP)" in e for e in strict["errors"])


def test_partial_mode_publishes_what_passed_and_reports_the_rest() -> None:
    result = contract.evaluate_gate(mixed(), mode="partial")
    assert result["passed"] and result["outcome"] == "partial", result
    assert result["errors"] == [] and result["blocking_errors"] == []
    assert result["publishable_athlete_count"] == 2 and result["eligible_athlete_count"] == 3
    assert result["published_part_count"] == 2  # A1 and C1; B1 and C2 are withheld
    gaps = "\n".join(result["qa_gaps"])
    assert "athlete B: eligible athlete has no primary publishable reel" in gaps
    assert "athlete B: Part 1 final QA verdict is not PASS" in gaps
    assert "athlete C: Part 2 is not publishable" in gaps
    assert "athlete C: every generated Part must be publishable" in gaps
    assert "athlete A" not in gaps


def test_partial_mode_still_fails_when_nothing_is_publishable() -> None:
    data = manifest(athlete("B", [part(1, "B1.mp4", passed=False)]), athlete("D", [part(1, "D1.mp4", passed=False)]))
    result = contract.evaluate_gate(data, mode="partial")
    assert not result["passed"] and result["outcome"] == "failed"
    assert any("produced no output" in e for e in result["errors"])
    assert result["qa_gaps"], "the QA findings are still reported"


def test_partial_mode_does_not_forgive_integrity_errors() -> None:
    base = mixed()

    def blocked(mutator) -> list[str]:
        data = copy.deepcopy(base)
        mutator(data)
        result = contract.evaluate_gate(data, mode="partial")
        assert not result["passed"] and result["outcome"] == "failed", result
        return result["blocking_errors"]

    # A withheld Part that failed to upload is infrastructure, not QA.
    errs = blocked(lambda d: d["athletes"][1]["parts"][0].update(uploaded_to_review=False, upload_error="boom"))
    assert any("was not uploaded to REVIEW" in e or "upload failed" in e for e in errs), errs
    # Missing final-QA evidence on a withheld Part means QA itself broke.
    errs = blocked(lambda d: d["athletes"][1]["parts"][0].update(qa_evidence_recorded=False))
    assert any("lacks explicit final QA evidence" in e for e in errs), errs
    # Lost storage identity, duplicates, summary drift.
    errs = blocked(lambda d: d["athletes"][1]["parts"][0].update(storage_object_id=""))
    assert any("immutable REVIEW storage identity" in e for e in errs), errs
    errs = blocked(lambda d: d["athletes"][1]["parts"][0].update(file_name="A1.mp4"))
    assert any("duplicated across athletes/Parts" in e for e in errs), errs
    errs = blocked(lambda d: d["summary"].update(publishable_athlete_count=3))
    assert any("summary.publishable_athlete_count" in e for e in errs), errs
    # An eligible athlete with no generated Part at all vanished in the pipeline; QA cannot explain it.
    errs = blocked(lambda d: d["athletes"].append({**athlete("E", []), "parts": []}) or d["summary"].update(
        eligible_athlete_count=4, coverage_gap_count=2))
    assert any("athlete E: eligible athlete has no primary publishable reel" in e for e in errs), errs


def test_a_published_part_must_still_satisfy_every_check() -> None:
    data = mixed()
    data["athletes"][0]["parts"][0]["has_audio"] = True  # A1 is published and carries audio
    result = contract.evaluate_gate(data, mode="partial")
    assert not result["passed"]
    assert any("athlete A: Part 1 contains unexpected audio" in e for e in result["blocking_errors"]), result
    data = mixed()
    data["athletes"][0]["parts"][0]["height"] = 720
    result = contract.evaluate_gate(data, mode="partial")
    assert any("resolution is below" in e for e in result["blocking_errors"])


def test_withheld_part_content_problems_are_gaps_not_blockers() -> None:
    data = manifest(athlete("A", [part(1, "A1.mp4")]),
                    athlete("F", [part(1, "F1.mp4", passed=False, has_audio=True, height=640, duration=0)]))
    result = contract.evaluate_gate(data, mode="partial")
    assert result["passed"] and result["outcome"] == "partial", result
    joined = "\n".join(result["qa_gaps"])
    assert "unexpected audio" in joined and "resolution is below" in joined and "invalid finite duration" in joined


def test_coverage_cross_check_treats_a_withheld_athlete_as_a_gap() -> None:
    data = mixed()
    coverage = {
        "athletes": [
            {"athlete_cluster_id": f"c_{key}", "athlete_ids": [f"id_{key}"], "candidate_action_count": 1,
             "selected_action_count": 1, "no_output_reason_explicit": False, "coverage_requirement_met": True}
            for key in ("A", "B", "C")
        ],
        "summary": {"coverage_gap_cluster_count": 0, "athlete_accountability_rate": 1.0,
                    "selected_identity_lineage_completeness_rate": 1.0},
    }
    strict = contract.evaluate_gate(data, coverage, mode="strict")
    assert any("c_B: selected athlete has no primary publishable reel" in e for e in strict["errors"])
    partial = contract.evaluate_gate(data, coverage, mode="partial")
    assert partial["passed"] and partial["outcome"] == "partial", partial
    assert any("c_B: selected athlete has no primary publishable reel" in e for e in partial["qa_gaps"])
    # Accountability is never relaxed.
    coverage["summary"]["athlete_accountability_rate"] = 0.9
    broken = contract.evaluate_gate(data, coverage, mode="partial")
    assert not broken["passed"] and any("accountability rate" in e for e in broken["blocking_errors"])


def test_unknown_mode_is_rejected() -> None:
    try:
        contract.evaluate_gate(mixed(), mode="lenient")
    except ValueError:
        return
    raise AssertionError("unknown mode must raise")


def _run_cli(data: dict[str, Any], mode: str | None) -> tuple[int, dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "PUBLISHABLE_GATE_MODE"}
        if mode is not None:
            env["PUBLISHABLE_GATE_MODE"] = mode
        proc = subprocess.run(
            [sys.executable, str(CHECKER), str(tmp_path / "manifest.json"), str(tmp_path / "result.json")],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
        return proc.returncode, {**result, "_stdout": proc.stdout, "_stderr": proc.stderr}


def test_cli_modes_and_result_file() -> None:
    code, result = _run_cli(mixed(), None)  # default stays strict
    assert code == 1 and result["passed"] is False
    code, result = _run_cli(mixed(), "strict")
    assert code == 1
    code, result = _run_cli(mixed(), "partial")
    assert code == 0 and result["passed"] is True and result["outcome"] == "partial", result
    assert result["mode"] == "partial" and result["errors"] == [] and result["qa_gaps"]
    assert result["publishable_athlete_count"] == 2 and result["published_part_count"] == 2
    assert "PARTIAL: 2/3 athletes published" in result["_stdout"]
    code, result = _run_cli(mixed(), "lenient")
    assert code == 1 and result["passed"] is False and "PUBLISHABLE_GATE_MODE" in result["errors"][0]


def test_recorder_annotates_a_partial_run_without_touching_its_status() -> None:
    result = {"passed": True, "outcome": "partial", "publishable_athlete_count": 2, "eligible_athlete_count": 3,
              "published_part_count": 2, "qa_gaps": ["athlete B: Part 1 is not publishable"]}
    calls: list[dict[str, Any]] = []
    assert recorder.record_partial_outcome(result, result_path="r.json", marker=lambda **f: calls.append(f)) is True
    assert len(calls) == 1 and set(calls[0]) == {"meta"}, calls
    meta = calls[0]["meta"]
    assert meta["publishable_gate_outcome"] == "partial" and meta["qa_gap_count"] == 1
    assert meta["publishable_athlete_count"] == 2 and meta["eligible_athlete_count"] == 3

    for other in ({"passed": True, "outcome": "complete"}, {"passed": False, "outcome": "failed"}, {"passed": True}):
        calls.clear()
        assert recorder.record_partial_outcome(other, result_path="r.json", marker=lambda **f: calls.append(f)) is False
        assert calls == []

    def boom(**_fields: Any) -> None:
        raise RuntimeError("supabase down")

    assert recorder.record_partial_outcome(result, result_path="r.json", marker=boom) is False  # never fails the run
    # A failing gate is still propagated as a failed run.
    failed: list[dict[str, Any]] = []
    assert recorder.record_gate_failure({"passed": False, "errors": ["x"]}, result_path="r.json",
                                        marker=lambda **f: failed.append(f)) is True
    assert failed[0]["status"] == "failed" and failed[0]["stage"] == "publishable_business_gate_failed"
    assert recorder.record_gate_failure({"passed": True, "outcome": "partial"}, result_path="r.json",
                                        marker=lambda **f: failed.append(f)) is False


def test_production_wrapper_defaults_to_partial_and_annotates() -> None:
    assert 'export PUBLISHABLE_GATE_MODE="${PUBLISHABLE_GATE_MODE:-partial}"' in WRAPPER
    assert WRAPPER.index("PUBLISHABLE_GATE_MODE") < WRAPPER.index("scripts/check_publishable_reel_manifest.py")
    assert ('[ "$STATUS" -eq 0 ] && [ "$BUSINESS_GATE_STATUS" -eq 0 ] && [ -f "$PUBLISHABLE_GATE_RESULT_FILE" ]'
            in WRAPPER)
    # The failure path is untouched.
    assert '[ "$STATUS" -eq 0 ] && [ "$BUSINESS_GATE_STATUS" -ne 0 ]' in WRAPPER


def test_diagnostics_show_what_was_withheld() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        debug = Path(tmp)
        (debug / "publishable_reel_gate_result.json").write_text(json.dumps({
            "passed": True, "outcome": "partial", "mode": "partial", "errors": [],
            "publishable_athlete_count": 2, "eligible_athlete_count": 3, "published_part_count": 2,
            "qa_gaps": ["athlete B: Part 1 did not pass final QA", "athlete C: Part 2 did not pass final QA"],
        }), encoding="utf-8")
        text = "\n".join(diag.gate(debug))
    assert "outcome=partial" in text and "published_athletes=2/3" in text, text
    assert "withheld for QA (not failing the run): 2 finding(s)" in text, text


def main() -> int:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print(f"ok  {name}")
    print("Publishable partial gate contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
