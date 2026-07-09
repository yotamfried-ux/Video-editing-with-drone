#!/usr/bin/env python3
"""Contract test for upstream single-athlete event selection policy."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_source_tokens() -> None:
    policy = (ROOT / "pipeline" / "single_athlete_selection_policy.py").read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts" / "sitecustomize.py").read_text(encoding="utf-8")
    required_policy_tokens = [
        "SINGLE-ATHLETE SELECTION POLICY",
        "shared-wave",
        "same-window multi-person",
        "clean sub-window",
        "at least 6 continuous seconds",
        "rewrite_raw_selection_json",
        "_parse_session = parse_with_single_athlete_policy",
        "subject_isolation",
    ]
    missing = [token for token in required_policy_tokens if token not in policy]
    if missing:
        raise AssertionError(f"single-athlete selection policy missing tokens: {missing}")
    if "_install_single_athlete_selection_policy()" not in sitecustomize:
        raise AssertionError("sitecustomize does not install single-athlete selection policy")


def test_rewrite_shared_wave_events() -> None:
    from pipeline.single_athlete_selection_policy import rewrite_raw_selection_json

    raw = {
        "activity": "surfing",
        "session_peak": 9,
        "style": {"visual": "bright", "pace": "moderate", "density": "high"},
        "persons": [
            {
                "id": "person_A",
                "description": "surfer in pink swimsuit on pink longboard",
                "events": [
                    {
                        "type": "highlight",
                        "start": 515,
                        "end": 535,
                        "score": 9,
                        "description": "Shares a wave and is partially obstructed by another rider.",
                        "crop_x": 0.5,
                        "crop_y": 0.6,
                        "edit": {"zoom": 1.0, "slowmo": False, "focus": "full"},
                    },
                    {
                        "type": "highlight",
                        "start": 536,
                        "end": 588,
                        "clean_start": 542,
                        "clean_end": 550,
                        "score": 8,
                        "subject_isolation": "shared_wave",
                        "description": "Long shared wave, but a clean solo section exists.",
                        "crop_x": 0.4,
                        "crop_y": 0.6,
                        "edit": {"zoom": 1.0, "slowmo": False, "focus": "full"},
                    },
                    {
                        "type": "carve",
                        "start": 480,
                        "end": 491,
                        "score": 9,
                        "subject_isolation": "clean",
                        "description": "Clean solo ride with readable carve and exit.",
                        "crop_x": 0.45,
                        "crop_y": 0.62,
                        "edit": {"zoom": 1.0, "slowmo": False, "focus": "full"},
                    },
                ],
            }
        ],
    }
    rewritten = json.loads(rewrite_raw_selection_json(json.dumps(raw)))
    events = rewritten["persons"][0]["events"]
    if len(events) != 2:
        raise AssertionError(f"expected one bad event dropped and two retained, got {len(events)}: {events}")
    if any("obstructed" in event.get("description", "").lower() for event in events):
        raise AssertionError(f"obstructed/shared event was not dropped: {events}")
    subwindow = events[0]
    if (subwindow["start"], subwindow["end"], subwindow.get("subject_isolation")) != (542, 550, "clean"):
        raise AssertionError(f"shared event was not rewritten to clean sub-window: {subwindow}")


def main() -> None:
    test_source_tokens()
    test_rewrite_shared_wave_events()
    print("single-athlete selection policy contract ok")


if __name__ == "__main__":
    main()
