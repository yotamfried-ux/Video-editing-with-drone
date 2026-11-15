#!/usr/bin/env python3
"""Retention audit of 2026-11-15 (PR #385): measure first, change the edit only behind a flag.

1. Metrics are computed from the EDL and the per-clip records, and a measurement that cannot be made is null.
2. With no flag set the opening fade and the clip order are exactly what they were.
3. `SPORTREEL_REEL_FADE_IN_SEC` changes the opening fade only within 0–1 s.
4. `SPORTREEL_HOOK_COMPLETE_OPENER` only reorders: among clips rated within a point, a ride that resolves inside
   its recording opens instead of one the camera cut; every clip is still there once, and the climax stays last.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def record(start_frame: int, track_offsets_sec: list[float], *, ends: bool | None, lead_in: float | None, fps: float = 60.0) -> dict:
    return {
        "src_start_frame": start_frame, "source": {"fps": fps}, "event_type": "surf_ride",
        "subject_track": [{"src_frame": start_frame + int(round(t * fps))} for t in track_offsets_sec],
        "ends_with_recording": ends, "setup_lead_in_sec": lead_in,
    }


def main() -> int:
    from pipeline import narrative_policy, retention_metrics as rm

    for key in ("SPORTREEL_REEL_FADE_IN_SEC", "SPORTREEL_HOOK_COMPLETE_OPENER"):
        os.environ.pop(key, None)

    # 1. metrics
    edl = {"output_id": "reel_a", "run_id": "r", "pipeline_commit": "c",
           "output": {"fps": 30.0, "duration_sec": 20.0},
           "shots": [{"out_start": 0, "out_end": 360, "mode": "follow_crop"},
                     {"out_start": 360, "out_end": 600, "mode": "contain"}],
           "fades": [{"kind": "in", "sec": 0.25}, {"kind": "out", "sec": 0.4}]}
    tracked_from_half_second = record(600, [0.5, 0.6, 0.8, 1.2, 2.0], ends=False, lead_in=2.1)
    metrics = rm.reel_metrics(edl, [tracked_from_half_second, record(0, [0.0], ends=True, lead_in=None)])
    expected = {"shot_count": 2, "first_shot_sec": 12.0, "longest_shot_sec": 12.0, "opening_fade_in_sec": 0.25,
                "first_1s_actor_visibility": 0.5, "time_to_tracked_actor_sec": 0.5, "opening_lead_in_sec": 2.1,
                "time_to_visible_action_sec": 2.1, "unresolved_final_action": True, "shots_ending_with_recording": 1,
                "framing_modes": ["contain", "follow_crop"], "event_types": ["surf_ride"]}
    for key, value in expected.items():
        if metrics[key] != value:
            raise SystemExit(f"{key}: expected {value!r}, got {metrics[key]!r}")

    untracked = rm.reel_metrics({**edl, "shots": edl["shots"][:1]}, [record(0, [], ends=None, lead_in=None)])
    for key in ("first_1s_actor_visibility", "time_to_tracked_actor_sec", "time_to_visible_action_sec", "unresolved_final_action"):
        if untracked[key] is not None:
            raise SystemExit(f"{key} must be null without evidence, got {untracked[key]!r}")

    with tempfile.TemporaryDirectory() as folder:
        if rm.write_reel_metrics(edl, [tracked_from_half_second, None], Path(folder)) is None:
            raise SystemExit("metrics were not written")
        line = json.loads((Path(folder) / rm.FILE_NAME).read_text().splitlines()[0])
        if line["schema"] != rm.SCHEMA or line["output_id"] != "reel_a":
            raise SystemExit(f"unexpected metrics line: {line}")

    # 2 + 3. opening fade
    if rm.reel_fade_in_sec() != 0.25:
        raise SystemExit("the opening fade must stay 0.25 s when no flag is set")
    for raw, want in (("0", 0.0), ("0.1", 0.1), ("5", 0.25), ("-1", 0.25), ("abc", 0.25), ("", 0.25)):
        os.environ["SPORTREEL_REEL_FADE_IN_SEC"] = raw
        if rm.reel_fade_in_sec() != want:
            raise SystemExit(f"SPORTREEL_REEL_FADE_IN_SEC={raw!r}: expected {want}, got {rm.reel_fade_in_sec()}")
    os.environ.pop("SPORTREEL_REEL_FADE_IN_SEC")

    # 2 + 4. clip order
    cut_by_camera = {"A", "C"}
    narrative_policy._ends_with_recording = lambda event: event["name"] in cut_by_camera

    def ride(name: str, score: float) -> dict:
        return {"name": name, "score": score, "track_id": 1, "peak_time": 1.0}

    rides = [ride("A", 8.0), ride("B", 7.5), ride("C", 7.0), ride("D", 9.0)]
    default = [e["name"] for e in narrative_policy.order_events(rides)]
    if default != ["A", "C", "B", "D"]:
        raise SystemExit(f"default order changed: {default}")
    os.environ["SPORTREEL_HOOK_COMPLETE_OPENER"] = "1"
    flagged = [e["name"] for e in narrative_policy.order_events(rides)]
    os.environ.pop("SPORTREEL_HOOK_COMPLETE_OPENER")
    if flagged != ["B", "C", "A", "D"]:
        raise SystemExit(f"with the flag a resolved ride within a point opens the reel: {flagged}")
    if sorted(flagged) != sorted(default) or flagged[-1] != "D":
        raise SystemExit("the flag may only reorder: every ride once, climax last")

    print("PASS: retention metrics are observational; fade and opener change only behind their flags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
