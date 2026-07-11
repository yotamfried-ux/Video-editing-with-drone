#!/usr/bin/env python3
"""Contract test for sport-agnostic primary-actor event selection."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.single_athlete_selection_policy import rewrite_raw_selection_json

ROOT = Path(__file__).resolve().parents[1]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def main() -> None:
    policy = (ROOT / "pipeline" / "single_athlete_selection_policy.py").read_text(encoding="utf-8")
    actor_policy = (ROOT / "pipeline" / "primary_actor_policy.py").read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts" / "sitecustomize.py").read_text(encoding="utf-8")

    required_tokens = [
        "PRIMARY-ACTOR CONTINUITY POLICY",
        "People around the target athlete are NORMAL",
        "football",
        "surfing",
        "background_people_present:true",
        "identity_continuity",
        "competing_active_subjects",
        "target_occluded_at_key_moment",
        "edited_sports_compilation",
        "Coverage requirement",
        "no_output_reason",
        "_enrich_parsed_session",
        "person_id",
        "source_profile",
    ]
    missing = [token for token in required_tokens if token not in policy]
    require(not missing, f"primary actor selection policy missing tokens: {missing}")

    for token in [
        "primary_actor_not_reliably_followable",
        "background_people_allowed",
        "IDENTITY_SWITCH",
        "PRIMARY_ACTOR_OCCLUDED",
        "PRIMARY_ACTOR_UNCLEAR",
    ]:
        require(token in actor_policy, f"primary actor policy missing {token}")

    payload = {
        "activity": "football",
        "source_profile": "edited_sports_compilation",
        "persons": [
            {
                "id": "person_A",
                "description": "player #7 in red jersey",
                "events": [
                    {
                        "type": "goal",
                        "start": 10.0,
                        "end": 20.0,
                        "score": 9,
                        "description": "Player #7 dribbles through defenders and scores.",
                        "primary_actor_clear": True,
                        "primary_actor_confidence": 0.93,
                        "identity_continuity": "stable",
                        "background_people_present": True,
                        "competing_active_subjects": False,
                        "target_occluded_at_key_moment": False,
                    },
                    {
                        "type": "tackle",
                        "start": 25.0,
                        "end": 34.0,
                        "score": 8,
                        "description": "Camera switches to another player during the tackle.",
                        "primary_actor_clear": False,
                        "identity_continuity": "switched",
                        "background_people_present": True,
                    },
                    {
                        "type": "assist",
                        "start": 40.0,
                        "end": 52.0,
                        "score": 8,
                        "description": "Wide play becomes ambiguous, but focused section shows the pass.",
                        "primary_actor_clear": False,
                        "identity_continuity": "uncertain",
                        "primary_actor_start": 43.0,
                        "primary_actor_end": 50.0,
                    },
                ],
            }
        ],
    }
    rewritten = json.loads(rewrite_raw_selection_json(json.dumps(payload)))
    events = rewritten["persons"][0]["events"]
    require(len(events) == 2, "clear crowded play and focused rescue should remain")
    require(events[0]["type"] == "goal", "crowded football goal should not be removed")
    require(events[0]["background_people_present"] is True, "background context should be preserved")
    require(events[1]["start"] == 43.0 and events[1]["end"] == 50.0, "ambiguous event should use focused sub-window")
    require(events[1]["primary_actor_clear"] is True, "focused rescue should become clear")

    surf_payload = {
        "activity": "surfing",
        "persons": [{
            "id": "person_B",
            "description": "surfer in black shorts on turquoise longboard",
            "events": [{
                "type": "wave_catch",
                "start": 60.0,
                "end": 78.0,
                "score": 9,
                "description": "Completes a full ride while another surfer waits in the background.",
                "primary_actor_clear": True,
                "primary_actor_confidence": 0.9,
                "identity_continuity": "stable",
                "background_people_present": True,
                "competing_active_subjects": False,
                "target_occluded_at_key_moment": False,
            }],
        }],
    }
    surf_rewritten = json.loads(rewrite_raw_selection_json(json.dumps(surf_payload)))
    require(len(surf_rewritten["persons"][0]["events"]) == 1, "background surfer must not discard a complete ride")

    required_sitecustomize_tokens = [
        "def _install_single_athlete_selection_policy()",
        "from pipeline.single_athlete_selection_policy import install",
        "_install_single_athlete_selection_policy()",
    ]
    missing_sitecustomize = [token for token in required_sitecustomize_tokens if token not in sitecustomize]
    require(not missing_sitecustomize, f"sitecustomize does not install policy: {missing_sitecustomize}")

    print("primary actor selection policy contract ok")


if __name__ == "__main__":
    main()
