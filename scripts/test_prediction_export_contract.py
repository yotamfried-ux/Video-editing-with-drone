#!/usr/bin/env python3
"""Prediction export contract (predictions/v1), driven by the *real* candidate-ledger builder."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.prediction_export import PREDICTIONS_SCHEMA, build_predictions, validate_predictions  # noqa: E402

spec = importlib.util.spec_from_file_location("ledger_builder", ROOT / "scripts" / "build_candidate_decision_ledger.py")
ledger_builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger_builder)

SHA_A, SHA_B = "a" * 64, "b" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def make_ledger(tmp: Path) -> dict:
    trace = {"schema_version": "sportreel.draft_decision_trace.v1", "drafts": [{
        "draft_id": "draft1", "draft_name": "reel_A", "person_id": "p1", "athlete_id": "ath-1",
        "source_windows": [{"source_video": "DJI_0001.mp4", "start": 10.0, "end": 25.5, "event_type": "surf_ride", "score": 8.2}]}]}
    upstream = {"schema_version": "x", "candidates": [
        {"candidate_id": "u1", "person_id": "p1", "athlete_id": "ath-1", "selected": True, "discarded": False,
         "event_type": "surf_ride", "source_video": "DJI_0001.mp4", "source_window": {"start": 10.0, "end": 25.5}},
        {"candidate_id": "u2", "person_id": "p2", "athlete_id": "ath-2", "selected": False, "discarded": True,
         "discard_cause": "failed_takeoff", "event_type": "surf_ride", "source_video": "DJI_0001.mp4",
         "source_window": {"start": 40.0, "end": 48.0}},
        {"candidate_id": "u3", "person_id": "p3", "selected": False, "discarded": True, "discard_cause": "duplicate",
         "event_type": "surf_ride", "source_video": "NEVER_RENDERED.mp4", "source_window": {"start": 1.0, "end": 4.0}}]}
    (tmp / "trace.json").write_text(json.dumps(trace))
    (tmp / "up.json").write_text(json.dumps(upstream))
    return ledger_builder.build_ledger(tmp / "trace.json", tmp / "up.json")


def make_edl() -> dict:
    return {"schema": "edl/v1", "output_id": "reel_A", "pipeline_commit": COMMIT, "mapping": "edl",
            "output": {"width": 2160, "height": 3840, "fps": 30},
            "shots": [{"out_start": 0, "out_end": 465, "src_start": 300, "speed": 1.0, "mode": "tracked_crop",
                       "source_file": "DJI_0001.mp4", "source_sha256": SHA_A, "event_id": "e1", "track_id": "7",
                       "source": {"width": 3840, "height": 2160, "fps": 30.0},
                       "subject_track": [{"src_frame": 300, "bbox": {"x": 0.1, "y": 0.4, "w": 0.03, "h": 0.05}},
                                         {"src_frame": 310, "bbox": {"x": 0.12, "y": 0.4, "w": 0.03, "h": 0.05}}]}]}


def test_export_maps_ledger_and_edl_with_lineage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = make_ledger(Path(tmp))
        out = build_predictions(ledger, [make_edl()], run_id="run-42", commit=COMMIT)
        assert out["schema"] == PREDICTIONS_SCHEMA and out["run_id"] == "run-42" and out["pipeline_commit"] == COMMIT
        assert validate_predictions(out) == [], validate_predictions(out)
        src = next(s for s in out["sources"] if s["source_sha256"] == SHA_A)
        sel = next(e for e in src["events"] if e["decision"] == "selected")
        assert (sel["start_frame"], sel["end_frame"]) == (300, 765), "10.0s..25.5s @30fps, half-open"
        assert sel["athlete_key"] == "ath-1" and sel["outputs"][0]["output_id"] == "reel_A"
        rej = next(e for e in src["events"] if e["decision"] == "rejected")
        assert rej["reason"] == "failed_takeoff" and rej["outputs"] == [], "rejection reason kept; no output lineage"
        assert src["tracks"] == [{"track_id": "7", "samples": make_edl()["shots"][0]["subject_track"]}]
        assert any(u["source_video"] == "NEVER_RENDERED.mp4" and u["reason"] == "source_sha256_unknown" for u in out["unresolved"])


def test_extra_source_hashes_resolve_rejected_only_sources() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = build_predictions(make_ledger(Path(tmp)), [make_edl()], run_id="r", commit=COMMIT,
                                source_hashes={"NEVER_RENDERED.mp4": {"sha256": SHA_B, "fps": 25.0}})
        extra = next(s for s in out["sources"] if s["source_sha256"] == SHA_B)
        assert extra["events"][0]["decision"] == "rejected" and extra["events"][0]["start_frame"] == 25
        assert not out["unresolved"]


def test_export_is_deterministic_and_traceable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = make_ledger(Path(tmp))
        a = build_predictions(ledger, [make_edl()], run_id="r", commit=COMMIT)
        b = build_predictions(json.loads(json.dumps(ledger)), [make_edl()], run_id="r", commit=COMMIT)
        assert a["digest"] == b["digest"]
        c = build_predictions(ledger, [make_edl()], run_id="r", commit="f" * 40)
        assert c["digest"] != a["digest"], "digest covers the code commit"
        assert validate_predictions(build_predictions(ledger, [], run_id=None, commit=None)) == ["run_id_unknown", "pipeline_commit_unknown"]


def test_invalid_windows_are_reported_not_dropped_silently() -> None:
    ledger = {"candidates": [{"candidate_id": "x", "selected": True, "source_video": "DJI_0001.mp4", "source_window": {"start": 5, "end": 5}},
                             {"candidate_id": "y", "selected": True, "source_window": {"start": 1, "end": 2}}]}
    out = build_predictions(ledger, [make_edl()], run_id="r", commit=COMMIT)
    assert [u["reason"] for u in out["unresolved"]] == ["missing_source_or_window"] * 2 and not out["sources"]


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} prediction export contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
