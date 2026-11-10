#!/usr/bin/env python3
"""Pipeline simulation: production render path end to end, with real ffmpeg.

Drives ``editor.compile_multi_source_reel`` exactly as context_qa_gate does: real bootstrap patch stack,
quality-first 4K framing, publishable policy, EDL export, and an explicit ``invocation_id``. It verifies the
two fixes for run 42474968394 together on one reel:

* the render returns with the explicit invocation ID, and QA can activate that exact scope (crash fix);
* the reel is rendered in ONE ffmpeg pass (single lossy encode), as a 2160x3840/30 silent MP4 whose duration
  matches the rendered timeline handed to QA, with no clip files left and the EDL written.
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


def fail(msg: str) -> None:
    raise SystemExit(f"single-pass pipeline simulation FAILED: {msg}")


def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main() -> None:
    if shutil.which("ffmpeg") is None:
        fail("ffmpeg is required")
    with tempfile.TemporaryDirectory(prefix="sportreel-sp-sim-") as tmp:
        os.environ.update({
            "TMP_DIR": tmp,
            "SPORTREEL_EXPORT_EDL": "1",
            "SPORTREEL_REQUIRE_EXPLICIT_SCOPE": "1",
            "PUBLISHABLE_REEL_MANIFEST_FILE": os.path.join(tmp, "manifest.json"),
        })
        os.environ.pop("SPORTREEL_SINGLE_PASS_RENDER", None)
        import config

        config.TMP_DIR = tmp
        src = os.path.join(tmp, "DJI_sim_0001_D.MP4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=30",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p", src], check=True)

        from pipeline import bootstrap

        bootstrap.install_pre_orchestrator_patches()
        import pipeline.publishable_pending_scope as pending_scope
        import pipeline.quality_preserving_framing as q
        import pipeline.stages.editor as editor

        renders: list[list[str]] = []
        real_run = subprocess.run

        def spy(cmd, *args, **kwargs):
            if isinstance(cmd, list) and cmd and cmd[0] == "ffmpeg" and "-filter_complex" in cmd:
                renders.append(cmd)
            return real_run(cmd, *args, **kwargs)

        q.subprocess.run = spy
        editor.subprocess.run = spy

        label, inv_id = "Surfer in red shorts", "inv_0_simulation"
        # Tracker-sidecar evidence as the perception stage attaches it (readable athlete -> contain framing).
        evidence = {"perception_evidence_status": "tracker_sidecar", "track_id": "7", "perception_confidence": 0.9,
                    "bbox_xyxy": [820.0, 300.0, 1100.0, 820.0], "perception_frame_width": 1920,
                    "perception_frame_height": 1080, "visible_ratio": 1.0}
        events = [
            # e1 carries the analyzer's boundary evidence (end = observed ride end); e2 is a legacy event without it.
            {"event_id": "e1", "type": "wave_catch", "start": 2.0, "end": 7.0, "score": 8, "crop_x": 0.5, "crop_y": 0.6,
             "outcome_end": None, "timing_precise": True,
             "timing_evidence": "start 2.0s: pops up on the board; end 7.0s: falls as the wave closes out",
             "edit": {"transition_out": "slide"}, **evidence},
            {"event_id": "e2", "type": "turn", "start": 18.0, "end": 24.0, "score": 9, "crop_x": 0.5, "crop_y": 0.6,
             "edit": {"transition_out": "cut"}, **evidence},
        ]
        events_out: list = []
        reels = editor.compile_multi_source_reel(
            [{"path": src, "events": events}], sport="surfing", athlete_label=label,
            _events_out=events_out, invocation_id=inv_id,
        )
        if not reels:
            fail("no reel produced")
        reel = reels[0]
        if len(renders) != 1:
            fail(f"expected exactly one ffmpeg render pass for the reel, saw {len(renders)}")
        if renders[0].count("-i") < 2 or src not in renders[0]:
            fail("the single pass must read the source windows directly (one input per clip)")
        if "xfade" not in renders[0][renders[0].index("-filter_complex") + 1]:
            fail("the simulation must cover a multi-clip reel with transitions")

        info = probe(reel)
        stream = next(s for s in info["streams"] if s["codec_type"] == "video")
        if (stream["width"], stream["height"]) != (q.OUTPUT_WIDTH, q.OUTPUT_HEIGHT):
            fail(f"reel must be {q.OUTPUT_WIDTH}x{q.OUTPUT_HEIGHT}, got {stream['width']}x{stream['height']}")
        if stream["r_frame_rate"] != f"{q.OUTPUT_FPS}/1":
            fail(f"reel must be {q.OUTPUT_FPS} fps, got {stream['r_frame_rate']}")
        if any(s["codec_type"] == "audio" for s in info["streams"]):
            fail("SportReel reels are silent")

        ordered = [ev for path, evs in events_out if path == reel for ev in evs]
        if not ordered:
            fail("events_out must describe the rendered reel")
        timeline_end = max(float(ev["rendered_timeline_end"]) for ev in ordered)
        duration = float(info["format"]["duration"])
        if abs(duration - timeline_end) > 0.1:
            fail(f"reel duration {duration:.3f}s must match the rendered timeline {timeline_end:.3f}s given to QA")
        # Run 42814819534: every evidence-backed ride end still reached QA as a blocking RIDE_BOUNDARY_UNCERTAIN.
        from pipeline.context_qa_gate import build_edit_context
        from pipeline.source_evidence_runner import _context_defects

        by_id = {ev.get("event_id"): ev for ev in ordered}
        blocking = {eid: {d["type"] for d in _context_defects(build_edit_context(reel, [ev]))} for eid, ev in by_id.items()}
        if "RIDE_BOUNDARY_UNCERTAIN" in blocking.get("e1", set()):
            fail(f"the evidence-backed ride end of e1 must not block QA, got {blocking}")
        if "RIDE_BOUNDARY_UNCERTAIN" not in blocking.get("e2", set()):
            fail(f"a ride end without evidence must stay a blocking QA defect, got {blocking}")
        stamped = {ev.get("_render_invocation_id") for ev in ordered}
        if stamped != {inv_id}:
            fail(f"events must carry the explicit invocation_id, got {stamped}")
        token = pending_scope.activate_next_scope("surfing", label, invocation_id=inv_id)
        pending_scope.release_scope(token)

        leftovers = [p.name for p in Path(tmp).glob("*_clip*.mp4")]
        if leftovers:
            fail(f"no per-clip files may be left behind: {leftovers}")
        edls = list((Path(tmp) / "pipeline-debug" / "edl").glob("*.json"))
        if not edls:
            fail("the reel EDL must still be written for Ground-Truth evaluation")

    print(f"single-pass pipeline simulation ok (1 render pass, {duration:.2f}s 4K/30 silent reel = rendered timeline, "
          f"invocation scope activated, EDL written, ride-end evidence reaches QA)")


if __name__ == "__main__":
    main()
