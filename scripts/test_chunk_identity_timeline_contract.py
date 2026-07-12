#!/usr/bin/env python3
"""Regression coverage for run 29165422772 chunk identity/timestamp failures."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.chunk_timeline_runtime import merge_chunk_sessions, merge_selector_payloads


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
                    event(11.0, 38.0, "valid first-chunk ride"),
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
    require(len(first_events) == 2, "invalid first-chunk event should be dropped")
    require(first_events[1]["end"] == 480.0, "chunk-boundary event was not clamped")
    require(first_events[1]["timestamp_clamped"] is True, "clamp evidence missing")

    local_event = people["chunk_01:person_A"]["events"][0]
    require((local_event["start"], local_event["end"]) == (496.0, 512.0), "chunk-local timestamps were not shifted exactly once")
    require(local_event["timestamp_basis"] == "chunk_local", "local timestamp basis missing")
    global_event = people["chunk_01:person_B"]["events"][0]
    require((global_event["start"], global_event["end"]) == (520.0, 527.0), "source-global timestamps were shifted twice")
    require(global_event["timestamp_basis"] == "source_global", "global timestamp basis missing")
    boundary_event = people["chunk_01:person_C"]["events"][0]
    require((boundary_event["start"], boundary_event["end"]) == (480.5, 490.5), "ambiguous boundary timestamp chose the unusable local interpretation")
    require(boundary_event["timestamp_basis"] == "source_global", "boundary timestamp basis should be global")

    all_events = [item for person in session["persons"] for item in person["events"]]
    require(all(float(item["end"]) <= source_duration for item in all_events), "event remained beyond source duration")
    diagnostics = session["diagnostics"]["chunk_timeline_contract"]
    require(diagnostics["invalid_timestamp_event_count"] == 1, "invalid timestamp count is wrong")
    require(diagnostics["clamped_timestamp_event_count"] == 1, "clamped timestamp count is wrong")
    require(diagnostics["timestamp_basis_counts"]["source_global"] == 2, "global timestamp basis count is wrong")

    payloads = [
        {"candidates": [candidate("person_A", 546.0, 619.0, "invalid selector event")]},
        {"candidates": [candidate("person_A", 16.0, 32.0, "valid selector event")]},
    ]
    selector = merge_selector_payloads(
        payloads,
        source_video="edited_surf.mp4",
        segment_sec=480.0,
        source_duration_sec=source_duration,
    )
    by_person = {item["person_id"]: item for item in selector["candidates"]}
    invalid = by_person["chunk_00:person_A"]
    require(invalid["discarded"] is True and invalid["selected"] is False, "invalid selected candidate was not converted to an explicit discard")
    require(invalid["discard_cause"] == "timestamp_outside_chunk_bounds", "invalid timestamp reason missing")
    valid = by_person["chunk_01:person_A"]
    require(valid["source_window"]["start"] == 496.0, "selector and analyzer timelines disagree")
    require(valid["source_window"]["end"] == 512.0, "selector end was not normalized")
    require(selector["chunk_timeline_summary"]["person_ids_namespaced"] is True, "multi-chunk selector must namespace local person IDs")

    # A short upload is parsed directly by analyzer and keeps person_A. Selector
    # telemetry must use the same ID rather than inventing chunk_00:person_A.
    short_selector = merge_selector_payloads(
        [{"candidates": [candidate("person_A", 10.0, 24.0, "short single-chunk ride")] }],
        source_video="short_surf.mp4",
        segment_sec=480.0,
        source_duration_sec=120.0,
    )
    short_candidate = short_selector["candidates"][0]
    require(short_candidate["person_id"] == "person_A", "single-chunk selector ID diverged from parsed analyzer ID")
    require(short_candidate["chunk_person_id"] == "person_A", "single-chunk lineage should keep the original local ID")
    require(short_selector["chunk_timeline_summary"]["person_ids_namespaced"] is False, "single-chunk selector incorrectly reported namespacing")

    print("chunk identity and timeline contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
