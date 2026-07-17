#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def ev(event_id, start, end, score=8, track_id="t1", **extra):
    event = {"event_id": event_id, "type": "cutback", "description": "surfer rides wave", "_src": "raw/source.mp4", "start": start, "end": end, "score": score}
    if track_id is not None:
        event["track_id"] = track_id
    event.update(extra)
    return event


def main() -> int:
    from pipeline.surf_ride_segment import normalize_surf_rides

    merged = normalize_surf_rides([ev("a", 10, 16), ev("b", 17, 25, score=9, outcome_end=28)], "surfing")
    if len(merged) != 1:
        raise SystemExit("adjacent fragments of one wave must merge")
    ride = merged[0]
    if ride.get("type") != "surf_ride" or ride.get("start") != 10 or ride.get("end") != 28:
        raise SystemExit("merged ride must span full source window")
    if ride.get("ride_fragment_count") != 2 or not ride.get("merged_ride_fragments"):
        raise SystemExit("merged ride diagnostics missing")

    uncertain = normalize_surf_rides([ev("c", 30, 35, track_id=None)], "surfing")[0]
    if not uncertain.get("ride_boundary_uncertain") or not uncertain.get("identity_uncertain"):
        raise SystemExit("missing ride/identity uncertainty")
    defects = uncertain.get("ride_qa_defects", [])
    types = {d.get("type") for d in defects}
    if {"RIDE_BOUNDARY_UNCERTAIN", "IDENTITY_UNCERTAIN"} - types:
        raise SystemExit("uncertain ride defects missing")
    if not uncertain.get("dedup_dropped_duplicates"):
        raise SystemExit("ride defects must surface to QA evidence")

    separate = normalize_surf_rides([ev("d", 1, 4), ev("e", 30, 34)], "surfing")
    if len(separate) != 2:
        raise SystemExit("distant waves must not merge")

    text = (ROOT / "pipeline/surf_ride_segment.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    for token in ["normalize_surf_rides", "RIDE_BOUNDARY_UNCERTAIN", "IDENTITY_UNCERTAIN", "merged_ride_fragments"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")
    if "pipeline.surf_ride_gate" not in boot:
        raise SystemExit("surf ride gate is not bootstrapped")

    print("Surf ride continuity contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
