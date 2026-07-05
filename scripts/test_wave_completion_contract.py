#!/usr/bin/env python3
from __future__ import annotations

from pipeline.draft_diagnostics import build_diagnostic_artifact
from pipeline.surf_ride_segment import normalize_surf_rides
from pipeline.wave_completion import annotate_wave_completion, build_wave_boundary_evidence, wave_completion_score


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(msg)


def main() -> int:
    complete = annotate_wave_completion({
        "event_id": "ride_complete",
        "type": "surf_ride",
        "description": "surfer completes a cutback and rides out",
        "start": 10,
        "end": 24,
        "ride_start": 10,
        "peak_time": 17,
        "outcome_end": 24,
    }, "surfing")
    require(complete.get("wave_completion_score") == 1.0, "complete ride should score 1.0")
    require(complete.get("wave_completion_status") == "complete", "complete ride should not require review")
    require("qa_gate" not in complete, "complete ride should not get QA review gate")

    missing = annotate_wave_completion({
        "event_id": "ride_missing_end",
        "type": "surf_ride",
        "description": "surfer rides wave with turn",
        "start": 30,
        "end": 36,
        "ride_start": 30,
        "peak_time": 33,
    }, "surfing")
    require(missing.get("wave_completion_status") == "review_required", "missing outcome should require review")
    defects = missing.get("wave_completion_defects", [])
    require(any(d.get("type") == "WAVE_COMPLETION_UNCERTAIN" for d in defects), "missing outcome defect missing")
    require(missing.get("qa_gate", {}).get("qa_review_required") is True, "missing outcome must set qa_review_required")

    early = annotate_wave_completion({
        "event_id": "ride_cut_early",
        "type": "surf_ride",
        "description": "surfer rides wave",
        "start": 50,
        "end": 58,
        "ride_start": 50,
        "peak_time": 55,
        "outcome_end": 62,
        "final_cut_start": 50,
        "final_cut_end": 58,
    }, "surfing")
    require(early.get("wave_completion_status") == "review_required", "early cut should require review")
    require(any(d.get("type") == "CUT_TOO_EARLY" for d in early.get("wave_completion_defects", [])), "CUT_TOO_EARLY defect missing")

    merged = normalize_surf_rides([
        {"event_id": "frag_a", "type": "cutback", "description": "surfer rides wave", "_src": "raw/a.mp4", "start": 1, "end": 5, "score": 7, "track_id": "t1"},
        {"event_id": "frag_b", "type": "carve", "description": "surfer rides wave", "_src": "raw/a.mp4", "start": 6, "end": 9, "score": 8, "track_id": "t1"},
    ], "surfing")
    require(len(merged) == 1, "ride fragments should merge before completion scoring")
    ride = merged[0]
    require("wave_completion_score" in ride, "merged ride missing wave_completion_score")
    require("wave_boundary_evidence" in ride, "merged ride missing boundary evidence")
    require(ride.get("wave_completion_status") == "review_required", "merged ride without outcome should require review")

    evidence = build_wave_boundary_evidence(complete, "surfing")
    require(wave_completion_score(evidence) == 1.0, "score helper should return full score for full evidence")

    artifact = build_diagnostic_artifact("DRAFT_wave.mp4", "surfing", [missing], {}, "review/DRAFT_wave.mp4")
    ordered = artifact["ordered_events"][0]
    require("wave_completion_score" in ordered, "diagnostic ordered event missing score")
    require("wave_boundary_evidence" in ordered, "diagnostic ordered event missing boundary evidence")
    require(any(item.get("reason") == "WAVE_COMPLETION_UNCERTAIN" for item in artifact["dropped_events"]), "diagnostic artifact missing wave review reason")

    print("wave completion contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
