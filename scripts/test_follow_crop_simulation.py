#!/usr/bin/env python3
"""Simulation: the 9:16 window follows a moving athlete, with real ffmpeg on a 3840x2160 source.

A white square crosses a black 4K frame left to right with a matching tracker sidecar. Contain framing
leaves it a small moving dot in a letterboxed canvas; follow_crop must keep it large and near the centre
of a full-height 2160x3840 frame, and must fall back to contain when the track cannot support a pan.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.quality_preserving_framing as framing  # noqa: E402
from pipeline.stages import editor  # noqa: E402

SIZE = 120
DURATION = 6.0


def make_source(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s=3840x2160:r=30:d={DURATION}",
         "-f", "lavfi", "-i", f"color=c=white:s={SIZE}x{SIZE}:r=30:d={DURATION}",
         "-filter_complex", "[0:v][1:v]overlay=x='400+500*t':y=1020:eval=frame",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
        check=True)


def square_x(t: float) -> float:
    return 400 + 500 * t


def write_sidecar(video: Path, times: list[float], confidence: float = 0.9) -> None:
    detections = []
    for t in times:
        x1 = square_x(t)
        detections.append({
            "time_sec": t, "frame_index": int(t * 30), "bbox_xyxy": [x1, 1020, x1 + SIZE, 1020 + SIZE],
            "frame_width": 3840, "frame_height": 2160, "confidence": confidence, "visible_ratio": 1.0,
            "class_id": 0, "class_name": "athlete", "track_id": 7})
    video.with_suffix(video.suffix + ".perception.json").write_text(
        json.dumps({"source_video": str(video), "status": "ok", "detections": detections}))


def event() -> dict:
    return {"type": "surf_ride", "sport": "surfing", "start": 0.0, "end": DURATION,
            "perception_evidence_status": "tracker_sidecar", "track_id": 7,
            "bbox_xyxy": [square_x(0), 1020, square_x(0) + SIZE, 1020 + SIZE],
            "perception_frame_width": 3840, "perception_frame_height": 2160,
            "perception_confidence": 0.9, "visible_ratio": 1.0, "visible_track_ids": [7]}


def bright_centroids(video: str, seconds: list[float]) -> list[tuple[float, float, int]]:
    """(x, y, pixel_count) of the bright blob, in a 54x96 grayscale thumbnail, per timestamp."""
    out = []
    for t in seconds:
        raw = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", video, "-frames:v", "1",
             "-vf", "scale=54:96,format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        pts = [(i % 54, i // 54) for i, value in enumerate(raw) if value > 128]
        if not pts:
            out.append((-1.0, -1.0, 0))
            continue
        out.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), len(pts)))
    return out


def render(video: Path, ev: dict) -> tuple[framing.FramingDecision, str]:
    editor._clamp = lambda start, end, path: (start, end)
    decision = framing._resolve_track_safe_decision(str(video), ev, framing.decide_framing(ev, sport="surfing"))
    return decision, framing._render_clip(str(video), ev, 0, decision)


def test_follow_crop_keeps_the_moving_athlete_large_and_centred() -> None:
    with tempfile.TemporaryDirectory(prefix="follow-crop-") as tmp:
        os.environ["TMP_DIR"] = tmp
        video = Path(tmp) / "src.mp4"
        make_source(video)
        write_sidecar(video, [i * 0.2 for i in range(int(DURATION / 0.2) + 1)])
        decision, clip = render(video, event())
        assert decision.mode == "follow_crop" and decision.path, decision
        assert decision.zoom > 1.0, decision
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                "-of", "csv=p=0", clip], capture_output=True, text=True, check=True).stdout.strip()
        assert probe == "2160,3840", probe
        blobs = bright_centroids(clip, [1.0, 2.0, 3.0, 4.0])
        for t, (x, y, count) in zip([1, 2, 3, 4], blobs):
            assert count > 0, f"athlete lost at t={t}"
            assert abs(x - 27) <= 8, f"athlete drifted off-centre at t={t}: x={x:.1f}/54"
            assert count >= 9, f"athlete too small at t={t}: {count} px in the thumbnail"


def test_contain_fallback_when_the_track_has_a_long_gap() -> None:
    with tempfile.TemporaryDirectory(prefix="follow-gap-") as tmp:
        os.environ["TMP_DIR"] = tmp
        video = Path(tmp) / "src.mp4"
        make_source(video)
        write_sidecar(video, [0.0, 0.2, 0.4, 5.6, 5.8, 6.0])      # 5 s with no detections
        decision, _ = render(video, event())
        assert decision.mode in {"contain", "tracked_crop"}, decision
        assert decision.mode != "follow_crop", "a pan across a 5 s tracking gap would be a guess"


def test_kill_switch_restores_contain() -> None:
    with tempfile.TemporaryDirectory(prefix="follow-off-") as tmp:
        os.environ["TMP_DIR"] = tmp
        os.environ["SPORTREEL_FOLLOW_CROP"] = "0"
        try:
            video = Path(tmp) / "src.mp4"
            make_source(video)
            write_sidecar(video, [i * 0.2 for i in range(int(DURATION / 0.2) + 1)])
            decision, _ = framing._resolve_track_safe_decision(str(video), event(), framing.decide_framing(event(), sport="surfing")), None
            assert decision.mode != "follow_crop", decision
        finally:
            os.environ.pop("SPORTREEL_FOLLOW_CROP", None)


def test_expression_is_a_valid_piecewise_linear_pan() -> None:
    path = ((10.0, 100.0, 0.0), (11.0, 200.0, 0.0), (12.0, 200.0, 0.0))
    expression = framing.follow_expression(path, 1, 10.0)
    assert "\\," in expression and expression.count("if(") == 2, expression
    assert expression.endswith("200)))") or "200" in expression


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("SKIP follow crop simulation (ffmpeg missing)")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS follow crop simulation ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
