#!/usr/bin/env python3
"""A ride that ends within 2 s of the end of the recording is cut at the end of the recording.

Run 42857524999: drone files stop recording right after the ride, and the manual catalog ends the ride at the
last frame. The cut ended 0.2-1.6 s earlier on 15 of 22 catalogued sources, and final QA reported the missing
outcome as PREMATURE_CUT, critical on 0115 ("cut just before its natural completion (the fall)"; cut at 15.5 s of
a 16.4 s file). The 2 s bound is QA's own DEAD_TIME definition, not a value fitted to the catalog.

Drives the production bootstrap stack and editor.compile_multi_source_reel with real ffmpeg (as
scripts/test_single_pass_pipeline_simulation.py does) and checks the rendered reel and the QA timeline.
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


def fail(msg: str) -> None:
    raise SystemExit(f"recording-end tail contract FAILED: {msg}")


def main() -> int:
    from pipeline.complete_action_window_policy import RECORDING_END_TAIL_MAX_SEC, extend_to_recording_end

    if RECORDING_END_TAIL_MAX_SEC > 2.0:
        fail("the tail must stay within QA's DEAD_TIME definition (> ~2 s)")
    base = {"start": 6.5, "end": 15.5}
    if extend_to_recording_end(base, 16.4).get("end") != 16.4:
        fail("0.9 s before the end of the recording must run to it")
    if extend_to_recording_end({"start": 1.0, "end": 10.0}, 16.4).get("end") != 10.0:
        fail("6.4 s of recording left is a real ending, not a tail")
    if extend_to_recording_end({**base, "_teaser": True}, 16.4).get("end") != 15.5:
        fail("a teaser keeps its window")
    lost = {**base, "window_refinement": {"status": "trimmed", "reasons": ["track_lost_before_end"]}}
    if extend_to_recording_end(lost, 16.4).get("end") != 15.5:
        fail("an end where the athlete's track was lost must not be extended")
    if extend_to_recording_end({"start": 1.0, "end": 16.4}, 16.4).get("end") != 16.4:
        fail("an end already at the recording end is unchanged")

    with tempfile.TemporaryDirectory(prefix="rec-tail-") as tmp:
        os.environ.update({"TMP_DIR": tmp, "SPORTREEL_EXPORT_EDL": "1", "SPORTREEL_REQUIRE_EXPLICIT_SCOPE": "1",
                           "PUBLISHABLE_REEL_MANIFEST_FILE": os.path.join(tmp, "manifest.json")})
        import config

        config.TMP_DIR = tmp
        src = os.path.join(tmp, "DJI_20260720161907_0115_D.MP4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=16.4",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p", src], check=True)
        from pipeline import bootstrap

        bootstrap.install_pre_orchestrator_patches()
        import pipeline.stages.editor as editor

        evidence = {"perception_evidence_status": "tracker_sidecar", "track_id": "7", "perception_confidence": 0.9,
                    "bbox_xyxy": [820.0, 300.0, 1100.0, 820.0], "perception_frame_width": 1920,
                    "perception_frame_height": 1080, "visible_ratio": 1.0}
        event = {"event_id": "ride", "type": "wave_catch", "description": "rides a wave and falls", "start": 6.5,
                 "end": 15.5, "score": 8, "crop_x": 0.5, "crop_y": 0.6, "outcome_end": None, "timing_precise": True,
                 "timing_evidence": "start 6.5s: pops up; end 15.5s: the wave closes out", "edit": {}, **evidence}
        events_out: list = []
        reels = editor.compile_multi_source_reel([{"path": src, "events": [event]}], sport="surfing",
                                                 athlete_label="shirtless surfer", _events_out=events_out,
                                                 invocation_id="inv_0_rec_tail")
        if not reels:
            fail("no reel produced")
        reel = reels[0]
        duration = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                                    "json", reel], capture_output=True, text=True, check=True).stdout)["format"]["duration"])
        rendered = [ev for path, evs in events_out if path == reel for ev in evs if not ev.get("_teaser")]
        ends = [float(ev.get("end")) for ev in rendered]
        if not ends or abs(max(ends) - 16.4) > 0.05:
            fail(f"the QA timeline must carry the extended end 16.4 s, got {ends}")
        if abs(duration - (16.4 - 6.5)) > 0.25:
            fail(f"the reel must show 6.5-16.4 s of the source ({16.4 - 6.5:.1f} s), got {duration:.2f} s")
    print(f"recording-end tail contract ok (6.5-15.5 s in a 16.4 s file -> rendered {duration:.2f} s, QA end 16.4 s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
