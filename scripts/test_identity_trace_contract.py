#!/usr/bin/env python3
"""Identity trace + multi-crop identity evidence + the GT identity evaluator.

1. Every detected person is traced through model -> post_process -> compile, keyed source::person, and the key
   survives the copies identity layers make.
2. A person's identity image is a contact sheet of its own tracked boxes at several moments (real ffmpeg on a
   synthetic video); without track detections it falls back to the single crop-point thumbnail, and says so.
3. The evaluator scores B-cubed precision/recall per layer and names the layer where each pair went wrong.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="idtrace_"))
os.environ["TMP_DIR"] = str(TMP)


def _stub_gemini(cluster_response: dict, verify_response: dict) -> None:
    fake = types.ModuleType("integrations.gemini")

    class _File:
        def __init__(self, path):
            self.name = path

    class _Model:
        def __init__(self, model_name=""):
            self.model_name = model_name

        def generate_content(self, content, request_options=None):
            body = verify_response if "Verify this grouping" in str(content[-1]) else cluster_response
            return types.SimpleNamespace(text=json.dumps(body))

    fake.genai = types.SimpleNamespace(upload_file=lambda path, mime_type=None: _File(path),
                                       delete_file=lambda name: None, GenerativeModel=_Model)
    sys.modules["integrations.gemini"] = fake


def check_trace_through_clustering() -> None:
    import config
    config.TMP_DIR = str(TMP)
    _stub_gemini(
        {"clusters": [
            {"description": "red board", "confidence": "high",
             "appearances": [{"clip_index": 0, "person_id": "person_A"}, {"clip_index": 1, "person_id": "person_A"}]},
            {"description": "bystander", "confidence": "high", "appearances": [{"clip_index": 1, "person_id": "person_B"}]},
        ]},
        {"same_person": True, "mismatched_indices": []},
    )
    from pipeline import identity_trace
    from pipeline.stages import identity
    identity_trace.reset()
    clips = []
    for i, name in enumerate(["DJI_20260720160337_0094_D.MP4", "DJI_20260720162035_0118_D.MP4"]):
        persons = []
        for pid in (["person_A"] if i == 0 else ["person_A", "person_B"]):
            thumb = TMP / f"t_{i}_{pid}.jpg"
            thumb.write_bytes(b"jpg")
            person = {"id": pid, "description": "surfer", "thumbnail": str(thumb),
                      "events": [{"type": "wave_ride", "start": 1.0, "end": 8.0, "score": 8, "target_track_id": "3"}]}
            persons.append(identity_trace.stamp_person(person, f"/tmp/raw/{name}"))
        clips.append({"path": f"/tmp/raw/{name}", "analysis": {"persons": persons}})
    clusters = identity.cluster_clips(clips)
    trace = identity_trace.snapshot()
    keys = set(trace["persons"])
    assert keys == {"DJI_20260720160337_0094_D.MP4::person_A", "DJI_20260720162035_0118_D.MP4::person_A",
                    "DJI_20260720162035_0118_D.MP4::person_B"}, keys
    assert set(trace["layers"]) == {"model", "post_process"}, trace["layers"].keys()
    together = [r["members"] for r in trace["layers"]["post_process"] if len(r["members"]) == 2]
    assert together == [["DJI_20260720160337_0094_D.MP4::person_A", "DJI_20260720162035_0118_D.MP4::person_A"]], together
    # keys survive into what the compiler receives
    identity_trace.record_layer("compile", [{**c, "appearances": [{**a} for a in c["appearances"]]} for c in clusters])
    trace = identity_trace.snapshot()
    assert [r["members"] for r in trace["layers"]["compile"]] == [r["members"] for r in trace["layers"]["post_process"]]
    assert json.loads((TMP / "identity_trace.json").read_text())["schema"] == identity_trace.SCHEMA
    lines = identity_trace.compact_lines(trace)
    assert len(lines) == 3 and "model=0 post_process=0 compile=0" in lines[0], lines


def _video(path: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30",
                    "-t", "6", "-pix_fmt", "yuv420p", str(path)], check=True)


def check_identity_sheet() -> None:
    import config
    config.TMP_DIR = str(TMP)
    from PIL import Image
    from pipeline import runtime_quality as rq
    from pipeline.perception.schema import PerceptionDetection
    video = TMP / "DJI_20260720160337_0094_D.MP4"
    _video(video)
    dets = [PerceptionDetection(source_video=str(video), frame_index=int(t * 30), time_sec=t,
                                xyxy=(800 + 20 * t, 400, 900 + 20 * t, 560), frame_width=1920, frame_height=1080,
                                confidence=0.9, class_id=0, class_name="person", tracker_id=7)
            for t in [0.5 * i for i in range(1, 12)]]
    other = [PerceptionDetection(source_video=str(video), frame_index=30, time_sec=1.0, xyxy=(10, 10, 60, 90),
                                 frame_width=1920, frame_height=1080, confidence=0.9, tracker_id=9)]
    person = {"id": "person_A", "events": [
        {"type": "wave_ride", "start": 0.5, "end": 2.6, "score": 8, "target_track_id": "7", "crop_x": 0.45, "crop_y": 0.45},
        {"type": "wave_ride", "start": 3.0, "end": 5.6, "score": 7, "target_track_id": "7", "crop_x": 0.47, "crop_y": 0.45}]}
    picks = rq._track_samples(person["events"], dets + other, 4)
    assert len(picks) == 4 and all(d.tracker_id == 7 for d in picks), picks
    assert picks == sorted(picks, key=lambda d: d.time_sec) and picks[-1].time_sec - picks[0].time_sec >= 3.0
    x, y, w, h = rq._crop_box(picks[0])
    assert abs(w * 1920 - h * 1080) < 1e-6 and 0 <= x and x + w <= 1 + 1e-9 and 0 <= y and y + h <= 1 + 1e-9
    hardened = rq._harden_person(str(video), person, dets + other)
    ev = hardened["identity_evidence"]
    assert ev["kind"] == "track_bbox_sheet" and ev["crops"] == 4 and ev["track_ids"] == ["7"], ev
    with Image.open(hardened["thumbnail"]) as im:
        assert im.size == (2 * rq._SHEET_TILE + 8, 2 * rq._SHEET_TILE + 8), im.size
    assert all(e["source_person_key"] == "DJI_20260720160337_0094_D.MP4::person_A" for e in hardened["events"])
    assert not list(TMP.glob("identity_crop_*")), "per-crop temp files must be removed"
    # no track evidence: the old single crop-point thumbnail, recorded as such
    fallback = rq._harden_person(str(video), {**person, "id": "person_B"}, other)
    assert fallback["identity_evidence"]["kind"] == "crop_point_thumbnail", fallback["identity_evidence"]
    assert fallback["identity_evidence"]["sheet_unavailable"] == "no_track_detections"
    os.environ["SPORTREEL_IDENTITY_CROPS"] = "0"
    try:
        off = rq._harden_person(str(video), {**person, "id": "person_C"}, dets)
        assert off["identity_evidence"]["sheet_unavailable"] == "disabled"
    finally:
        os.environ.pop("SPORTREEL_IDENTITY_CROPS")


def check_production_hardening_builds_sheet() -> None:
    """The hardening that production actually runs must build the contact sheet too.

    `performance_reel_policy.install()` replaces `runtime_quality._harden_session_result` (bootstrap order:
    runtime_quality, then performance_reel_policy). Its replacement built one crop-point thumbnail, so run
    42891165218 clustered every person from a single frame (trace: evidence=crop_point_thumbnailx1 for 23/23)
    and split one surfer into two athletes (0097 / 0115). The base-path check above passed all along.
    """
    import config
    config.TMP_DIR = str(TMP)
    gemini = sys.modules["integrations.gemini"]  # the stub above; the analyzer imports two more names from it
    gemini.upload_video = getattr(gemini, "upload_video", lambda path: path)
    gemini.delete_video = getattr(gemini, "delete_video", lambda item: None)
    from pipeline import performance_reel_policy, runtime_quality as rq
    from pipeline.perception.schema import PerceptionDetection
    rq.install()
    performance_reel_policy.install()
    video = TMP / "DJI_20260720161907_0115_D.MP4"
    _video(video)
    dets = [PerceptionDetection(source_video=str(video), frame_index=int(t * 30), time_sec=t,
                                xyxy=(800 + 20 * t, 400, 900 + 20 * t, 560), frame_width=1920, frame_height=1080,
                                confidence=0.9, class_id=0, class_name="person", tracker_id=3)
            for t in [0.5 * i for i in range(1, 12)]]
    original_load = rq._load_detections
    rq._load_detections = lambda _path: dets
    try:
        result = {"activity": "surfing", "persons": [
            {"id": "person_A", "description": "surfer in dark shorts on a light blue longboard", "events": [
                {"type": "wave_catch", "description": "rides a wave down the line", "start": 0.5, "end": 5.6,
                 "score": 8, "target_track_id": "3", "crop_x": 0.45, "crop_y": 0.45}]},
            {"id": "person_B", "description": "surfer far away", "events": [
                {"type": "wave_catch", "description": "rides a wave", "start": 0.5, "end": 5.6, "score": 8,
                 "crop_x": 0.2, "crop_y": 0.5}]}]}
        hardened = rq._harden_session_result(str(video), result)
    finally:
        rq._load_detections = original_load
    people = {p["id"]: p for p in hardened["persons"]}
    assert people["person_A"]["events"], "the tracked person's ride must survive the performance filter"
    ev = people["person_A"].get("identity_evidence") or {}
    assert ev.get("kind") == "track_bbox_sheet" and ev.get("crops") == 4 and ev.get("track_ids") == ["3"], (
        f"production hardening must build the tracked contact sheet, got {ev}")
    assert os.path.exists(people["person_A"]["thumbnail"]), "the sheet is the person's identity image"
    if people["person_B"]["events"]:
        fallback = people["person_B"].get("identity_evidence") or {}
        assert fallback.get("kind") == "crop_point_thumbnail" and fallback.get("sheet_unavailable") == "no_track_detections", fallback


def check_evaluator() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import eval_identity_trace as ev
    gt = {"athletes": {"A": "red", "B": "black"}, "sources": [
        {"name": "x_DJI_1_0001_D.MP4", "split": "train", "segments": [{"start_sec": 0, "end_sec": 10, "athlete": "A"}]},
        {"name": "x_DJI_1_0002_D.MP4", "split": "train", "segments": [{"start_sec": 0, "end_sec": 10, "athlete": "A"}]},
        {"name": "x_DJI_1_0003_D.MP4", "split": "train", "segments": [{"start_sec": 0, "end_sec": 10, "athlete": "B"}]},
        {"name": "x_DJI_1_0004_D.MP4", "split": "train", "segments": [{"start_sec": 0, "end_sec": 9, "athlete": "B"}]}]}
    k = lambda n, p="person_A": f"DJI_1_000{n}_D.MP4::{p}"
    persons = {k(i): {"source": f"DJI_1_000{i}_D.MP4", "windows": [[1, 8]]} for i in (1, 2, 3, 4)}
    persons[k(3, "person_B")] = {"source": "DJI_1_0003_D.MP4", "windows": [[12, 15]]}  # outside every segment
    trace = {"persons": persons, "layers": {
        # model: A correct, B correct
        "model": [{"cluster": 0, "members": [k(1), k(2)]}, {"cluster": 1, "members": [k(3), k(4)]},
                  {"cluster": 2, "members": [k(3, "person_B")]}],
        # verifier splits A; wrongly joins 4 into ... keeps B
        "post_process": [{"cluster": 0, "members": [k(1)]}, {"cluster": 1, "members": [k(2)]},
                         {"cluster": 2, "members": [k(3), k(4)]}, {"cluster": 3, "members": [k(3, "person_B")]}],
        # gate merges A back, but mixes 4 into A
        "compile": [{"cluster": 0, "members": [k(1), k(2), k(4)]}, {"cluster": 1, "members": [k(3)]},
                    {"cluster": 2, "members": [k(3, "person_B")]}]}}
    report = ev.evaluate(trace, gt)
    assert report["attributed_persons"] == 4 and report["unattributed_persons"] == [k(3, "person_B")], report
    assert report["layers"]["model"]["bcubed_precision"] == 1.0 and report["layers"]["model"]["bcubed_recall"] == 1.0
    assert report["layers"]["post_process"]["bcubed_recall"] == 0.75 and report["layers"]["post_process"]["fragmented_athletes"] == {"red": 2}
    assert report["layers"]["compile"]["mixed_clusters"] == {"0": ["black", "red"]}
    counts = report["pair_error_counts"]
    assert counts["missed_merge@compile"] == 1 and counts["false_merge@compile"] == 2, counts
    assert counts["missed_merge@post_process"] == 0, "the A split was undone later, so it is not a final error"
    # the log form is accepted
    log = TMP / "job.log"
    log.write_text("noise\n2026-11-07T10:00:00Z IDTRACE_JSON " + json.dumps(trace) + "\n", encoding="utf-8")
    assert ev.load_trace(log) == trace
    # the test split is refused
    gt_path = TMP / "gt.json"
    gt_path.write_text(json.dumps(gt))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/eval_identity_trace.py"), str(log), str(gt_path), "--splits", "test"],
                          capture_output=True, text=True)
    assert proc.returncode == 2, proc


def main() -> int:
    check_trace_through_clustering()
    check_identity_sheet()
    check_production_hardening_builds_sheet()
    check_evaluator()
    print("identity trace contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
