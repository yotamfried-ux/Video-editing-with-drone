#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pipeline.draft_diagnostics import build_diagnostic_artifact
from pipeline.multi_person_clip_gate import annotate_multi_person_events, has_multi_person_defect
from pipeline.qa_gate_policy import BLOCKING_DEFECT_TYPES, is_critical_defect
from pipeline.subject_gate_policy import build_subject_gate, effective_cut_window, has_subject_isolation_defect

ROOT = Path(__file__).resolve().parents[1]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(msg)


def det(track_id: int, time_sec: float) -> dict:
    return {
        "source_video": "source.mp4",
        "time_sec": time_sec,
        "track_id": track_id,
        "raw_track_id": track_id,
        "bbox_xyxy": [100, 100, 200, 300],
        "frame_width": 1920,
        "frame_height": 1080,
    }


def main() -> int:
    # Surfing: another surfer in the lineup/background is not a defect when the
    # target remains the clear actor throughout the ride.
    surf_events = annotate_multi_person_events([{
        "event_id": "ride_1",
        "type": "surf_ride",
        "person_id": "surfer_A",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.94,
        "identity_continuity": "stable",
        "background_people_present": True,
        "competing_active_subjects": False,
        "source_window_track_ids": ["main", "extra"],
        "start": 1,
        "end": 12,
    }])
    surf_gate = surf_events[0].get("multi_person_clip_gate", {})
    require(surf_gate.get("decision") == "allowed_primary_actor_clear", "background surfer should be allowed")
    require(surf_gate.get("background_people_allowed") is True, "background allowance missing")
    require(not has_multi_person_defect(surf_events), "clear surf actor must not be blocked")
    require("qa_gate" not in surf_events[0], "allowed surf event must not get QA defect")

    # Football: teammates and opponents are expected around the player executing
    # the play. Attribution, not people count, decides validity.
    football_events = annotate_multi_person_events([{
        "event_id": "goal_1",
        "type": "goal",
        "person_id": "player_7",
        "description": "Player #7 dribbles past two defenders and scores.",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.91,
        "identity_continuity": "stable",
        "background_people_present": True,
        "competing_active_subjects": False,
        "source_window_person_ids": ["player_7", "defender_4", "defender_5", "goalkeeper_1"],
        "start": 20,
        "end": 31,
    }])
    football_gate = football_events[0].get("multi_person_clip_gate", {})
    require(football_gate.get("decision") == "allowed_primary_actor_clear", "football play should follow primary actor")
    require(not has_multi_person_defect(football_events), "normal football context must not be blocked")

    # Genuine ambiguity remains a hard block.
    ambiguous_events = annotate_multi_person_events([{
        "event_id": "duel_1",
        "type": "tackle",
        "primary_actor_clear": False,
        "primary_actor_confidence": 0.35,
        "identity_continuity": "uncertain",
        "competing_active_subjects": True,
        "source_window_track_ids": ["track_1", "track_2"],
        "start": 40,
        "end": 49,
    }])
    ambiguous = ambiguous_events[0]
    ambiguous_gate = ambiguous.get("multi_person_clip_gate", {})
    require(ambiguous_gate.get("decision") == "review_required", "ambiguous primary actor must require review")
    require(has_multi_person_defect(ambiguous_events), "ambiguous gate was not detected")
    defects = ambiguous.get("qa_gate", {}).get("defects", [])
    require(defects and defects[0].get("type") == "PRIMARY_ACTOR_UNCLEAR", "primary actor defect missing")
    require(is_critical_defect(defects[0]), "primary actor ambiguity must be critical")

    switched_events = annotate_multi_person_events([{
        "event_id": "switch_1",
        "type": "dribble",
        "person_id": "player_10",
        "identity_switch_detected": True,
        "source_window_person_ids": ["player_10", "player_8"],
        "start": 50,
        "end": 59,
    }])
    switch_defect = switched_events[0].get("qa_gate", {}).get("defects", [])[0]
    require(switch_defect.get("type") == "IDENTITY_SWITCH", "identity switch must be explicit")

    # Sidecar gate: multiple persistent tracks are allowed when native-video
    # analysis says the action attribution is stable.
    subject_event = {
        "event_id": "play_2",
        "type": "dribble",
        "start": 10,
        "end": 30,
        "score": 8,
        "person_id": "player_7",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.9,
        "identity_continuity": "stable",
        "competing_active_subjects": False,
    }
    crowded_detections = [
        det(1, 20.0), det(2, 20.0),
        det(1, 21.0), det(2, 21.0),
        det(1, 22.0), det(2, 22.0),
    ]
    subject_gate = build_subject_gate(subject_event, crowded_detections, 0, source_video="source.mp4")
    require(subject_gate is not None, "subject gate telemetry should be emitted")
    require(subject_gate.get("decision") == "allowed_primary_actor_clear", "stable actor should survive crowded frame")
    require(subject_gate.get("background_people_allowed") is True, "sidecar gate must allow background people")
    require("defect" not in subject_gate, "allowed sidecar gate must not create defect")

    # A declared target may never be silently replaced by the most common opponent
    # or background track when that target disappeared from the window.
    missing_target_gate = build_subject_gate(
        {
            **subject_event,
            "target_track_id": "99",
            "primary_actor_clear": True,
            "identity_continuity": "stable",
        },
        crowded_detections,
        0,
        source_video="source.mp4",
    )
    require(missing_target_gate is not None, "missing target should emit blocking telemetry")
    require(missing_target_gate.get("decision") == "review_required", "missing declared target must be blocked")
    require(missing_target_gate.get("declared_target_track_id") == "99", "declared target evidence missing")
    require(missing_target_gate.get("declared_target_track_present") is False, "missing target incorrectly marked present")
    require(missing_target_gate.get("primary_track_id") == "99", "opponent track must not replace declared target")
    require("declared_target_track_absent" in missing_target_gate.get("ambiguity_reasons", []), "missing-target reason absent")
    require(missing_target_gate.get("defect", {}).get("blocking") is True, "missing target defect must block")

    blocked_subject_gate = build_subject_gate(
        {**subject_event, "primary_actor_clear": False, "identity_continuity": "uncertain"},
        [det(1, 20.0), det(2, 20.0), det(1, 21.0), det(2, 21.0)],
        0,
        source_video="source.mp4",
    )
    require(blocked_subject_gate.get("decision") == "review_required", "uncertain actor must be blocked")
    subject_review_event = {
        **subject_event,
        "subject_isolation_gate": blocked_subject_gate,
        "qa_gate": {"qa_review_required": True, "defects": [blocked_subject_gate["defect"]]},
    }
    require(has_subject_isolation_defect([subject_review_event]), "subject continuity defect not detected")

    capped = effective_cut_window({"start": 1.0, "end": 25.0})
    require(capped == (14.0, 25.0), f"non-climax window should match actual editor cap: {capped}")

    social_events = annotate_multi_person_events([{
        "event_id": "social_1",
        "type": "high_five",
        "track_id": "main",
        "source_window_track_ids": ["main", "friend"],
        "value_labels": ["SOCIAL_MOMENT", "HIGH_FIVE"],
        "start": 3,
        "end": 9,
    }])
    require(social_events[0]["multi_person_clip_gate"]["decision"] == "allowed_social_moment", "social moment should remain allowed")

    artifact = build_diagnostic_artifact("DRAFT_ambiguous.mp4", "football", ambiguous_events, {}, "review/DRAFT_ambiguous.mp4")
    require(artifact["identity_clusters"][0]["members"][0]["multi_person_clip_gate"]["decision"] == "review_required", "diagnostic gate missing")
    require(any(item.get("reason") in {"PRIMARY_ACTOR_UNCLEAR", "IDENTITY_UNCERTAIN"} for item in artifact["dropped_events"]), "diagnostic dropped reason missing")

    for code in ("PRIMARY_ACTOR_UNCLEAR", "PRIMARY_ACTOR_OCCLUDED", "IDENTITY_SWITCH"):
        require(code in BLOCKING_DEFECT_TYPES, f"{code} not blocking")

    context = (ROOT / "pipeline/context_qa_gate.py").read_text(encoding="utf-8")
    require("annotate_subject_events" in context, "context QA does not annotate subject gates")
    long_context = (ROOT / "pipeline/context_qa_long_video.py").read_text(encoding="utf-8")
    require("annotate_subject_events" in long_context, "long-video context QA does not annotate subject gates")

    print("primary actor continuity gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
