#!/usr/bin/env python3
"""Contract test for sport-agnostic primary-athlete event selection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def validate_tokens() -> None:
    policy = (ROOT / "pipeline" / "single_athlete_selection_policy.py").read_text(encoding="utf-8")
    actor_policy = (ROOT / "pipeline" / "primary_actor_policy.py").read_text(encoding="utf-8")
    required_tokens = [
        "PRIMARY-ATHLETE CONTINUITY POLICY",
        "CENTERED ON ONE TARGET ATHLETE",
        "People around the target athlete are NORMAL",
        "football",
        "two surfers on the same wave",
        "target surfer remains the central",
        "background_people_present:true",
        "competing_active_subjects:true",
        "identity_continuity",
        "target_occluded_at_key_moment",
        "edited_sports_compilation",
        "Coverage requirement",
        "no_output_reason",
        "_enrich_parsed_session",
        "person_id",
        "source_profile",
        "normalize_focused_subwindow_evidence",
        "broad_window_ambiguity_reasons",
    ]
    missing = [token for token in required_tokens if token not in policy]
    require(not missing, f"primary athlete selection policy missing tokens: {missing}")
    for token in [
        "primary_actor_not_reliably_followable",
        "primary_athlete_centered",
        "other_people_allowed",
        "IDENTITY_SWITCH",
        "PRIMARY_ACTOR_OCCLUDED",
        "PRIMARY_ACTOR_UNCLEAR",
        "normalize_focused_subwindow_evidence",
        "FOCUSED_SUBWINDOW_SCOPE",
        "_ACTIVE_CONTEXT_FIELDS",
    ]:
        require(token in actor_policy, f"primary athlete policy missing {token}")
    print("primary athlete policy tokens ok")


def validate_football() -> None:
    from pipeline.primary_actor_policy import ambiguity_reasons, classify_primary_actor
    from pipeline.single_athlete_selection_policy import rewrite_raw_selection_json

    payload = {
        "activity": "football",
        "source_profile": "edited_sports_compilation",
        "persons": [{
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
                    "multiple_active_subjects": True,
                    "competing_active_subjects": True,
                    "target_occluded_at_key_moment": False,
                    "athlete_id": "player_7",
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
                    "description": "Camera switches in the wide view, but the focused pass is clear.",
                    "primary_actor_clear": False,
                    "primary_actor_confidence": 0.2,
                    "identity_continuity": "uncertain",
                    "identity_switch_detected": True,
                    "critical_occlusion": True,
                    "competing_active_subjects": True,
                    "target_occluded_at_key_moment": True,
                    "primary_actor_start": 43.0,
                    "primary_actor_end": 50.0,
                },
            ],
        }],
    }
    rewritten = json.loads(rewrite_raw_selection_json(json.dumps(payload)))
    events = rewritten["persons"][0]["events"]
    require(len(events) == 2, f"expected 2 retained football events, got {events}")
    goal = events[0]
    require(goal["type"] == "goal", "crowded football goal should not be removed")
    require(goal["competing_active_subjects"] is True, "active defenders should remain as context")
    require(ambiguity_reasons(goal) == [], f"clear goal became ambiguous because defenders were active: {goal}")
    gate = classify_primary_actor(goal, visible_subject_count=5, primary_continuity_ratio=0.9)
    require(gate["decision"] == "allowed_primary_actor_clear", f"centered football player was blocked: {gate}")
    require(gate["other_people_allowed"] is True, "football gate did not allow other participants")

    rescued = events[1]
    require(rescued["start"] == 43.0 and rescued["end"] == 50.0, "ambiguous event should use focused sub-window")
    require(rescued["primary_actor_clear"] is True, "focused rescue should become clear")
    require(rescued["identity_continuity"] == "stable", "focused rescue continuity should be stable")
    require(rescued["identity_switch_detected"] is False, "stale identity switch evidence was not cleared")
    require(rescued["critical_occlusion"] is False, "stale occlusion evidence was not cleared")
    require(rescued["competing_active_subjects"] is False, "focused rescue did not clear stale context evidence")
    require(rescued["primary_actor_confidence"] >= 0.75, "focused rescue confidence was not scoped")
    require(rescued["primary_actor_evidence_scope"] == "focused_subwindow", "focused evidence scope missing")
    require(rescued["broad_window_ambiguity_reasons"], "broad-window audit evidence should be retained")
    require(ambiguity_reasons(rescued) == [], f"focused sub-window still carries stale ambiguity: {rescued}")
    print("football centered-athlete selection ok")


def validate_surfing() -> None:
    from pipeline.primary_actor_policy import ambiguity_reasons, classify_primary_actor
    from pipeline.single_athlete_selection_policy import rewrite_raw_selection_json

    payload = {
        "activity": "surfing",
        "persons": [{
            "id": "person_B",
            "description": "surfer in black shorts on turquoise longboard",
            "events": [
                {
                    "type": "wave_catch",
                    "start": 60.0,
                    "end": 78.0,
                    "score": 9,
                    "description": "Target completes a full ride while another surfer enters the same wave.",
                    "primary_actor_clear": True,
                    "primary_actor_confidence": 0.9,
                    "identity_continuity": "stable",
                    "background_people_present": True,
                    "multiple_active_subjects": True,
                    "competing_active_subjects": True,
                    "target_occluded_at_key_moment": False,
                    "athlete_id": "surfer_target",
                },
                {
                    "type": "wave_catch",
                    "start": 85.0,
                    "end": 100.0,
                    "score": 8,
                    "description": "Two surfers overlap and the camera switches focus with no clear target.",
                    "primary_actor_clear": False,
                    "primary_actor_confidence": 0.25,
                    "identity_continuity": "switched",
                    "multiple_active_subjects": True,
                    "competing_active_subjects": True,
                },
            ],
        }],
    }
    rewritten = json.loads(rewrite_raw_selection_json(json.dumps(payload)))
    events = rewritten["persons"][0]["events"]
    require(len(events) == 1, f"expected only the clearly centered same-wave ride, got {events}")
    ride = events[0]
    require(ride["competing_active_subjects"] is True, "same-wave surfer context should be preserved")
    require(ambiguity_reasons(ride) == [], "another surfer on the same wave must not discard a clear ride")
    gate = classify_primary_actor(ride, visible_subject_count=2, primary_continuity_ratio=0.83)
    require(gate["decision"] == "allowed_primary_actor_clear", f"clear same-wave ride was blocked: {gate}")
    require(gate["primary_athlete_centered"] is True, "target surfer was not recorded as centered")
    require(gate["other_people_allowed"] is True, "same-wave participant was not allowed")
    print("surfing same-wave centered-athlete selection ok")


def validate_sitecustomize() -> None:
    sitecustomize = (ROOT / "scripts" / "sitecustomize.py").read_text(encoding="utf-8")
    required = [
        "def _install_single_athlete_selection_policy()",
        "from pipeline.single_athlete_selection_policy import install",
        "_install_single_athlete_selection_policy()",
    ]
    missing = [token for token in required if token not in sitecustomize]
    require(not missing, f"sitecustomize does not install policy: {missing}")
    print("primary athlete policy bootstrap ok")


VALIDATORS = {
    "tokens": validate_tokens,
    "football": validate_football,
    "surfing": validate_surfing,
    "sitecustomize": validate_sitecustomize,
}


def main() -> None:
    modes = sys.argv[1:] or list(VALIDATORS)
    unknown = [mode for mode in modes if mode not in VALIDATORS]
    require(not unknown, f"unknown modes: {unknown}")
    for mode in modes:
        VALIDATORS[mode]()
    print("primary athlete selection policy contract ok")


if __name__ == "__main__":
    main()
