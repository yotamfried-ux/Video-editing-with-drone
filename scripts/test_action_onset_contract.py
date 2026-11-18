#!/usr/bin/env python3
"""Cycle 11 FIX-PQ-11-001: motion-supported action onset (Core) with profile parameters (surfing + football).

O1  surf paddle-in on FRAGMENTED tracks (track 3 then 7 then the actor 10, as 0115) moving from 0.5 s: the onset walks
    back through the stitched tracklets to the analyzer's setup (0.5 s) - beyond the 2 s lead-in cap.
O2  surf waiting (as 0140): stationary from 0 to 2.5 s, moving after -> onset stops at the moving part (>= 2.4 s);
    never opens on the wait.
O3  a profile that does not require motion (generic) -> None (callers keep the legacy rule).
O4  football profile, a player running onto the ball while two stationary team-mates stand nearby -> the onset
    follows the target player's run only; the other people neither extend nor block it.
O5  integration: window_refinement records onset_motion_from_sec; complete_action_window_policy.extend_to_setup opens
    the cut there for O1 and keeps the capped legacy start for O2; output_qualification does not flag the longer lead
    as lead_before_verified_actor.
O6  no evidence (track missing) -> no change.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.action_onset import motion_supported_onset, stitched_actor_detections  # noqa: E402
from pipeline.perception.schema import PerceptionDetection  # noqa: E402
from pipeline.sport_profiles import GENERIC, profile_for  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def det(t, track, x, y, h=200, w=None, name="person"):
    w = w or h * 0.6
    return PerceptionDetection(source_video="s.mp4", frame_index=int(t * 30), time_sec=round(t, 2),
                               xyxy=(x, y, x + w, y + h), frame_width=3840, frame_height=2160, confidence=0.9,
                               class_id=0, class_name=name, tracker_id=track)


def path(t0, t1, track, x0, y0, vx, vy, step=0.2, h=200):
    out, t = [], t0
    while t <= t1 + 1e-9:
        out.append(det(t, track, x0 + vx * (t - t0), y0 + vy * (t - t0), h=h))
        t += step
    return out


def main() -> int:
    surf, foot = profile_for("surfing"), profile_for("football")
    # O1 paddler moving 120 px/s (0.6 body heights/s) on three tracklets
    paddle = path(0.0, 1.9, 3, 1000, 1500, -120, -40) + path(2.1, 3.4, 7, 772, 1416, -120, -40) \
        + path(3.6, 8.0, 10, 592, 1356, -120, -40)
    chain = stitched_actor_detections(paddle, 10)
    check(chain and chain[0].time_sec == 0.0, f"O1 stitched back through tracklets to 0.0 s (got {chain[0].time_sec if chain else None})")
    res = motion_supported_onset(paddle, 10, start=4.0, setup=0.5, policy=surf.onset)
    check(res and res["onset_sec"] <= 1.0, f"O1 onset reaches the setup region beyond the 2 s cap ({res})")
    # O2 waiting: stationary 0..2.5 s, then moving
    wait = path(0.0, 2.5, 5, 1000, 1500, 0, 0) + path(2.6, 8.0, 5, 1000, 1500, -150, -50)
    res2 = motion_supported_onset(wait, 5, start=4.4, setup=0.5, policy=surf.onset)
    check(res2 is None or res2["onset_sec"] >= 2.4, f"O2 onset never opens on the stationary wait ({res2})")
    # O3
    check(motion_supported_onset(paddle, 10, start=4.0, setup=0.5, policy=GENERIC.onset) is None,
          "O3 a profile without a motion build-up returns None")
    # O4 football: target runs from 1.0 s; two team-mates stand still close by
    target = path(0.0, 1.0, 21, 1800, 1000, 0, 0, h=180) + path(1.1, 6.0, 21, 1800, 1000, 140, 10, h=180)
    mates = path(0.0, 6.0, 22, 1700, 980, 0, 0, h=180) + path(0.0, 6.0, 23, 1950, 1030, 0, 0, h=180)
    res4 = motion_supported_onset(target + mates, 21, start=4.0, setup=0.0, policy=foot.onset)
    check(res4 is not None and 0.9 <= res4["onset_sec"] <= 2.1,
          f"O4 football run-up onset follows the target only (~1-2 s): {res4}")
    # O6
    check(motion_supported_onset(paddle, 999, start=4.0, setup=0.5, policy=surf.onset) is None, "O6 missing track -> None")

    # O5 integration through the production window code
    from pipeline import complete_action_window_policy as cap, window_refinement as wr
    from pipeline import output_qualification as oq
    ev = {"start": 4.0, "end": 8.0, "setup_start": 0.5, "target_track_id": 10, "sport": "surfing", "type": "wave_catch"}
    refined = wr.refine_event_window(ev, paddle)
    r = refined.get("window_refinement") or {}
    check(r.get("onset_motion_from_sec") is not None and r["onset_motion_from_sec"] <= 1.0,
          f"O5 window_refinement records the onset ({r.get('onset_motion_from_sec')})")
    out = cap.extend_to_setup(refined)
    check(abs(float(out["start"]) - 0.5) < 0.11, f"O5 extend_to_setup opens at the setup through the moving build-up ({out['start']})")
    ev2 = {"start": 4.4, "end": 8.0, "setup_start": 0.5, "target_track_id": 5, "sport": "surfing", "type": "wave_catch"}
    out2 = cap.extend_to_setup(wr.refine_event_window(ev2, wait))
    check(float(out2["start"]) >= 2.39, f"O5 waiting stays outside the cut (start {out2['start']} >= 2.4)")
    interval = oq.action_interval({**out, "event_uid": "ev2_x", "event_source_ref": "sha256:x"})
    check("lead_before_verified_actor" not in (interval.get("issues") or []),
          f"O5 the stitched moving lead is verified actor evidence ({interval.get('issues')})")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
