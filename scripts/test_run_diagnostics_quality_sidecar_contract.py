#!/usr/bin/env python3
"""Contract: the run digest explains the quality report and why a source's analysis failed.

Fixtures are the real thing: the `Analysis failed ... RuntimeError: Perception producer did not create a reusable
sidecar: status=ok reason=None` lines of run 39726001357 (five sources, one per run of this kind, dropped after three
tries), and a quality report with the fields scripts/generate_run_quality_report.py writes. The sidecar generator now
records what the detector saw, so a rejected "status=ok, 0 detections" sidecar says whether anything person-like was
seen at all or the tracker simply never confirmed a track.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location("print_run_diagnostics", ROOT / "scripts" / "print_run_diagnostics.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

import pipeline.perception.runtime as rt  # noqa: E402

REAL_LOG = """\
2026-10-22T05:33:08.5678412Z ⏱️  analyze_source took 72.0s source=2026-10-04T07-38-33_DJI_20260724103751_0165_D.MP4
2026-10-22T05:33:14.6016939Z ⏱️  analyze_source took 9.9s source=2026-10-21T07-12-45_b6j0lx_1000000018.mp4
2026-10-22T05:33:14.6103102Z Analysis failed for 2026-10-21T07-12-45_b6j0lx_1000000018.mp4 — will retry
2026-10-22T05:33:14.6132433Z Traceback (most recent call last):
2026-10-22T05:33:14.6169591Z   File "pipeline/orchestrator.py", line 659, in _analyze_one_source
2026-10-22T05:33:14.6170358Z     analysis = analyze_session(item["path"])
2026-10-22T05:33:14.6181684Z   File "pipeline/perception/runtime.py", line 295, in ensure_sidecar_for_video
2026-10-22T05:33:14.6182556Z     raise RuntimeError(_non_reusable_error(summary))
2026-10-22T05:33:14.6183106Z RuntimeError: Perception producer did not create a reusable sidecar: status=ok reason=None
2026-10-22T05:33:24.3300595Z Analysis failed for 2026-10-21T07-17-50_ktz4rx_1000000016.mp4 — will retry
2026-10-22T05:33:24.3359138Z Traceback (most recent call last):
2026-10-22T05:33:24.3569941Z RuntimeError: Perception producer did not create a reusable sidecar: status=ok reason=None
2026-10-22T05:33:28.7061268Z Analysis failed for 2026-10-21T07-17-50_unvbj2_1000000018.mp4 — will retry
2026-10-22T05:33:28.7912431Z RuntimeError: Perception producer did not create a reusable sidecar: status=ok reason=None
2026-10-22T05:33:30.0000000Z Analysis failed for 2026-10-16T15-04-52_1000000016.mp4 — will retry
2026-10-22T05:33:30.1000000Z Traceback (most recent call last):
2026-10-22T05:33:31.0000000Z Analysis failed for 2026-10-20T19-03-05_1000000018.mp4 — will retry
2026-10-22T05:33:31.5000000Z   File "x.py", line 1, in f
2026-10-22T05:33:31.9000000Z ValueError: invalid literal for int()
"""

REPORT = {
    "status": "fail",
    "alerts": [{"metric": "mixed_subject_violation_rate", "severity": "hard_block", "reason": "multiple tracks"}],
    "bug_classifications": [{"code": "BUG_MIXED_SUBJECT_LIKELY", "evidence": "1 window"}],
    "mixed_subject_likely_windows": [{"draft": "DRAFT_a.mp4", "primary_track_id": "7", "primary_track_dominance_ratio": 0.4}],
    "duplicate_athlete_likely_drafts": [{"athlete_id": "athlete_9", "draft_ids": ["DRAFT_a.mp4", "DRAFT_b.mp4"]}],
    "source_window_overlap_duplicates": [{"left_draft": "DRAFT_a.mp4", "right_draft": "DRAFT_c.mp4",
                                          "overlap_seconds": 4.5, "overlap_ratio_of_shorter": 0.75}],
    "track_fragmentation": {"track_count": 40, "short_track_count": 22, "short_track_rate": 0.55, "short_track_threshold_sec": 2.0},
    "sidecar_schema_errors": ["clip_1.perception.json: detections must be a list"],
    "implementation_gaps": {"candidate_decision_ledger_present": True, "dropped_reasons_present": False},
}


def _debug(files: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for name, text in files.items():
        (tmp / name).write_text(text, encoding="utf-8")
    return tmp


def test_quality_report_prints_alerts_bugs_and_every_kind_of_violation() -> None:
    text = "\n".join(diag.run_quality(_debug({"run_quality_report.json": json.dumps(REPORT)})))
    for needle in (
        "status=fail alerts=1 bugs=1", "mixed_subject_violation_rate", "BUG_MIXED_SUBJECT_LIKELY",
        "violations (1 mixed-subject):", "primary_track=7",
        "violations (1 same athlete in drafts built from different source pools):", "athlete_9",
        "violations (1 overlapping source windows in different drafts):", "overlap=4.5s",
        "tracks=40 short(<2.0s)=22", "sidecar schema errors (1):", "detections must be a list",
        "evidence the report could not find: dropped_reasons_present",
    ):
        assert needle in text, (needle, text)


def test_quality_report_degrades_gracefully() -> None:
    assert diag.run_quality(_debug({})) == ["(no run_quality_report.json)"]
    assert diag.run_quality(_debug({"run_quality_report.json": "garbage"})) == ["(no run_quality_report.json)"]
    minimal = diag.run_quality(_debug({"run_quality_report.json": json.dumps({"status": "pass"})}))
    assert minimal == ["status=pass alerts=0 bugs=0"], minimal


def test_analysis_failures_group_the_real_run_by_reason() -> None:
    lines = diag.analysis_failures(_debug({"run_tracked.log": REAL_LOG}))
    text = "\n".join(lines)
    assert lines[0].startswith("5 source(s) failed analysis; 3 distinct reason(s):"), lines[0]
    assert "3 x RuntimeError: Perception producer did not create a reusable sidecar: status=ok reason=None" in text
    assert "1 x ValueError: invalid literal for int()" in text
    assert "(no exception line found after the failure)" in text, "a failure whose traceback is missing says so"
    assert "2026-10-21T07-12-45_b6j0lx_1000000018.mp4" in text
    # A failure must not borrow the exception that belongs to the next failure.
    own = next(l for l in lines if "2026-10-16T15-04-52_1000000016.mp4" in l)
    assert "no exception line" in own, own


def test_analysis_failures_degrade_gracefully() -> None:
    assert diag.analysis_failures(_debug({})) == ["(no run_tracked.log)"]
    assert diag.analysis_failures(_debug({"run_tracked.log": "all good\n"})) == ["(no analysis failures)"]


def test_sections_are_registered() -> None:
    names = [name for name, _fn in diag.SECTIONS]
    assert "Run quality report" in names and "Source analysis failures" in names


# --- detector-side counters -------------------------------------------------------------------------------


def _result(*, tracked: bool, boxes: int, conf: float = 0.41) -> SimpleNamespace:
    return SimpleNamespace(
        boxes=SimpleNamespace(
            is_track=tracked,
            id=[7] * boxes if tracked else None,
            xyxy=[[10.0, 20.0, 60.0, 160.0]] * boxes,
            conf=[conf] * boxes,
            cls=[0] * boxes,
        ),
        names={0: "person"},
        orig_shape=(1920, 1080),
        path="clip.mp4",
    )


def _generate(results: list[SimpleNamespace]) -> dict:
    fake = types.ModuleType("ultralytics")

    class YOLO:  # noqa: D401 - test double
        def __init__(self, _model: str) -> None:
            pass

        def track(self, **_kwargs):
            yield from results

    fake.YOLO = YOLO
    sys.modules["ultralytics"] = fake
    try:
        import generate_perception_sidecar as gen

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip.perception.json"
            args = SimpleNamespace(
                video_path=str(Path(tmp) / "clip.mp4"), output_path=str(out), ultralytics_model="yolo-test.pt",
                ultralytics_tracker=None, ultralytics_vid_stride=None, ultralytics_imgsz=None,
                ultralytics_device=None, fps="30",
            )
            gen._fast_ultralytics_sidecar(args)
            payload = json.loads(out.read_text(encoding="utf-8"))
            return {"payload": payload, "summary": rt.validate_sidecar(args.video_path, out)}
    finally:
        sys.modules.pop("ultralytics", None)


def test_sidecar_records_what_the_detector_saw() -> None:
    tracked = _generate([_result(tracked=True, boxes=1, conf=0.9)] * 3)
    assert tracked["summary"]["detection_count"] == 3 and tracked["summary"]["raw_person_boxes"] == 3
    assert tracked["summary"]["frames_processed"] == 3 and tracked["summary"]["max_person_confidence"] == 0.9
    assert (tracked["summary"]["frame_width"], tracked["summary"]["frame_height"]) == (1080, 1920)

    untracked = _generate([_result(tracked=False, boxes=2, conf=0.41)] * 4)
    assert untracked["summary"]["detection_count"] == 0
    assert untracked["summary"]["raw_person_boxes"] == 8 and untracked["summary"]["frames_processed"] == 4
    message = rt._non_reusable_error(untracked["summary"])
    assert message.startswith("Perception producer did not create a reusable sidecar: status=ok reason=None"), message
    assert "raw_person_boxes=8" in message and "max_person_confidence=0.41" in message, message
    assert "persons were detected but the tracker never confirmed a track" in message, message

    empty = _generate([_result(tracked=False, boxes=0)] * 5)
    message = rt._non_reusable_error(empty["summary"])
    assert "raw_person_boxes=0" in message and "frames_processed=5" in message, message
    assert "no person-like detection in any sampled frame" in message, message

    nothing_decoded = _generate([])
    assert "frames_processed=0" in rt._non_reusable_error(nothing_decoded["summary"])


def test_legacy_sidecars_keep_the_original_message() -> None:
    legacy = {"status": "ok", "reason": None, "detection_count": 0}
    assert rt._non_reusable_error(legacy) == (
        "Perception producer did not create a reusable sidecar: status=ok reason=None"
    )
    assert rt._non_reusable_error({"status": "skipped", "reason": "x"}).endswith("status=skipped reason=x")


def main() -> int:
    os.environ.pop("SPORTREEL_PERCEPTION_MIN_CONFIDENCE", None)
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print(f"ok  {name}")
    print("Run diagnostics quality/sidecar contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
