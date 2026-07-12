#!/usr/bin/env python3
"""Prove MM.SS recovery happens before analyzer/selector fragment filtering."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.raw_timestamp_recovery import (
    annotate_parsed_session,
    enrich_selector_payload,
    recover_raw_session_payload,
)
from pipeline.stages.selector_candidates import build_selector_candidate_events


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def raw_event(start: float, end: float, score: int, description: str) -> dict:
    return {
        "type": "wave_catch",
        "start": start,
        "end": end,
        "score": score,
        "description": description,
        "crop_x": 0.5,
        "crop_y": 0.7,
        "edit": {"zoom": 1.2, "slowmo": False, "focus": "full", "transition_out": "cut"},
    }


def main() -> int:
    production_windows = [
        (2.00, 2.52, 8, "two minute ride"),
        (3.00, 3.32, 7, "three minute ride"),
        (4.01, 4.21, 7, "four minute ride"),
        (5.46, 6.19, 9, "five minute ride"),
        (4.52, 5.17, 8, "late four minute ride"),
        (7.03, 7.35, 8, "seven minute ride"),
        (0.11, 0.38, 7, "opening ride"),
        (0.52, 1.06, 8, "one minute transition ride"),
        (1.07, 1.21, 7, "one minute ride"),
        (2.08, 2.23, 7, "second two minute ride"),
        (7.39, 7.55, 9, "known 459 to 475 ride"),
        # Exactly five recovered seconds: core parser keeps it but pads its end
        # to the six-second editor minimum before annotation.
        (2.00, 2.05, 7, "padded five second ride"),
    ]
    payload = {
        "activity": "surfing",
        "session_peak": 9,
        "style": {"visual": "bright", "pace": "moderate", "density": "high"},
        "persons": [{
            "id": "person_A",
            "description": "surfer in dark shorts on turquoise board",
            "events": [raw_event(*item) for item in production_windows] + [
                raw_event(16.0, 32.0, 8, "valid decimal event"),
                raw_event(2.75, 2.90, 8, "invalid compact time"),
            ],
        }],
    }
    raw_text = json.dumps(payload)
    recovered = recover_raw_session_payload(raw_text, 5.0)
    events = recovered["persons"][0]["events"]
    by_description = {event["description"]: event for event in events}

    expected = {
        "two minute ride": (120.0, 172.0),
        "three minute ride": (180.0, 212.0),
        "four minute ride": (241.0, 261.0),
        "five minute ride": (346.0, 379.0),
        "late four minute ride": (292.0, 317.0),
        "seven minute ride": (423.0, 455.0),
        "opening ride": (11.0, 38.0),
        "one minute transition ride": (52.0, 66.0),
        "one minute ride": (67.0, 81.0),
        "second two minute ride": (128.0, 143.0),
        "known 459 to 475 ride": (459.0, 475.0),
        "padded five second ride": (120.0, 125.0),
    }
    for description, window in expected.items():
        event = by_description[description]
        require((event["start"], event["end"]) == window, f"MM.SS recovery failed for {description}")
        require(event["timestamp_encoding"] == "minute_second", f"encoding evidence missing for {description}")
        require(event["timestamp_recovered"] is True, f"recovery flag missing for {description}")

    decimal = by_description["valid decimal event"]
    require((decimal["start"], decimal["end"]) == (16.0, 32.0), "usable decimal seconds were incorrectly converted")
    require(decimal["timestamp_encoding"] == "decimal_seconds" and decimal["timestamp_recovered"] is False, "decimal evidence is wrong")
    invalid = by_description["invalid compact time"]
    require((invalid["start"], invalid["end"]) == (2.75, 2.9), "invalid MM.SS seconds should remain raw for normal filtering")
    require(invalid["timestamp_recovered"] is False, "invalid MM.SS value was marked recovered")

    selector = build_selector_candidate_events(
        recovered["persons"],
        source_video="edited_surf.mp4",
        min_event_sec=5.0,
        score_threshold=6,
        dedup_start_seconds=2.0,
    )
    selector = enrich_selector_payload(selector, recovered)
    selected_by_description = {
        item["description"]: item
        for item in selector["candidates"]
        if item.get("selected")
    }
    known = selected_by_description["known 459 to 475 ride"]
    require(known["source_window"] == {"start": 459.0, "end": 475.0, "duration": 16.0}, "recovered event was still filtered before selector")
    require(known["raw_timestamp_window"] == {"start": 7.39, "end": 7.55}, "selector lost raw timestamp evidence")
    require(known["interpreted_timestamp_window"] == {"start": 459.0, "end": 475.0}, "selector lost interpreted timestamp evidence")
    invalid_candidate = next(item for item in selector["candidates"] if item["description"] == "invalid compact time")
    require(invalid_candidate["discard_cause"] == "fragment_shorter_than_min_event_sec", "invalid compact value bypassed normal fragment filtering")

    parsed_stub = {
        "activity": "surfing",
        "persons": [{
            "id": "person_A",
            "description": payload["persons"][0]["description"],
            "events": [
                {
                    "type": "wave_catch", "start": 459.0, "end": 475.0,
                    "score": 9, "description": "known 459 to 475 ride", "edit": {},
                },
                {
                    # Parser padded recovered 120-125 to 120-126.
                    "type": "wave_catch", "start": 120.0, "end": 126.0,
                    "score": 7, "description": "padded five second ride", "edit": {},
                },
            ],
        }],
    }
    annotated = annotate_parsed_session(parsed_stub, recovered)
    parsed_by_description = {
        event["description"]: event for event in annotated["persons"][0]["events"]
    }
    parsed_event = parsed_by_description["known 459 to 475 ride"]
    require(parsed_event["timestamp_encoding"] == "minute_second", "parsed analyzer event lost encoding evidence")
    require((parsed_event["raw_chunk_start"], parsed_event["raw_chunk_end"]) == (7.39, 7.55), "parsed analyzer event lost raw evidence")
    padded_event = parsed_by_description["padded five second ride"]
    require((padded_event["start"], padded_event["end"]) == (120.0, 126.0), "parser padding fixture is wrong")
    require(padded_event["timestamp_recovered"] is True, "parser padding dropped recovery flag")
    require((padded_event["raw_chunk_start"], padded_event["raw_chunk_end"]) == (2.0, 2.05), "parser padding dropped raw MM.SS evidence")
    require((padded_event["interpreted_chunk_start"], padded_event["interpreted_chunk_end"]) == (120.0, 125.0), "parser padding overwrote interpreted evidence")

    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    selector_runtime = (ROOT / "pipeline/selector_candidate_runtime.py").read_text(encoding="utf-8")
    require(run_tracked.rindex("_install_raw_timestamp_recovery()") < run_tracked.rindex("_install_chunk_timeline_runtime()"), "tracked runtime installs recovery after chunk filtering")
    require(run_tracked.rindex("_install_raw_timestamp_recovery()") < run_tracked.rindex("_install_selector_candidate_runtime()"), "tracked runtime installs recovery after selector capture")
    require(sitecustomize.rindex("_install_raw_timestamp_recovery()") < sitecustomize.rindex("_install_chunk_timeline_runtime()"), "sitecustomize installs recovery too late")
    require("recover_raw_session_payload(raw_text" in selector_runtime, "selector telemetry still reads unrecovered raw timestamps")
    require("return original_parse_session(raw_text)" in selector_runtime, "selector runtime bypasses recovery-aware analyzer parser")

    print("raw timestamp recovery contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
