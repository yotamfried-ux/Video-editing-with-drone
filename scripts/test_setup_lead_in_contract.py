#!/usr/bin/env python3
"""A ride's cut opens on the catch and pop-up the analyzer reported as setup_start, not on a standing athlete.

Run 43203677423 against the manual catalog (ground_truth, 22 drafted sources): cuts started a median 1.6 s after
the catalogued ride start, 40.7 s of usable ride starts were lost, and no cut started before the catalogued ride.
The analyzer already reports setup_start ("paddle into position, takeoff") on 13 of those 22, matching the catalog
(median 0.5 s). window_policy.resolve_window applied it, but that wrapper is no longer on the production path.

1. Window refinement records where the target track is first seen between setup_start and start.
2. The cut opens at setup_start, at most SETUP_LEAD_IN_MAX_SEC (QA's DEAD_TIME bound) before start, never before
   the athlete is tracked; without that evidence, or when refinement trimmed the start, it does not move.
3. Normalization runs more than once on the same event: the lead-in is applied once.
4. On the run's catalogued starts the rule recovers usable start seconds and adds none outside the catalog.
"""
from __future__ import annotations

import sys
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"setup lead-in contract FAILED: {msg}")


def main() -> int:
    from pipeline.complete_action_window_policy import (
        SETUP_LEAD_IN_MAX_SEC, extend_to_setup, normalize_complete_action_event)
    from pipeline.perception.schema import PerceptionDetection
    from pipeline.window_refinement import refine_event_window

    if SETUP_LEAD_IN_MAX_SEC > 2.0:
        fail("the lead-in must stay within QA's DEAD_TIME definition (> ~2 s)")

    def det(track: int, t: float) -> PerceptionDetection:
        return PerceptionDetection(source_video="DJI_0070_D.MP4", frame_index=int(t * 30), time_sec=t,
                                   xyxy=(100, 100, 160, 200), frame_width=1280, frame_height=720,
                                   confidence=0.9, class_id=0, class_name="person", tracker_id=track)

    # 0070: analyzer start 2.5 s ("stands up fully"), setup_start 0.5 s; catalog ride from 0.0 s.
    detections = [det(7, 0.4 + 0.1 * i) for i in range(0, 180)]
    event = {"start": 2.5, "end": 18.2, "setup_start": 0.5, "target_track_id": "7", "type": "wave_catch"}
    refined = refine_event_window(event, detections)
    first = (refined.get("window_refinement") or {}).get("setup_first_track_sec")
    if first is None or abs(first - 0.4) > 0.05:
        fail(f"refinement must record where the track is first seen after setup_start: {refined.get('window_refinement')}")
    opened = extend_to_setup(refined)
    if abs(float(opened["start"]) - 0.5) > 1e-6 or opened.get("start_before_setup_lead_in") != 2.5:
        fail(f"the cut opens at setup_start 0.5 s: {opened.get('start')}")

    late_track = refine_event_window(event, [det(7, 1.6 + 0.1 * i) for i in range(0, 170)])
    if abs(float(extend_to_setup(late_track)["start"]) - 1.3) > 0.06:
        fail("the cut never opens more than the margin before the athlete is first tracked")
    far = refine_event_window({**event, "start": 6.5, "setup_start": 1.0},
                              [det(7, 0.6 + 0.1 * i) for i in range(0, 175)])
    if abs(float(extend_to_setup(far)["start"]) - 4.5) > 1e-6:
        fail("at most SETUP_LEAD_IN_MAX_SEC of lead-in (0115: 5.5 s of paddling is dead time)")
    if extend_to_setup({**event})["start"] != 2.5:
        fail("without tracking evidence for the lead-in the start does not move")
    trimmed = {**opened, "start": 2.5, "start_before_setup_lead_in": None,
               "window_refinement": {**opened["window_refinement"], "reasons": ["athlete_not_in_frame_at_start"]}}
    if extend_to_setup(trimmed)["start"] != 2.5:
        fail("when refinement moved the start because the athlete was not in frame, the lead-in is not applied")
    if extend_to_setup({**refined, "_teaser": True})["start"] != 2.5:
        fail("a teaser keeps its window")

    twice = normalize_complete_action_event(normalize_complete_action_event(dict(refined)))
    if abs(float(twice["start"]) - 0.5) > 1e-6:
        fail(f"normalizing twice applies the lead-in once: {twice['start']}")
    perf = normalize_complete_action_event({**refined, "performance_reel_contract": "all_usable_waves_per_athlete_v1"})
    if abs(float(perf.get("final_cut_start", -1)) - 0.5) > 1e-6:
        fail("the persisted final cut window (renderer and QA) carries the lead-in")

    # Run 43203677423, catalogued starts: (source, analyzer start, setup_start, catalogued ride start).
    rows = [("0070", 2.5, 0.5, 0.0), ("0074", 2.8, 0.5, 0.0), ("0094", 3.5, 0.5, 0.0), ("0097", 2.0, 1.4, 0.0),
            ("0108", 1.5, None, 0.0), ("0112", 1.5, 0.5, 0.0), ("0115", 6.5, 1.0, 0.07), ("0118", 2.0, 1.0, 0.0),
            ("0126", 0.9, 0.0, 0.0), ("0130", 1.4, None, 0.0), ("0131", 0.0, None, 0.0), ("0140", 3.4, None, 1.77),
            ("0142", 3.2, 0.0, 0.0), ("0143", 0.0, None, 0.0), ("0104", 2.7, None, 0.02), ("0146", 2.8, 0.5, 0.0),
            ("0151", 0.0, None, 0.0), ("0152", 5.0, 3.5, 3.42), ("0160", 3.5, 2.5, 2.12), ("0162", 1.8, None, 0.03),
            ("0163", 1.0, 0.0, 0.0), ("0165", 0.1, None, 0.0)]
    before, after = [], []
    for _src, start, setup, catalog_start in rows:
        ev = {"start": start, "end": start + 8.0, "window_refinement": {"status": "unchanged"}}
        if setup is not None:
            ev.update(setup_start=setup, window_refinement={"status": "unchanged", "setup_first_track_sec": setup})
        before.append(start - catalog_start)
        after.append(float(extend_to_setup(ev)["start"]) - catalog_start)
    missed_before = sum(max(0.0, d) for d in before)
    missed_after = sum(max(0.0, d) for d in after)
    outside = sum(max(0.0, -d) for d in after)
    if not (missed_after < missed_before - 15.0 and outside == 0.0 and statistics.median(after) < statistics.median(before)):
        fail(f"catalog: usable start seconds missed {missed_before:.1f} -> {missed_after:.1f}, outside {outside:.1f}")
    print(f"setup lead-in contract ok (catalog: usable start seconds missed {missed_before:.1f} -> {missed_after:.1f}, "
          f"median start gap {statistics.median(before):.2f} -> {statistics.median(after):.2f} s, 0 s outside)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
