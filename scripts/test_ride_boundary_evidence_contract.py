#!/usr/bin/env python3
"""A ride whose `end` the analyzer backed with timing evidence is not "inferred from fragments".

Run 42814819534: 11 of 12 reels carried the blocking context defect RIDE_BOUNDARY_UNCERTAIN ("ride end was
inferred from fragments"), most of them on a single-fragment ride. The analyzer prompt makes `end` the observed
ride end, requires `timing_evidence` naming what is visible at it, and tells the model to omit outcome_end
unless it differs from `end`; cut_window_guard already treats that end as exact. surf_ride_segment treated the
same end as missing. The uncertainty must stay for every end that really is unknown.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVIDENCE = "start 1.5s: pops up on the board; end 9.0s: falls off as the wave closes out"


def ride(event_id, start, end, **extra):
    # Shape of an analyzer event (_parse_session): phase fields present but None when the model omitted them.
    event = {"event_id": event_id, "type": "wave_catch", "description": "rides a wave down the line",
             "_src": "raw/0070.MP4", "start": start, "end": end, "score": 8, "track_id": "7",
             "setup_start": None, "peak_time": None, "outcome_end": None,
             "timing_evidence": EVIDENCE, "timing_precise": True}
    event.update(extra)
    return event


def types(event):
    return {d.get("type") for d in event.get("ride_qa_defects", []) or []}


def main() -> int:
    from pipeline.source_evidence_runner import _context_defects
    from pipeline.surf_ride_segment import normalize_surf_rides
    from pipeline.context_qa_gate import build_edit_context

    # The production case: one evidence-backed fragment.
    single = normalize_surf_rides([ride("a", 1.5, 9.0)], "surfing")[0]
    if single.get("ride_boundary_uncertain") or "RIDE_BOUNDARY_UNCERTAIN" in types(single):
        raise SystemExit("an evidence-backed ride end was reported as inferred from fragments (run 42814819534)")
    if single.get("ride_end") != 9.0 or single.get("ride_end_evidence") != "timing_evidence":
        raise SystemExit(f"the evidence-backed end must become the ride end with its provenance, got {single.get('ride_end')}")
    if single.get("wave_completion_status") != "complete":
        raise SystemExit(f"wave completion must see the evidence-backed end, got {single.get('wave_completion_status')}")
    blocking = {d["type"] for d in _context_defects(build_edit_context("reel.mp4", [single]))}
    if "RIDE_BOUNDARY_UNCERTAIN" in blocking:
        raise SystemExit("QA context still blocks the reel on an evidence-backed ride end")

    # Merged fragments: the fragment that defines the end decides.
    merged = normalize_surf_rides([ride("b", 1.0, 6.0, timing_precise=False, timing_evidence=None), ride("c", 8.0, 14.0)], "surfing")[0]
    if merged.get("ride_boundary_uncertain") or merged.get("end") != 14.0:
        raise SystemExit("a merged ride whose last fragment has end evidence must not be uncertain")
    early_only = normalize_surf_rides([ride("d", 1.0, 6.0), ride("e", 8.0, 14.0, timing_precise=False, timing_evidence=None)], "surfing")[0]
    if not early_only.get("ride_boundary_uncertain"):
        raise SystemExit("evidence on an EARLIER fragment says nothing about the merged ride's end")

    # Ends that really are unknown stay uncertain and blocking.
    unknown = [
        ("no timing evidence (legacy cached response)", ride("f", 1.0, 8.0, timing_precise=False, timing_evidence=None)),
        ("flag without evidence text", ride("g", 1.0, 8.0, timing_evidence="")),
        ("end moved to where the track was lost", ride("h", 1.0, 8.0, window_refined=True,
                                                         window_refinement={"status": "trimmed", "reasons": ["track_lost_before_end"]})),
        ("tail padding", ride("i", 1.0, 8.0, cut_window_evidence_status="inferred_tail_padding")),
    ]
    for why, event in unknown:
        out = normalize_surf_rides([event], "surfing")[0]
        if not out.get("ride_boundary_uncertain") or "RIDE_BOUNDARY_UNCERTAIN" not in types(out):
            raise SystemExit(f"ride end must stay uncertain: {why}")
    trimmed_start = normalize_surf_rides([ride("j", 2.0, 8.0, window_refined=True,
                                               window_refinement={"status": "trimmed", "reasons": ["athlete_not_in_frame_at_start"]})], "surfing")[0]
    if trimmed_start.get("ride_boundary_uncertain"):
        raise SystemExit("a start-only refinement leaves the evidence-backed end intact")

    print("ride boundary evidence contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
