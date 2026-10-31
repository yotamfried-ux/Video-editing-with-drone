#!/usr/bin/env python3
"""EDL export contract: the exported geometry must match the pixels the real renderer produced.

Renders with the production ``_render_clip`` on a synthetic 3840x2160 source containing one bright moving square, then
checks that the square's *actual* centroid in the rendered output equals the centroid predicted by transforming the known
source position through the exported EDL. Also covers reel assembly offsets, multi-source reels, opt-in/no-op behaviour and
failure isolation. Runs with plain python (no pytest).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ("GEMINI_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON", "RAW_FOLDER_ID", "PROCESSED_FOLDER_ID",
            "REVIEW_FOLDER_ID", "APPROVED_FOLDER_ID", "OWNER_EMAIL"):
    os.environ.setdefault(key, "fixture-not-used")

import pipeline.edl_export as edl_export  # noqa: E402
import pipeline.quality_preserving_framing as framing  # noqa: E402
from pipeline.stages import editor  # noqa: E402

SIZE = 120
FPS = 30
OW, OH = framing.OUTPUT_WIDTH, framing.OUTPUT_HEIGHT


def make_source(path: Path, seconds: float, x_expr: str, y: int = 1020, tag: str = "a") -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=3840x2160:r={FPS}:d={seconds}",
         "-f", "lavfi", "-i", f"color=c=white:s={SIZE}x{SIZE}:r={FPS}:d={seconds}",
         "-filter_complex", f"[0:v][1:v]overlay=x='{x_expr}':y={y}:eval=frame", "-metadata", f"title={tag}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(path)], check=True)


def square_center(source_frame: int, x_expr_fn, y: int = 1020) -> tuple[float, float]:
    return x_expr_fn(source_frame / FPS) + SIZE / 2, y + SIZE / 2


def write_sidecar(video: Path, fn, seconds: float, step: float = 0.2, y: int = 1020) -> None:
    dets, t = [], 0.0
    while t <= seconds + 1e-9:
        x1 = fn(t)
        dets.append({"time_sec": t, "frame_index": int(round(t * FPS)), "bbox_xyxy": [x1, y, x1 + SIZE, y + SIZE],
                     "frame_width": 3840, "frame_height": 2160, "confidence": 0.9, "visible_ratio": 1.0,
                     "class_id": 0, "class_name": "athlete", "track_id": 7})
        t += step
    video.with_suffix(video.suffix + ".perception.json").write_text(
        json.dumps({"source_video": str(video), "status": "ok", "detections": dets}))


def event(fn, seconds: float, height_px: int = SIZE, y: int = 1020, x_override: float | None = None) -> dict:
    x1 = fn(0) if x_override is None else x_override
    return {"type": "surf_ride", "sport": "surfing", "start": 0.0, "end": seconds, "event_id": "ev1",
            "perception_evidence_status": "tracker_sidecar", "track_id": 7,
            "bbox_xyxy": [x1, y, x1 + SIZE, y + height_px], "perception_frame_width": 3840, "perception_frame_height": 2160,
            "perception_confidence": 0.9, "visible_ratio": 1.0, "visible_track_ids": [7]}


def output_centroid(clip: str, out_frame: int) -> tuple[float, float, int]:
    """Centroid (output px) of the bright blob in an exact output frame, using a 216x384 gray thumbnail."""
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", clip, "-vf", f"select=eq(n\\,{out_frame}),scale=216:384,format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    pts = [(i % 216, i // 216) for i, v in enumerate(raw) if v > 150]
    if not pts:
        return -1.0, -1.0, 0
    return (sum(p[0] for p in pts) / len(pts) + 0.5) * 10, (sum(p[1] for p in pts) / len(pts) + 0.5) * 10, len(pts)


def predict(edl: dict, shot: dict, out_frame: int, center: tuple[float, float]) -> tuple[float, float]:
    """Studio-equivalent transform of a source-pixel point into output pixels for ``out_frame``."""
    crop = shot["crop_start"]
    kfs = shot.get("keyframes")
    if kfs:
        a = max((k for k in kfs if k["out_frame"] <= out_frame), key=lambda k: k["out_frame"], default=kfs[0])
        b = min((k for k in kfs if k["out_frame"] > out_frame), key=lambda k: k["out_frame"], default=a)
        t = 0.0 if a is b else (out_frame - a["out_frame"]) / (b["out_frame"] - a["out_frame"])
        crop = {k: a["crop"][k] + (b["crop"][k] - a["crop"][k]) * t for k in ("cx", "cy", "w", "h")}
    s = min(edl["output"]["width"] / crop["w"], edl["output"]["height"] / crop["h"])
    return (center[0] - crop["cx"]) * s + OW / 2, (center[1] - crop["cy"]) * s + OH / 2


def render_one(tmp: Path, src: Path, ev: dict, seconds: float):
    os.environ["TMP_DIR"] = str(tmp)
    os.environ[edl_export.ENV_FLAG] = "1"
    edl_export.reset_for_tests()
    editor._clamp = lambda start, end, path: (start, end)
    decision = framing._resolve_track_safe_decision(str(src), ev, framing.decide_framing(ev, sport="surfing"))
    clip = framing._render_clip(str(src), ev, 0, decision)
    assert clip, "render failed"
    framing._export_edl_clip(str(src), ev, decision, clip)
    return decision, clip


def reel_edl(clip_paths, out_path, transitions=None):
    written = edl_export.write_reel_edl(clip_paths, str(out_path), transitions, FPS, OW, OH)
    assert written, "EDL not written"
    return json.loads(Path(written).read_text())


def check_pixels(edl: dict, clip: str, fn, frames: list[int], tol: float = 24.0) -> None:
    for f in frames:
        shot = next(s for s in edl["shots"] if s["out_start"] <= f < s["out_end"])
        src_frame = shot["src_start"] + int(round((f - shot["out_start"]) * shot["speed"]))
        center = square_center(src_frame, fn)
        px, py = predict(edl, shot, f, center)
        ax, ay, count = output_centroid(clip, f)
        assert count > 0, f"surfer not visible in output frame {f}"
        assert abs(ax - px) <= tol and abs(ay - py) <= tol, (
            f"frame {f}: EDL predicts ({px:.0f},{py:.0f}) but render shows ({ax:.0f},{ay:.0f}) mode={shot['mode']}")


def test_contain_matches_pixels() -> None:
    fn = lambda t: 1800.0 + 100 * t  # large near-centre athlete => contain
    with tempfile.TemporaryDirectory(prefix="edl-contain-") as tmp:
        tmp = Path(tmp)
        src = tmp / "src.mp4"
        make_source(src, 2.0, "1800+100*t")
        ev = event(fn, 2.0, height_px=SIZE)
        ev["bbox_xyxy"] = [1800, 700, 1800 + 400, 1500]  # big, readable, centred => contain decision
        decision, clip = render_one(tmp, src, ev, 2.0)
        assert decision.mode == "contain", decision
        edl = reel_edl([clip], tmp / "reel.mp4")
        assert edl["schema"] == "edl/v1" and edl["mode"] == "contain" and len(edl["shots"]) == 1
        shot = edl["shots"][0]
        assert shot["crop_start"] == {"cx": 1920.0, "cy": 1080.0, "w": 3840.0, "h": 2160.0}
        assert shot["source_sha256"] == edl_export.source_sha256(str(src))
        assert edl["output"]["width"] == OW and edl["output"]["fps"] == 30
        check_pixels(edl, clip, fn, [5, 30, 55])


def test_follow_crop_matches_pixels_with_keyframes() -> None:
    fn = lambda t: 400.0 + 500 * t
    with tempfile.TemporaryDirectory(prefix="edl-follow-") as tmp:
        tmp = Path(tmp)
        src = tmp / "src.mp4"
        make_source(src, 4.0, "400+500*t")
        write_sidecar(src, fn, 4.0)
        decision, clip = render_one(tmp, src, event(fn, 4.0), 4.0)
        assert decision.mode == "follow_crop", decision
        edl = reel_edl([clip], tmp / "reel.mp4")
        shot = edl["shots"][0]
        assert shot["mode"] == "tracked_crop" and len(shot["keyframes"]) >= 3, shot
        assert shot["keyframes"][0]["out_frame"] == 0 and shot["keyframes"][-1]["out_frame"] == 119
        check_pixels(edl, clip, fn, [3, 40, 80, 115])


def test_fixed_crop_matches_pixels() -> None:
    fn = lambda t: 3300.0  # stationary small athlete near the right edge => emergency fixed crop
    with tempfile.TemporaryDirectory(prefix="edl-fixed-") as tmp:
        tmp = Path(tmp)
        src = tmp / "src.mp4"
        make_source(src, 2.0, "3300")
        write_sidecar(src, fn, 2.0)
        os.environ["SPORTREEL_FOLLOW_CROP"] = "0"
        try:
            decision, clip = render_one(tmp, src, event(fn, 2.0), 2.0)
        finally:
            os.environ.pop("SPORTREEL_FOLLOW_CROP", None)
        assert decision.mode == "tracked_crop", decision
        edl = reel_edl([clip], tmp / "reel.mp4")
        shot = edl["shots"][0]
        assert shot["mode"] == "tracked_crop" and "keyframes" not in shot
        check_pixels(edl, clip, fn, [2, 30, 57])


def test_reel_offsets_match_editor_and_blends_are_listed() -> None:
    fn = lambda t: 1800.0 + 100 * t
    with tempfile.TemporaryDirectory(prefix="edl-reel-") as tmp:
        tmp = Path(tmp)
        os.environ["TMP_DIR"] = str(tmp)
        os.environ[edl_export.ENV_FLAG] = "1"
        edl_export.reset_for_tests()
        editor._clamp = lambda start, end, path: (start, end)
        clips, events = [], []
        for i, tag in enumerate(("a", "b")):
            src = tmp / f"src{i}.mp4"
            make_source(src, 2.0, "1800+100*t", tag=tag)
            ev = event(fn, 2.0)
            ev["bbox_xyxy"] = [1800, 700, 2200, 1500]
            ev["event_id"] = f"ev{i}"
            decision = framing._resolve_track_safe_decision(str(src), ev, framing.decide_framing(ev, sport="surfing"))
            clip = framing._render_clip(str(src), ev, i, decision)
            framing._export_edl_clip(str(src), ev, decision, clip)
            clips.append(clip)
            events.append(ev)
        transitions = ["fade", "fade"]
        edl = reel_edl(clips, tmp / "reel.mp4", transitions)
        timeline = editor._events_with_rendered_timeline(events, clips, transitions)
        assert len(edl["shots"]) == 2
        for shot, ev in zip(edl["shots"], timeline):
            assert shot["event_id"] == ev["event_id"]
            assert abs(shot["out_start"] / FPS - ev["rendered_timeline_start"]) <= 1 / FPS, (shot, ev)
        assert edl["blends"] and edl["blends"][0]["out_start"] == edl["shots"][1]["out_start"]
        assert edl["shots"][0]["out_end"] == edl["shots"][1]["out_start"], "shots must not overlap; blend frames are listed"
        assert len(edl["sources"]) == 2 and edl["source_sha256"] == "multiple"


def test_disabled_by_default_and_failures_never_raise() -> None:
    with tempfile.TemporaryDirectory(prefix="edl-off-") as tmp:
        os.environ["TMP_DIR"] = tmp
        os.environ.pop(edl_export.ENV_FLAG, None)
        edl_export.reset_for_tests()
        assert edl_export.enabled() is False
        edl_export.record_clip("/nope.mp4", "/nope-src.mp4", {}, None, 0, 1, OW, OH, FPS)  # no-op
        assert edl_export.write_reel_edl(["/nope.mp4"], "/nope/reel.mp4", None, FPS, OW, OH) is None
        os.environ[edl_export.ENV_FLAG] = "1"
        try:
            edl_export.record_clip("/nope.mp4", "/does-not-exist.mp4", {}, None, 0, 1, OW, OH, FPS)  # swallowed
            assert not edl_export._CLIPS
            edl = edl_export.build_reel_edl(["/nope.mp4"], "/x/reel.mp4", [1.0], [], FPS, OW, OH, None, None)
            assert edl["shots"] == [] and edl["notes"] == ["clip_not_recorded:nope.mp4"], "incomplete EDL says so"
        finally:
            os.environ.pop(edl_export.ENV_FLAG, None)


def test_rendering_is_unchanged_by_export() -> None:
    """Same decision + same ffmpeg arguments whether export is on or off (export is observational)."""
    fn = lambda t: 1800.0 + 100 * t
    digests = []
    with tempfile.TemporaryDirectory(prefix="edl-same-") as tmp:
        tmp = Path(tmp)
        src = tmp / "src.mp4"
        make_source(src, 1.0, "1800+100*t")
        ev = event(fn, 1.0)
        ev["bbox_xyxy"] = [1800, 700, 2200, 1500]
        editor._clamp = lambda start, end, path: (start, end)
        seen = []
        real_run = subprocess.run

        def spy(cmd, *a, **k):
            if cmd and cmd[0] == "ffmpeg" and "-filter_complex" in cmd:
                seen.append([c for c in cmd if not str(c).endswith(".mp4")])
            return real_run(cmd, *a, **k)

        framing.subprocess.run = spy
        try:
            for flag in ("0", "1"):
                os.environ["TMP_DIR"] = str(tmp / flag)
                os.environ[edl_export.ENV_FLAG] = flag
                edl_export.reset_for_tests()
                decision = framing._resolve_track_safe_decision(str(src), ev, framing.decide_framing(ev, sport="surfing"))
                clip = framing._render_clip(str(src), ev, 0, decision)
                framing._export_edl_clip(str(src), ev, decision, clip)
                digests.append(json.dumps(seen[-1]))
        finally:
            framing.subprocess.run = real_run
            os.environ.pop(edl_export.ENV_FLAG, None)
    assert digests[0] == digests[1]


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("SKIP edl export contract (ffmpeg missing)")
        return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} EDL export contract tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
