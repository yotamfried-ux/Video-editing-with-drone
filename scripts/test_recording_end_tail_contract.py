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

    # The analyzer's own "outcome resolves here" second is part of the action (its prompt calls it a firm
    # claim). The production cut chain dropped it: the wrapper that applied it (window_policy) is not on the
    # path quality_preserving_framing installs.
    from pipeline.complete_action_window_policy import extend_to_outcome, normalize_complete_action_event

    landing = {"start": 2.0, "end": 6.0, "outcome_end": 8.5}
    if extend_to_outcome(landing, 30.0).get("end") != 8.5:
        fail("an outcome reported after `end` must be inside the cut")
    if extend_to_outcome(landing, 7.0).get("end") != 7.0:
        fail("an outcome past the end of the recording is clamped to it")
    if extend_to_outcome({"start": 2.0, "end": 6.0, "outcome_end": 5.0}, 30.0).get("end") != 6.0:
        fail("an outcome before `end` never shortens the cut")
    if extend_to_outcome({"start": 2.0, "end": 6.0, "outcome_end": None}, 30.0).get("end") != 6.0:
        fail("no reported outcome: the cut is unchanged")
    if extend_to_outcome({**landing, "_teaser": True}, 30.0).get("end") != 6.0:
        fail("a teaser keeps its window")
    if normalize_complete_action_event(landing).get("end") != 8.5:
        fail("the outcome must reach the event the renderer and QA use (no source file: length unknown)")

    # A ride that ends in a fall keeps the fall (run 43013005072: 0151 and 0160 were rejected by final QA,
    # "cut while still surfing ... ending in a fall"). Values are the run's own analyzer and track numbers.
    from pipeline.complete_action_window_policy import extend_through_fall, FALL_OUTCOME_TAIL_SEC
    from pipeline.window_refinement import ends_in_fall, refine_event_window

    fall_0151 = {"start": 0.0, "end": 5.0,
                 "timing_evidence": "start 0.0s: athlete is already up and riding; end 5.0s: athlete falls into the whitewater as the wave ends."}
    if not ends_in_fall(fall_0151):
        fail("the analyzer's 'falls into the whitewater' end is a fall")
    if ends_in_fall({"timing_evidence": "start 2.8s: falls back then stands; end 20.5s: the ride on the whitewater has lost its power"}):
        fail("only the end clause counts: a fall at the start is not a fall ending")
    if ends_in_fall({"timing_evidence": "end 18.2s: steps off the board as the ride finishes in the shallows"}):
        fail("stepping off in the shallows is a finish, not a fall")
    extended = extend_through_fall(fall_0151, 7.61)
    if extended.get("end") != 5.0 + FALL_OUTCOME_TAIL_SEC or extended.get("end_before_fall_tail") != 5.0:
        fail(f"a fall ending keeps {FALL_OUTCOME_TAIL_SEC}s of the fall: {extended}")
    if extend_through_fall(fall_0151, 5.8).get("end") != 5.8:
        fail("the fall tail never passes the end of the recording")
    if extend_through_fall({**fall_0151, "timing_evidence": "end 5.0s: rides out of the wave"}, 7.61).get("end") != 5.0:
        fail("a ride that does not end in a fall gets no tail")
    if normalize_complete_action_event({**fall_0151, "_src": "nowhere.mp4"}).get("end") != 5.0 + FALL_OUTCOME_TAIL_SEC:
        fail("the fall tail must reach the event the renderer and QA use")

    # 0160: the analyzer ended at 10.8 s "falls off the board into the water"; the track was lost at 8.74 s.
    class Det:
        def __init__(self, t):
            self.time_sec, self.tracker_id, self.class_name = t, 4, "person"
            self.xyxy, self.frame_width, self.frame_height = (100, 100, 160, 200), 1920, 1080

    dets = [Det(3.5 + 0.2 * i) for i in range(0, 27)]  # 3.5 .. 8.7 s
    fall_0160 = {"start": 3.5, "end": 10.8, "target_track_id": "4", "outcome_end": 10.8,
                 "timing_evidence": "start 3.5s: begins to pop up; end 10.8s: falls off the board into the water."}
    refined = refine_event_window(fall_0160, dets)
    if refined.get("end") != 10.8 or not (refined.get("window_refinement") or {}).get("track_lost_in_fall_kept"):
        fail(f"a track lost in the fall must not trim the fall away: {refined.get('end')} {refined.get('window_refinement')}")
    ridden_off = {**fall_0160, "timing_evidence": "start 3.5s: pops up; end 10.8s: kicks out over the back of the wave"}
    if refine_event_window(ridden_off, dets).get("end") == 10.8:
        fail("without a fall, a track lost 2 s before the end still trims the window")
    far = {**fall_0160, "end": 14.0, "timing_evidence": "end 14.0s: falls"}
    if refine_event_window(far, dets).get("end") == 14.0:
        fail("a track lost long before a claimed fall still trims the window")

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
