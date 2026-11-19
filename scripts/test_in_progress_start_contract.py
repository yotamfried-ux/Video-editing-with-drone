#!/usr/bin/env python3
"""EXP-14-001 / FIX-PQ-14-001: an action already running when the recording opens starts on the first frame.

Root cause (run 44388634790, frozen replay 25/25 exact): the analyzer reports starts in whole/half seconds from ~1 fps
samples. The source-start snap only fired for starts <= 1.0 s, and the motion walk-back measured RAW on-screen
displacement, which a follow camera makes high even for a surfer who is waiting (0140, 0160). So recordings that open
mid-paddle or mid-ride were cut 1-2.5 s late (0162 1.47 s, 0097 1.0 s), and a lower threshold would have pulled
waiting into the cut. The fix measures the actor's motion RELATIVE to the other people in frame (camera-motion
compensated) and snaps only when every window from the first frame to the start shows real motion.

I1  moving actor, static others, start 1.5 s -> in progress, cut opens at 0.0 with its evidence recorded
I2  camera pan: actor and every other person shift together (actor waiting) -> NO claim (raw motion would say moving)
I3  actor first seen after 0.5 s -> no claim
I4  fewer than two reference people -> no claim (no evidence is never "moving")
I5  one window below the bound (waiting, then paddling) -> no claim
I6  profile without the field (football) / start already 0 -> no claim
I7  end to end: refine_event_window -> extend_to_recording_start opens at 0; the waiting control keeps its start
I8  negative control: replacing the compensated measure with raw displacement makes I2 fail (the test can fail)
I9  frozen replay (when COLD_OR_DEV_DIAGNOSTICS is set): no replayed boundary gets worse
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import action_onset as ao  # noqa: E402
from pipeline import complete_action_window_policy as pol  # noqa: E402
from pipeline import window_refinement as wr  # noqa: E402
from pipeline.sport_profiles import profile_for_event  # noqa: E402

FAILS: list[str] = []
SURF = profile_for_event({"sport": "surfing", "event_type": "wave_catch"}).onset


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def det(track, t, x, y, h=100.0):
    return SimpleNamespace(tracker_id=track, track_id=track, time_sec=round(t, 3), class_name="person",
                           xyxy=(x - h / 4, y - h / 2, x + h / 4, y + h / 2))


def scene(actor_speed, pan_speed, *, refs=3, actor_from=0.0, until=6.0, dip=None):
    """Actor 'A' moves actor_speed body heights/s in the world; `refs` static people; the camera pans at pan_speed
    (everything shifts on screen). `dip=(t0, t1)`: the actor is still in that interval."""
    out, t, ax = [], 0.0, 1000.0
    while t <= until + 1e-9:
        pan = -pan_speed * 100.0 * t
        if t >= actor_from:
            out.append(det("A", t, ax + pan, 500.0))
        for k in range(refs):
            out.append(det(f"R{k}", t, 300.0 + 400.0 * k + pan, 200.0 + 50 * k))
        moving = not (dip and dip[0] <= t < dip[1])
        ax += (actor_speed * 100.0 * 0.1) if moving else 0.0
        t += 0.1
    return out


def i1_to_i6():
    r = ao.in_progress_from_recording_start(scene(2.0, 0.0), "A", start=1.5, policy=SURF)
    check(bool(r and r["in_progress"]) and len(r["steps"]) == 3, f"I1 moving actor from frame 0 is in progress: {r}")
    raw = ao._motion_per_sec([d for d in scene(0.0, 1.5) if d.tracker_id == "A"][:11])
    r = ao.in_progress_from_recording_start(scene(0.0, 1.5), "A", start=1.5, policy=SURF)
    check(r is None and raw is not None and raw > 1.0,
          f"I2 camera pan with a waiting actor: raw on-screen motion {raw:.2f} body h/s, compensated claim {r}")
    check(ao.in_progress_from_recording_start(scene(2.0, 0.0, actor_from=1.0), "A", start=2.0, policy=SURF) is None,
          "I3 actor first seen at 1.0 s: no claim")
    check(ao.in_progress_from_recording_start(scene(2.0, 0.0, refs=1), "A", start=1.5, policy=SURF) is None,
          "I4 one reference person only: no claim")
    check(ao.in_progress_from_recording_start(scene(2.0, 0.8, dip=(0.0, 1.0)), "A", start=2.0, policy=SURF) is None,
          "I5 waiting for the first second, then paddling: no claim")
    foot = profile_for_event({"sport": "football", "event_type": "goal"}).onset
    check(ao.in_progress_from_recording_start(scene(2.0, 0.0), "A", start=1.5, policy=foot) is None
          and ao.in_progress_from_recording_start(scene(2.0, 0.0), "A", start=0.0, policy=SURF) is None,
          "I6 profile without the field / start already 0: no claim")


def i7():
    base = {"start": 1.5, "end": 5.5, "target_track_id": "A", "sport": "surfing", "event_type": "wave_catch"}
    moving = pol.extend_to_recording_start(wr.refine_event_window(dict(base), scene(2.0, 0.6)))
    waiting = pol.extend_to_recording_start(wr.refine_event_window(dict(base), scene(0.0, 0.6)))
    check(moving["start"] == 0.0 and moving.get("start_snap_evidence") == "in_progress_relative_motion"
          and moving["start_snapped_to_recording_start"] == 1.5, f"I7 moving: {moving.get('start')} {moving.get('start_snap_evidence')}")
    check(waiting["start"] == 1.5 and "start_snap_evidence" not in waiting, f"I7 waiting control keeps 1.5: {waiting.get('start')}")


def i8():
    original = ao.relative_motion_per_sec
    try:
        def raw(dets, actor, t0, t1, **_):
            return ao._motion_per_sec([d for d in actor if t0 - 0.05 <= d.time_sec <= t1 + 0.05])
        ao.relative_motion_per_sec = raw
        mutated = ao.in_progress_from_recording_start(scene(0.0, 1.5), "A", start=1.5, policy=SURF)
    finally:
        ao.relative_motion_per_sec = original
    check(mutated is not None, "I8 negative control: raw displacement wrongly claims the panning-camera waiting case "
                               "(so I2 really tests the compensation)")


def i9():
    path = os.getenv("BOUNDARY_REPLAY_DIFF")
    if not path or not Path(path).exists():
        print("SKIP I9 (set BOUNDARY_REPLAY_DIFF to an old/new replay pair to check it)")
        return
    pair = json.loads(Path(path).read_text())
    worse = [k for k, (a, b) in pair.items() if a and b and abs(b[0]) + abs(b[1]) > abs(a[0]) + abs(a[1]) + 1e-6]
    check(not worse, f"I9 frozen replay: no boundary worse ({len(pair)} events, worse: {worse[:5]})")


if __name__ == "__main__":
    i1_to_i6()
    i7()
    i8()
    i9()
    print(f"{len(FAILS)} failing")
    raise SystemExit(1 if FAILS else 0)
