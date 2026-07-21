#!/usr/bin/env python3
"""Deterministic contract tests for the 4K/perception/no-face product decision."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.quality_preserving_framing import (  # noqa: E402
    OUTPUT_FPS,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    _resolve_track_safe_decision,
    decide_framing,
    quality_output_issues,
)
from pipeline.required_perception_policy import _event_has_required_evidence  # noqa: E402


def _event(**overrides):
    event = {
        "type": "surf_ride",
        "start": 0.0,
        "end": 1.0,
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


def _write_sidecar(video_path: Path, detections: list[dict]) -> Path:
    sidecar = video_path.with_suffix(video_path.suffix + ".perception.json")
    sidecar.write_text(
        json.dumps({"source_video": str(video_path), "status": "ok", "detections": detections}),
        encoding="utf-8",
    )
    return sidecar


def _detection(time_sec: float, bbox: list[int], track_id: int = 7) -> dict:
    return {
        "time_sec": time_sec,
        "frame_index": int(time_sec * 30),
        "bbox_xyxy": bbox,
        "frame_width": 3840,
        "frame_height": 2160,
        "confidence": 0.95,
        "class_id": 0,
        "class_name": "athlete",
        "track_id": track_id,
    }


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


def test_multi_person_evidence_requires_featured_track_binding() -> None:
    unbound = _event(visible_track_ids=[7, 11])
    assert not _event_has_required_evidence(unbound)

    bound = _event(visible_track_ids=[7, 11], target_track_id=7)
    assert _event_has_required_evidence(bound)

    wrong_track = _event(visible_track_ids=[7, 11], target_track_id=11)
    assert not _event_has_required_evidence(wrong_track)


def test_stable_track_trajectory_keeps_emergency_crop() -> None:
    event = _event(
        bbox_xyxy=[1810, 970, 1930, 1090],
        visible_track_ids=[7],
    )
    decision = decide_framing(event, sport="surfing")
    with tempfile.TemporaryDirectory(prefix="sportreel-track-safe-") as temp_dir:
        video_path = Path(temp_dir) / "stable.mp4"
        _write_sidecar(
            video_path,
            [
                _detection(0.1, [1800, 960, 1920, 1080]),
                _detection(0.5, [1820, 970, 1940, 1090]),
                _detection(0.9, [1810, 965, 1930, 1085]),
            ],
        )
        resolved = _resolve_track_safe_decision(str(video_path), event, decision)
    assert resolved.mode == "tracked_crop"
    assert "stable_track_trajectory" in resolved.reason


def test_moving_track_falls_back_to_contain() -> None:
    event = _event(
        bbox_xyxy=[350, 970, 470, 1090],
        visible_track_ids=[7],
    )
    decision = decide_framing(event, sport="surfing")
    with tempfile.TemporaryDirectory(prefix="sportreel-track-motion-") as temp_dir:
        video_path = Path(temp_dir) / "moving.mp4"
        _write_sidecar(
            video_path,
            [
                _detection(0.1, [300, 960, 420, 1080]),
                _detection(0.5, [1800, 970, 1920, 1090]),
                _detection(0.9, [3300, 965, 3420, 1085]),
            ],
        )
        resolved = _resolve_track_safe_decision(str(video_path), event, decision)
    assert resolved.mode == "contain"
    assert resolved.zoom == 1.0
    assert "track_motion_requires_contain" in resolved.reason


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
    privacy = (ROOT / "mobile/src/shared/legal/privacyPolicy.ts").read_text(encoding="utf-8")
    terms = (ROOT / "mobile/src/shared/legal/terms.ts").read_text(encoding="utf-8")
    deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    stripe_checkout = (ROOT / "web-api/src/app/api/checkout/stripe/route.ts").read_text(encoding="utf-8")
    stripe_webhook = (ROOT / "web-api/src/app/api/webhooks/stripe/route.ts").read_text(encoding="utf-8")
    mobile_checkout = (ROOT / "mobile/src/features/payment/hooks/useCheckout.ts").read_text(encoding="utf-8")

    assert "face_recognition" not in requirements
    assert "face_matcher" not in delivery
    assert "matched_athlete" not in delivery
    assert "FaceUploadStep" not in registration
    assert "Face Recognition" not in profile
    assert "SPORTREEL_REQUIRE_PERCEPTION: '1'" in workflow
    assert "drop column if exists face_embedding" in migration
    assert "drop column if exists matched_athlete" in migration
    assert "receipt_email: email" in stripe_checkout
    assert "payer_email: email" in stripe_checkout
    assert "Stripe owns the compliant" in stripe_webhook
    assert "sendPaymentConfirmEmail" not in stripe_webhook
    assert "email: payerEmail" in mobile_checkout
    for forbidden in (
        "face_embedding",
        "photo_path",
        "matched_athlete",
        "match_athlete_face",
        "cosine_similarity",
        "athlete-photos",
    ):
        assert forbidden not in core_schema, f"fresh schema still creates biometric surface: {forbidden}"

    for stale_feature_text in (
        "Face Biometric Data (Optional)",
        "FACE_CONSENT_TEXT",
        "I consent to SportReel collecting and processing my facial biometric data",
        "FACE RECOGNITION (OPTIONAL)",
        "Profile → Face Recognition",
        "Face/biometric disclosure if app-store review requires it",
    ):
        combined = "\n".join((privacy, terms, deployment))
        assert stale_feature_text not in combined, f"stale biometric product text remains: {stale_feature_text}"


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
