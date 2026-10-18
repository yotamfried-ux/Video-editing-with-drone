#!/usr/bin/env python3
"""Behavior contract for event-quality-first reel eligibility."""
from __future__ import annotations

from pipeline.performance_reel_policy import evaluate_event_quality, filter_session_result_for_performance_reel


def event(**overrides):
    base = {
        "event_id": "event-1",
        "athlete_id": "athlete-1",
        "type": "highlight",
        "start": 10.0,
        "end": 17.0,
        "score": 8,
        "description": "complete visible action with a clean outcome",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.95,
        "identity_continuity": "stable",
        "action_complete": True,
        "action_readable": True,
    }
    base.update(overrides)
    return base


def assert_single_quality_event_is_enough():
    for activity, sample in [
        ("surfing", event(type="wave_catch", description="beginner stands cleanly and rides the wave to a natural finish")),
        ("football", event(type="goal", description="player controls, shoots and scores with a visible outcome")),
    ]:
        verdict = evaluate_event_quality(sample, activity)
        assert verdict["clip_worthy"] is True, (activity, verdict)
        result = filter_session_result_for_performance_reel({
            "activity": activity,
            "persons": [{"id": "person_A", "description": "target athlete", "events": [sample]}],
        })
        assert len(result["persons"][0]["events"]) == 1, (activity, result)


def assert_short_or_incomplete_event_is_rejected():
    too_short = evaluate_event_quality(event(end=12.0), "football")
    assert too_short["clip_worthy"] is False and "too_short" in too_short["reasons"], too_short
    incomplete = evaluate_event_quality(event(action_complete=False), "surfing")
    assert incomplete["clip_worthy"] is False and "incomplete_action" in incomplete["reasons"], incomplete


def assert_weak_volume_does_not_create_eligibility():
    weak = [event(event_id=f"weak-{i}", start=i * 8.0, end=i * 8.0 + 7.0, score=4) for i in range(8)]
    result = filter_session_result_for_performance_reel({
        "activity": "football",
        "persons": [{"id": "person_A", "description": "player #7", "events": weak}],
    })
    assert result["persons"][0]["events"] == [], result
    assert result["persons"][0]["no_output_reason"] == "quality_below_threshold", result


def assert_identity_is_hard_gate():
    mixed = event(primary_actor_clear=False, primary_actor_confidence=0.40, identity_continuity="unstable")
    verdict = evaluate_event_quality(mixed, "football")
    assert verdict["clip_worthy"] is False, verdict
    assert "identity_not_verified" in verdict["reasons"], verdict


def main() -> int:
    assert_single_quality_event_is_enough()
    assert_short_or_incomplete_event_is_rejected()
    assert_weak_volume_does_not_create_eligibility()
    assert_identity_is_hard_gate()
    print("Event-quality-first eligibility contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
