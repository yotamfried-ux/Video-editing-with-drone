#!/usr/bin/env python3
"""Cycle 14b: observed action validity through the REAL production path with REAL decoded video frames.

Not synthetic event dictionaries alone: a real MP4 is encoded with ffmpeg (a bright moving "athlete" box and two
static people on a dark sea), its perception sidecar is written next to it and loaded by the production loader, and
the production functions publishable_reel_policy._qualification_inputs / record_athlete_outcome run with
SPORTREEL_ACTION_VALIDITY enabled. Only the model is stubbed; the stub decodes the grid JPEG that the production code
cut from the video and checks, tile by tile, that each crop shows the target (bright pixels where the target box is).

R1  gate off: no observation, no model call, eligibility unchanged
R2  valid answers: two passes, each grid really built from the target crops at the requested times; observation
    recorded on the event (VALID), both passes cover the window start AND end; RC-03 VALID with the observation
R3  failed-take-off answers: INVALID -> eligibility INVALID -> the part is NOT publishable (withheld)
R4  low-confidence valid answers: UNCERTAIN (never VALID) -> withheld
R5  target leaves the frame half way (identity/coverage check): UNCERTAIN, NO model call (no cost)
R6  answer that skips the ending crop (timestamp coverage): UNCERTAIN
R7  sample plan: every pass includes the first and last second of the window; gaps <= the planned step
R8  negative control: boxes shifted off the athlete (wrong target) -> the stub sees no athlete in the crops -> the
    observation is not VALID (the pixel check really tests what the crops contain)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import action_validity as av  # noqa: E402
from pipeline import action_validity_runtime as avr  # noqa: E402
from pipeline import output_qualification as oq  # noqa: E402
from pipeline import publishable_reel_policy as prp  # noqa: E402

FAILS: list[str] = []
W, H, DUR = 640, 360, 8.0


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def actor_box(t):                    # bright 30x60 athlete moving right at 60 px/s
    x = 40 + 60 * t
    return [x, 150, x + 30, 210]


def make_media(tmp: Path, *, leave_at: float | None = None, shift: float = 0.0) -> Path:
    video = tmp / "SRC_0001_D.MP4"
    if not video.exists():
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x0a1e3c:s={W}x{H}:d={DUR}:r=30",
               "-f", "lavfi", "-i", f"color=c=white:s=30x60:d={DUR}:r=30", "-filter_complex",
               "[0][1]overlay=x='40+60*t':y=150,drawbox=x=100:y=40:w=20:h=40:color=gray@1:t=fill,"
               "drawbox=x=500:y=280:w=20:h=40:color=gray@1:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    dets, t = [], 0.0
    while t <= DUR + 1e-9:
        if leave_at is None or t < leave_at:
            b = actor_box(t)
            dets.append({"frame_index": int(t * 30), "time_sec": round(t, 3), "class_name": "person", "class_id": 0,
                         "confidence": 0.9, "track_id": 7, "bbox_xyxy": [b[0] + shift, b[1], b[2] + shift, b[3]]})
        dets.append({"frame_index": int(t * 30), "time_sec": round(t, 3), "class_name": "person", "class_id": 0,
                     "confidence": 0.8, "track_id": 1, "bbox_xyxy": [100, 40, 120, 80]})
        dets.append({"frame_index": int(t * 30), "time_sec": round(t, 3), "class_name": "person", "class_id": 0,
                     "confidence": 0.8, "track_id": 2, "bbox_xyxy": [500, 280, 520, 320]})
        t += 0.2
    video.with_suffix(".perception.json").write_text(json.dumps(
        {"source_video": str(video), "status": "ok", "frame_width": W, "frame_height": H, "detections": dets}))
    return video


class Model:
    """Stub model: verifies the grid pixels, then answers with a scripted state sequence for the requested times."""

    def __init__(self, script, conf="high", drop_last=False):
        self.script, self.conf, self.drop_last, self.calls, self.tiles_ok = script, conf, drop_last, 0, []

    def __call__(self, image: bytes, prompt: str) -> str:
        from PIL import Image
        self.calls += 1
        times = [float(x) for x in re.search(r"\(([\d., ]+)\)", prompt).group(1).split(",")]
        im = Image.open(BytesIO(image)).convert("L")
        tile = avr.TILE
        ok = []
        for i in range(len(times)):
            x0, y0 = (i % 4) * tile, (i // 4) * tile
            centre = im.crop((x0 + tile // 3, y0 + tile // 3, x0 + 2 * tile // 3, y0 + 2 * tile // 3))
            hist = centre.histogram()
            bright = sum(hist[200:]) / max(1, sum(hist))
            ok.append(bright > 0.05)
        self.tiles_ok.append(ok)
        if not all(ok):
            return "the target is not visible"         # a wrong-target grid cannot produce observations
        rows = [{"t": t, "state": self.script(i, len(times)), "carried": self.script(i, len(times)) != "paddling"}
                for i, t in enumerate(times)]
        if self.drop_last:
            rows = rows[:-1]
        return json.dumps({"frames": rows, "confidence": self.conf})


def riding(i, n):
    return "paddling" if i == 0 else "standing_riding"


def failed(i, n):
    return "paddling" if i < 2 else ("popping_up" if i < n - 2 else "in_water")


def event(video: Path) -> dict:
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    return {"event_uid": "ev2_media_integration_1", "event_id": "ev2_media_integration_1", "_src": str(video),
            "source_video": str(video), "event_source_ref": f"sha256:{sha}", "start": 0.5, "end": 7.5,
            "target_track_id": "7", "sport": "surfing", "event_type": "wave_catch", "type": "wave_catch", "score": 9,
            "perception_evidence_status": "tracker_sidecar", "athlete_activity_state": "active"}


def run(video, model, gate=True):
    ev = event(video)
    original = avr.default_ask
    avr.default_ask = model
    if gate:
        os.environ[av.ENV] = "1"
    else:
        os.environ.pop(av.ENV, None)
    try:
        inputs = prp._qualification_inputs([ev], "surfing")
    finally:
        avr.default_ask = original
        os.environ.pop(av.ENV, None)
    return ev, inputs["events"][0]["eligibility"], inputs


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("FAIL ffmpeg is required for the real-media integration test")
        return 1
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(tmp / "manifest.json")
        video = make_media(tmp)

        m = Model(riding)
        ev, elig, _ = run(video, m, gate=False)
        check(m.calls == 0 and "action_validity" not in ev and elig["verdict"] == oq.VALID, "R1 gate off: no call, unchanged")

        m = Model(riding)
        ev, elig, _ = run(video, m)
        obs = ev.get("action_validity") or {}
        covs = [c["coverage"] for c in obs.get("checks", [])]
        check(m.calls == 2 and all(all(t) for t in m.tiles_ok), f"R2 two grids cut from the real video, every tile shows the target ({m.calls} calls)")
        check(obs.get("verdict") == av.VALID and elig["verdict"] == oq.VALID and "observed_established_action" in elig["positive"],
              f"R2 observation recorded and used: {obs.get('verdict')} / {elig['verdict']}")
        check(len(covs) == 2 and all(c["covers_start"] and c["covers_end"] for c in covs),
              f"R2 both passes cover the window start and end: {covs}")

        m = Model(failed)
        ev, elig, inputs = run(video, m)
        part = None
        avr_ask, avr.default_ask = avr.default_ask, m
        os.environ[av.ENV] = "1"
        try:
            row = prp.record_athlete_outcome(sport="surfing", athlete_label="surfer X", final_reels=[str(tmp / "reel.mp4")],
                                             events_by_reel={str(tmp / "reel.mp4"): [event(video)]}, flagged_paths=set(),
                                             specs_by_path={str(tmp / "reel.mp4"): {"duration": 7, "width": 1080,
                                                                                     "height": 1920, "aspect": 9 / 16,
                                                                                     "has_audio": False, "fps": 30}})
            part = row["parts"][0]
        finally:
            avr.default_ask = avr_ask
            os.environ.pop(av.ENV, None)
        check(ev["action_validity"]["verdict"] == av.INVALID and elig["verdict"] == oq.INVALID,
              f"R3 failed take-off observed INVALID -> eligibility {elig['verdict']}")
        check(part is not None and part.get("publishable") is not True and any("action_invalid" in str(i) for i in part.get("technical_issues") or []),
              f"R3 production record_athlete_outcome withholds the part: publishable={part and part.get('publishable')}")

        m = Model(riding, conf="low")
        ev, elig, _ = run(video, m)
        check(ev["action_validity"]["verdict"] == av.UNCERTAIN and elig["verdict"] == oq.UNCERTAIN,
              f"R4 low confidence is never VALID: {ev['action_validity']['verdict']}")

        leave = make_media(tmp, leave_at=3.0)
        m = Model(riding)
        ev, elig, _ = run(leave, m)
        check(m.calls == 0 and ev["action_validity"]["basis"] == "target_coverage_insufficient" and elig["verdict"] == oq.UNCERTAIN,
              f"R5 target lost half way: {ev['action_validity']['basis']}, {m.calls} model calls")
        video = make_media(tmp)

        m = Model(riding, drop_last=True)
        ev, elig, _ = run(video, m)
        check(ev["action_validity"]["verdict"] == av.UNCERTAIN, "R6 an answer that skips the ending crop is UNCERTAIN")

        plan = avr.sample_plan(0.5, 7.5)
        gaps_ok = all(max(b - a for a, b in zip(p, p[1:])) <= plan["step_sec"] + 0.011 for p in plan["passes"])
        check(all(p[0] == 0.5 and p[-1] == 7.5 for p in plan["passes"]) and gaps_ok,
              f"R7 each pass spans the full window: {[ (p[0], p[-1], len(p)) for p in plan['passes']]}, step {plan['step_sec']}")

        wrong = make_media(tmp, shift=200.0)
        m = Model(riding)
        ev, elig, _ = run(wrong, m)
        check(ev["action_validity"]["verdict"] != av.VALID and m.calls >= 1 and not all(all(t) for t in m.tiles_ok),
              f"R8 negative control: crops off the athlete are detected ({ev['action_validity']['verdict']})")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
