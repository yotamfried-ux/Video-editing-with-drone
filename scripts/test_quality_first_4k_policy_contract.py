#!/usr/bin/env python3
"""Deterministic contract tests for the 4K/perception/no-face product decision."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.quality_preserving_framing import (  # noqa: E402
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    decide_framing,
    quality_output_issues,
)


def _event(**overrides):
    event = {
        "type": "surf_ride",
        "edit": {"zoom": 1.8, "focus": "peak"},
        "perception_evidence_status": "tracker_sidecar",
        "track_id": 7,
        "bbox_xyxy": [900, 420, 2500, 1740],
        "perception_frame_width": 3840,
        "perception_frame_height": 2160,
        "perception_confidence": 0.91,
        "visible_ratio": 1.0,
        "visible_track_ids": [7, 11],
    }
    event.update(overrides)
    return event


def test_readable_surfing_stays_contain() -> None:
    decision = decide_framing(_event(), sport="surfing")
    assert decision.mode == "contain"
    assert decision.zoom == 1.0
    assert decision.reason == "full_frame_readable"


def test_small_stable_surfer_allows_emergency_crop() -> None:
    decision = decide_framing(
        _event(
            bbox_xyxy=[1810, 970, 1930, 1090],
            visible_track_ids=[7],
        ),
        sport="surfing",
    )
    assert decision.mode == "tracked_crop"
    assert "athlete_unreadably_small" in decision.reason
    assert 1.0 <= decision.zoom <= 1.30


def test_other_visible_people_do_not_trigger_crop_by_themselves() -> None:
    decision = decide_framing(
        _event(visible_track_ids=[7, 11, 12]),
        sport="surfing",
    )
    assert decision.mode == "contain"


def test_unreliable_tracking_fails_closed_when_crop_is_needed() -> None:
    try:
        decide_framing(
            _event(
                bbox_xyxy=[1810, 970, 1930, 1090],
                perception_confidence=0.40,
                visible_ratio=0.50,
            ),
            sport="surfing",
        )
    except RuntimeError as exc:
        assert "not reliable enough" in str(exc)
    else:
        raise AssertionError("low-confidence destructive crop must fail closed")


def test_missing_perception_never_falls_back_to_gemini() -> None:
    try:
        decide_framing(_event(perception_evidence_status="gemini"), sport="surfing")
    except RuntimeError as exc:
        assert "tracker_sidecar" in str(exc)
    else:
        raise AssertionError("Gemini-only framing must fail closed")


def test_publishable_output_requires_4k_30() -> None:
    assert (OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_FPS) == (2160, 3840, 30)
    valid = quality_output_issues(
        {"width": 2160, "height": 3840, "fps": 30.0},
        [],
    )
    assert valid == []
    invalid = quality_output_issues(
        {"width": 1080, "height": 1920, "fps": 29.0},
        [],
    )
    assert "resolution_not_4k_vertical" in invalid
    assert "frame_rate_not_30fps" in invalid


def test_face_recognition_is_absent_from_active_product_code() -> None:
    assert not (ROOT / "integrations" / "face_matcher.py").exists()
    assert not (ROOT / "mobile/src/features/auth/components/FaceUploadStep.tsx").exists()
    assert not (ROOT / "mobile/src/app/(tabs)/highlights.tsx").exists()

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    delivery = (ROOT / "services/delivery.py").read_text(encoding="utf-8")
    registration = (ROOT / "mobile/src/app/(auth)/register.tsx").read_text(encoding="utf-8")
    profile = (ROOT / "mobile/src/app/(tabs)/profile.tsx").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/pipeline-run.yml").read_text(encoding="utf-8")
    migration = (ROOT / "supabase/migrations/20260721_remove_face_recognition.sql").read_text(encoding="utf-8")
    core_schema = (ROOT / "supabase/migrations/20260612_create_core_schema.sql").read_text(encoding="utf-8")

    assert "face_recognition" not in requirements
    assert "face_matcher" not in delivery
    assert "matched_athlete" not in delivery
    assert "FaceUploadStep" not in registration
    assert "Face Recognition" not in profile
    assert "SPORTREEL_REQUIRE_PERCEPTION: '1'" in workflow
    assert "drop column if exists face_embedding" in migration
    assert "drop column if exists matched_athlete" in migration
    for forbidden in (
        "face_embedding",
        "photo_path",
        "matched_athlete",
        "match_athlete_face",
        "cosine_similarity",
        "athlete-photos",
    ):
        assert forbidden not in core_schema, f"fresh schema still creates biometric surface: {forbidden}"


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS quality-first 4K contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
