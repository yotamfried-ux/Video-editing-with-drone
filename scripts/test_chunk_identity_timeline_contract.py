#!/usr/bin/env python3
"""Regression coverage for chunk identity and timestamp normalization."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.chunk_timeline_runtime import (
    merge_chunk_sessions,
    merge_selector_payloads,
    normalize_chunk_window,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def event(start: float, end: float, description: str) -> dict:
    return {
        "type": "wave_catch",
        "start": start,
        "end": end,
        "score": 8,
        "description": description,
        "edit": {"zoom": 1.2, "slowmo": False, "focus": "full", "transition_out": "cut"},
    }


def candidate(person_id: str, start: float, end: float, description: str) -> dict:
    return {
        "person_id": person_id,
        "person_description": description,
        "selected": True,
        "discarded": False,
        "event_type": "wave_catch",
        "score": 8,
        "source_window": {"start": start, "end": end, "duration": end - start},
        "description": description,
    }


def main() -> int:
    source_duration = 548.9
    chunks = [
        {
            "activity": "surfing",
            "persons": [{
                "id": "person_A",
                "description": "black shorts on dark board",
                "events": [
                    event(11.0, 38.0, "valid decimal-seconds ride"),
                    event(2.00, 2.52, "production MM.SS ride 2:00 to 2:52"),
                    event(7.39, 7.55, "production MM.SS ride 7:39 to 7:55"),
                    event(453.0, 516.0, "ride crosses chunk boundary and must clamp"),
                    event(546.0, 619.0, "hallucinated timestamp outside first chunk"),
                ],
            }],
            "style": {},
            "session_peak": 8,
        },
        {
            "activity": "surfing",
            "persons": [
                {
                    "id": "person_A",
                    "description": "pink swimsuit on pink board",
                    "events": [event(16.0, 32.0, "chunk-local second-chunk ride")],
                },
                {
                    "id": "person_B",
                    "description": "black shorts on turquoise board",
                    "events": [event(520.0, 527.0, "source-global timestamp returned by model")],
                },
                {
                    "id": "person_C",
                    "description": "white shirt near chunk boundary",
                    "events": [event(480.5, 490.5, "global event at the exact chunk boundary")],
                },
                {
                    "id": "person_D",
                    "description": "global MM.SS event in second chunk",
                    "events": [event(8.12, 8.30, "source-global 8:12 to 8:30")],
                },
            ],
            "style": {},
            "session_peak": 9,
        },
    ]
    session = merge_chunk_sessions(
        chunks,
        segment_sec=480.0,
        source_duration_sec=source_duration,
        source_video="edited_surf.mp4",
    )

    people = {person["id"]: person for person in session["persons"]}
    require("chunk_00:person_A" in people, "first chunk person ID was not namespaced")
    require("chunk_01:person_A" in people, "second chunk reused person_A globally")
    require(people["chunk_00:person_A"]["description"] != people["chunk_01:person_A"]["description"], "different athletes were conflated")

    first_events = people["chunk_00:person_A"]["events"]
    require(len(first_events) == 4, "invalid first-chunk event should be the only dropped event")
    by_description = {item["description"]: item for item in first_events}
    recovered_200 = by_description["production MM.SS ride 2:00 to 2:52"]
    require((recovered_200["start"], recovered_200["end"]) == (120.0, 172.0), "2.00-2.52 was not recovered as 2:00-2:52")
    require(recovered_200["timestamp_encoding"] == "minute_second", "MM.SS encoding evidence missing")
    require(recovered_200["timestamp_recovered"] is True, "MM.SS recovery flag missing")
    recovered_739 = by_description["production MM.SS ride 7:39 to 7:55"]
    require((recovered_739["start"], recovered_739["end"]) == (459.0, 475.0), "7.39-7.55 was not recovered as 7:39-7:55")
    clamped = by_description["ride crosses chunk boundary and must clamp"]
    require(clamped["end"] == 480.0 and clamped["timestamp_clamped"] is True, "chunk-boundary event was not clamped")

    local_event = people["chunk_01:person_A"]["events"][0]
    require((local_event["start"], local_event["end"]) == (496.0, 512.0), "chunk-local timestamps were not shifted exactly once")
    require(local_event["timestamp_encoding"] == "decimal_seconds", "valid decimal seconds should remain authoritative")
    global_event = people["chunk_01:person_B"]["events"][0]
    require((global_event["start"], global_event["end"]) == (520.0, 527.0), "source-global timestamps were shifted twice")
    boundary_event = people["chunk_01:person_C"]["events"][0]
    require((boundary_event["start"], boundary_event["end"]) == (480.5, 490.5), "ambiguous boundary timestamp chose the unusable local interpretation")
    global_mmss = people["chunk_01:person_D"]["events"][0]
    require((global_mmss["start"], global_mmss["end"]) == (492.0, 510.0), "8.12-8.30 was not recovered as source-global 8:12-8:30")
    require(global_mmss["timestamp_basis"] == "source_global", "global MM.SS basis missing")

    all_events = [item for person in session["persons"] for item in person["events"]]
    require(all(float(item["end"]) <= source_duration for item in all_events), "event remained beyond source duration")
    diagnostics = session["diagnostics"]["chunk_timeline_contract"]
    require(diagnostics["invalid_timestamp_event_count"] == 1, "invalid timestamp count is wrong")
    require(diagnostics["clamped_timestamp_event_count"] == 1, "clamped timestamp count is wrong")
    require(diagnostics["minute_second_recovered_event_count"] == 3, "MM.SS recovery count is wrong")
    require(diagnostics["timestamp_encoding_counts"]["minute_second"] == 3, "MM.SS encoding summary missing")

    # This window crosses the chunk boundary but leaves fewer than four usable
    # seconds after clamp. It is invalid, yet diagnostics must retain that clamp.
    rejected_after_clamp = normalize_chunk_window(
        478.5,
        482.0,
        {"chunk_index": 0, "source_start": 0.0, "duration": 480.0, "source_end": 480.0},
        min_duration_sec=4.0,
    )
    require(rejected_after_clamp["valid"] is False, "short clamped window should be rejected")
    require(rejected_after_clamp["reason"] == "insufficient_time_inside_chunk", "short clamped rejection reason is wrong")
    require(rejected_after_clamp["timestamp_clamped"] is True, "rejected window lost clamp evidence")

    payloads = [
        {"candidates": [
            candidate("person_A", 546.0, 619.0, "invalid selector event"),
            candidate("person_F", 478.5, 482.0, "clamped invalid selector event"),
            candidate("person_E", 7.39, 7.55, "recovered selector wave"),
        ]},
        {"candidates": [candidate("person_A", 16.0, 32.0, "valid selector event")]},
    ]
    selector = merge_selector_payloads(
        payloads,
        source_video="edited_surf.mp4",
        segment_sec=480.0,
        source_duration_sec=source_duration,
    )
    invalid = next(item for item in selector["candidates"] if item["description"] == "invalid selector event")
    require(invalid["discarded"] is True and invalid["discard_cause"] == "timestamp_outside_chunk_bounds", "invalid selected candidate was not explicitly discarded")
    clamped_invalid = next(item for item in selector["candidates"] if item["description"] == "clamped invalid selector event")
    require(clamped_invalid["discarded"] is True, "clamped invalid selector candidate was not discarded")
    require(clamped_invalid["timestamp_validation"]["timestamp_clamped"] is True, "selector discard lost clamp evidence")
    recovered = next(item for item in selector["candidates"] if item["description"] == "recovered selector wave")
    require(recovered["selected"] is True and recovered["source_window"] == {"start": 459.0, "end": 475.0, "duration": 16.0}, "MM.SS selector candidate was not recovered")
    require(recovered["raw_timestamp_window"] == {"start": 7.39, "end": 7.55}, "raw MM.SS evidence missing")
    require(selector["chunk_timeline_summary"]["minute_second_recovered_candidate_count"] == 1, "selector recovery count missing")

    short_selector = merge_selector_payloads(
        [{"candidates": [candidate("person_A", 10.0, 24.0, "short single-chunk ride")]}],
        source_video="short_surf.mp4",
        segment_sec=480.0,
        source_duration_sec=120.0,
    )
    short_candidate = short_selector["candidates"][0]
    require(short_candidate["person_id"] == "person_A", "single-chunk selector ID diverged from analyzer ID")
    require(short_candidate["timestamp_encoding"] == "decimal_seconds", "usable decimal window was incorrectly converted to MM.SS")
    require(short_selector["chunk_timeline_summary"]["person_ids_namespaced"] is False, "single-chunk selector incorrectly reported namespacing")

    print("chunk identity and timeline contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
