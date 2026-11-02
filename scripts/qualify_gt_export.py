#!/usr/bin/env python3
"""Phase B qualification fixture generator (SYNTHETIC footage only; no network, no storage, no credentials).

Drives the REAL production render path (framing.install(); editor.cut_clip; editor.compile_reel) on three synthetic 4K
sources with analytically known athlete positions, with EDL export enabled, then writes the candidate ledger and the
predictions/v1 export. Output directory layout:

  OUT/sources/{srcA,srcB,srcC}.mp4       source footage (what would be uploaded)
  OUT/outputs/reel1.mp4, reel2.mp4       real rendered reels
  OUT/pipeline-debug/edl/*.edl.json      EDL export
  OUT/predictions.v1.json                prediction export
  OUT/truth.json                         the analytic truth the evaluator should be able to recover

Scenarios
  srcA  one athlete crosses the frame  -> follow crop (tracked)          [reel1 shot 1]
  srcB  large central athlete (follow-crop kill switch) -> contain   [reel1 shot 2]
  srcC  two athletes; the pipeline tracks athlete #1, the operator-truth featured athlete is #2 (decoy)   [reel2]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ("GEMINI_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "RAW_FOLDER_ID", "PROCESSED_FOLDER_ID",
            "REVIEW_FOLDER_ID", "APPROVED_FOLDER_ID", "OWNER_EMAIL"):
    os.environ.setdefault(key, "fixture-not-used")

FPS = 30
SECONDS = 4.0
SIZE = 120


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def make_source(path: Path, squares: list[dict], tag: str) -> None:
    """squares: [{x0, vx, y, size}] white squares on black, x(t) = x0 + vx*t (px/s)."""
    inputs, chain, last = [], "", "[0:v]"
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=3840x2160:r={FPS}:d={SECONDS}"]
    for i, sq in enumerate(squares, start=1):
        cmd += ["-f", "lavfi", "-i", f"color=c=white:s={sq['size']}x{sq['size']}:r={FPS}:d={SECONDS}"]
        out = f"[v{i}]"
        chain += f"{last}[{i}:v]overlay=x='{sq['x0']}+({sq['vx']})*t':y={sq['y']}:eval=frame{out};"
        last = out
    cmd += ["-filter_complex", chain.rstrip(";"), "-map", last, "-metadata", f"title={tag}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", str(path)]
    run(cmd)


def write_sidecar(video: Path, sq: dict, track_id: int = 7, step: float = 0.2) -> None:
    dets, t = [], 0.0
    while t <= SECONDS + 1e-9:
        x1 = sq["x0"] + sq["vx"] * t
        dets.append({"time_sec": round(t, 3), "frame_index": int(round(t * FPS)),
                     "bbox_xyxy": [x1, sq["y"], x1 + sq["size"], sq["y"] + sq["size"]], "frame_width": 3840, "frame_height": 2160,
                     "confidence": 0.9, "visible_ratio": 1.0, "class_id": 0, "class_name": "athlete", "track_id": track_id})
        t += step
    video.with_suffix(video.suffix + ".perception.json").write_text(
        json.dumps({"source_video": str(video), "status": "ok", "detections": dets}))


def event(video: Path, sq: dict, eid: str, athlete: str) -> dict:
    x1 = sq["x0"]
    return {"type": "surf_ride", "sport": "surfing", "start": 0.0, "end": SECONDS, "event_id": eid, "athlete_id": athlete,
            "perception_evidence_status": "tracker_sidecar", "track_id": 7,
            "bbox_xyxy": [x1, sq["y"], x1 + sq["size"], sq["y"] + sq["size"]],
            "perception_frame_width": 3840, "perception_frame_height": 2160, "perception_confidence": 0.9,
            "visible_ratio": 1.0, "visible_track_ids": [7], "source_video": video.name}


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "sources").mkdir(exist_ok=True)
    (out / "outputs").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="gt-qual-"))
    os.environ["TMP_DIR"] = str(work)
    os.environ["SPORTREEL_EXPORT_EDL"] = "1"
    os.environ["PIPELINE_RUN_ID"] = "qual-run-001"
    os.environ["SPORTREEL_COMMIT"] = "0123456789abcdef0123456789abcdef01234567"

    sqA = {"x0": 400, "vx": 500, "y": 1020, "size": SIZE}
    sqB = {"x0": 1650, "vx": 60, "y": 800, "size": 460}
    sqC1 = {"x0": 400, "vx": 500, "y": 1020, "size": SIZE}          # tracked by the pipeline
    sqC2 = {"x0": 3000, "vx": -400, "y": 300, "size": SIZE}          # the operator-truth featured athlete
    srcs = {"srcA": [sqA], "srcB": [sqB], "srcC": [sqC1, sqC2]}
    for name, squares in srcs.items():
        make_source(out / "sources" / f"{name}.mp4", squares, tag=name)
    write_sidecar(out / "sources" / "srcA.mp4", sqA)
    write_sidecar(out / "sources" / "srcC.mp4", sqC1)
    # srcB has no moving track need: a stationary-ish athlete with a sidecar track so decide_framing has evidence
    write_sidecar(out / "sources" / "srcB.mp4", sqB)

    import pipeline.edl_export as edl_export
    import pipeline.quality_preserving_framing as framing
    from pipeline.stages import editor

    framing.install()
    edl_export.reset_for_tests()

    events = {"srcA": event(out / "sources" / "srcA.mp4", sqA, "evA", "athlete-A"),
              "srcB": event(out / "sources" / "srcB.mp4", sqB, "evB", "athlete-B"),
              "srcC": event(out / "sources" / "srcC.mp4", sqC1, "evC", "athlete-C")}
    events["srcB"]["bbox_xyxy"] = [sqB["x0"], sqB["y"], sqB["x0"] + sqB["size"], sqB["y"] + sqB["size"]]
    clips = {}
    for i, name in enumerate(("srcA", "srcB", "srcC")):
        # srcB uses the pipeline's own kill switch so the contain path is exercised alongside follow-crop.
        if name == "srcB":
            os.environ["SPORTREEL_FOLLOW_CROP"] = "0"
        clip = editor.cut_clip(str(out / "sources" / f"{name}.mp4"), events[name], i, False, "surfing", {}, 10, 30)
        os.environ.pop("SPORTREEL_FOLLOW_CROP", None)
        assert clip, f"render failed for {name}"
        clips[name] = clip
    reel1 = editor.compile_reel([clips["srcA"], clips["srcB"]], "", str(out / "outputs" / "reel1.mp4"), sport="surfing",
                                transitions=["fade", "fade"], fps=FPS)
    reel2 = editor.compile_reel([clips["srcC"]], "", str(out / "outputs" / "reel2.mp4"), sport="surfing", transitions=["fade"], fps=FPS)
    assert reel1 and reel2, "compile failed"

    edl_dir = out / "pipeline-debug" / "edl"
    edl_dir.mkdir(parents=True, exist_ok=True)
    for p in (work / "pipeline-debug" / "edl").glob("*.edl.json"):
        (edl_dir / p.name).write_text(p.read_text())

    # candidate ledger through the real builder (selected + one discarded candidate with a cause)
    import importlib.util
    spec = importlib.util.spec_from_file_location("ledger_builder", ROOT / "scripts" / "build_candidate_decision_ledger.py")
    lb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lb)
    windows = lambda name, pid: {"source_video": f"{name}.mp4", "start": 0.0, "end": SECONDS, "event_type": "surf_ride", "score": 8.0}
    trace = {"schema_version": "sportreel.draft_decision_trace.v1", "drafts": [
        {"draft_id": "reel1", "draft_name": "reel1", "person_id": "pA", "athlete_id": "athlete-A", "source_windows": [windows("srcA", "pA")]},
        {"draft_id": "reel1b", "draft_name": "reel1", "person_id": "pB", "athlete_id": "athlete-B", "source_windows": [windows("srcB", "pB")]},
        {"draft_id": "reel2", "draft_name": "reel2", "person_id": "pC", "athlete_id": "athlete-C", "source_windows": [windows("srcC", "pC")]}]}
    upstream = {"schema_version": "x", "candidates": [
        {"candidate_id": "rej1", "person_id": "pC2", "athlete_id": "athlete-D", "selected": False, "discarded": True, "discard_cause": "failed_takeoff",
         "event_type": "surf_ride", "source_video": "srcA.mp4", "source_window": {"start": 3.5, "end": 3.9}}]}
    (work / "trace.json").write_text(json.dumps(trace))
    (work / "up.json").write_text(json.dumps(upstream))
    ledger = lb.build_ledger(work / "trace.json", work / "up.json")
    (out / "candidate_decision_ledger.json").write_text(json.dumps(ledger, indent=2))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_pipeline_predictions.py"), str(out / "candidate_decision_ledger.json"),
                    str(edl_dir), str(out / "predictions.v1.json")], check=True, env=os.environ)

    truth = {"fps": FPS, "frames": int(SECONDS * FPS), "sources": {
        "srcA": {"squares": [sqA], "featured": 0}, "srcB": {"squares": [sqB], "featured": 0}, "srcC": {"squares": [sqC1, sqC2], "featured": 1}},
        "reels": {"reel1": ["srcA", "srcB"], "reel2": ["srcC"]}}
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    print(json.dumps({"out": str(out), "edls": sorted(p.name for p in edl_dir.glob('*.edl.json'))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
