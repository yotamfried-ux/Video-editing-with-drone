#!/usr/bin/env python3
"""Source-limited start (cycle 5): an action that was already running when the recording opened starts on frame 0.

S1  Measurement: `continuous_presence_from` walks the target track backwards from the analyzer start; a hole > 0.4 s
    stops the walk; a track not seen near the start gives None.
S2  Snap: start <= 1.0 s, track continuous from <= 0.5 s -> the cut opens at 0.0 and says so.
S3  Negative controls (nothing moves): start > 1.0 s, track first continuous from > 0.5 s, a hole in the track (continuity
    broken), the refinement already found the athlete missing at the start, no refinement / no measurement, teaser, start
    already 0, applied twice.
S4  Qualification: a snapped start is a VALID lead (continuous presence); the same start without that presence is still
    `lead_before_verified_actor`.
S5  Through `refine_event_window` with real detection objects, then the policy: end to end on a synthetic ride.
S6  Frozen sidecars (when present): the rule changes at least the known late starts and moves NO ride whose GT starts
    later than the snap window (82dd..., 3095fb... style controls) - see scripts/boundary_start_replay.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from pipeline import complete_action_window_policy as pol  # noqa: E402
from pipeline import output_qualification as oq  # noqa: E402
from pipeline import window_refinement as wr  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def dets(track: str, times: list[float]):
    return [SimpleNamespace(tracker_id=track, time_sec=t) for t in times]


def ev(start, cont, **extra):
    refinement = {"status": "unchanged", "first_track_sec": 2.0, "last_track_sec": 9.0}
    if cont is not None:
        refinement["track_continuous_from_sec"] = cont
    refinement.update(extra.pop("refinement", {}))
    return {"start": start, "end": 9.0, "window_refinement": refinement, **extra}


def s1():
    d = dets("7", [round(0.03 + 0.08 * i, 2) for i in range(40)])                  # dense 0.03 .. 3.15
    check(wr.continuous_presence_from(d, "7", 1.0) == 0.03, "S1 dense track")
    holed = dets("7", [0.03, 0.11, 0.19, 0.27] + [1.0 + 0.08 * i for i in range(20)])      # hole 0.27 -> 1.0
    check(wr.continuous_presence_from(holed, "7", 1.5) == 1.0, f"S1 hole must stop the walk: {wr.continuous_presence_from(holed, '7', 1.5)}")
    check(wr.continuous_presence_from(dets("7", [8.0, 8.1]), "7", 1.0) is None, "S1 not near the start")
    check(wr.continuous_presence_from(d, "9", 1.0) is None, "S1 other track")


def s2():
    out = pol.extend_to_recording_start(ev(0.9, 0.03))
    check(out["start"] == 0.0 and out["start_snapped_to_recording_start"] == 0.9, f"S2 {out}")
    check(pol.extend_to_recording_start(ev(1.0, 0.5))["start"] == 0.0, "S2 boundary values")


def s3():
    cases = {
        "start beyond the snap window": ev(1.4, 0.03),
        "track first continuous later": ev(0.9, 0.8),
        "athlete missing at start (refinement)": ev(0.9, 0.03, refinement={"reasons": ["athlete_not_in_frame_at_start"]}),
        "no measurement": ev(0.9, None),
        "teaser": ev(0.9, 0.03, _teaser=True),
        "start already 0": ev(0.0, 0.0),
        "already snapped": ev(0.9, 0.03, start_snapped_to_recording_start=0.9),
        "no refinement": {"start": 0.9, "end": 9.0},
        "garbage": {"start": "x", "window_refinement": {"track_continuous_from_sec": 0.0}},
    }
    for name, event in cases.items():
        check(pol.extend_to_recording_start(event) == event, f"S3 {name}: must not move")
    once = pol.extend_to_recording_start(ev(0.9, 0.03))
    check(pol.extend_to_recording_start(once) == once, "S3 idempotent")


def s4():
    snapped = pol.extend_to_recording_start(ev(0.9, 0.03, setup_start=None))
    snapped.update(final_cut_start=0.0, final_cut_end=9.0)
    check("lead_before_verified_actor" not in oq.action_interval(snapped)["issues"], "S4 snapped start must be a valid lead")
    unsupported = ev(0.0, None)
    unsupported["window_refinement"]["first_track_sec"] = 2.0
    unsupported.update(final_cut_start=0.0, final_cut_end=9.0)
    check("lead_before_verified_actor" in oq.action_interval(unsupported)["issues"], "S4 a lead without presence stays flagged")
    broken = ev(0.0, 1.5)
    broken.update(final_cut_start=0.0, final_cut_end=9.0)
    check("lead_before_verified_actor" in oq.action_interval(broken)["issues"], "S4 presence only from 1.5 s does not validate 0.0")


def s5():
    d = dets("7", [round(0.03 + 0.08 * i, 2) for i in range(160)])                 # present from the first frames to 12.8 s
    event = {"target_track_id": "7", "start": 0.9, "end": 9.0, "setup_start": None}
    refined = wr.refine_event_window(event, d)
    check(refined.get("window_refinement", {}).get("track_continuous_from_sec") == 0.03, f"S5 measurement {refined.get('window_refinement')}")
    snapped = pol.extend_to_recording_start(refined)
    check(snapped["start"] == 0.0, f"S5 snapped {snapped.get('start')}")
    late = {"target_track_id": "7", "start": 4.0, "end": 12.0, "setup_start": None}
    check(pol.extend_to_recording_start(wr.refine_event_window(late, d))["start"] == 4.0, "S5 a start at 4 s is not source-limited")


def s6():
    import json
    import glob
    import os
    run = os.environ.get("SPORTREEL_FROZEN_DIAGNOSTICS", "")
    if not run or not Path(run).exists():
        return                                          # frozen artifacts are optional locally; replay script reports them
    import boundary_start_replay as rep
    result = rep.replay(Path(run))
    check(result["regressions"] == [], f"S6 regressions on frozen rides: {result['regressions']}")
    check(result["moved"] >= 5, f"S6 expected the known late starts to move: {result['moved']}")


for case in (s1, s2, s3, s4, s5, s6):
    try:
        case()
    except Exception as exc:
        import traceback
        FAILURES.append(f"{case.__name__} crashed: {exc!r}\n{traceback.format_exc()[-500:]}")
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("source-start contract: all cases passed")
