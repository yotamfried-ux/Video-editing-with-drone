"""Make detector/tracker evidence mandatory for every production analysis.

SportReel uses Gemini for semantic understanding, but athlete localization and
continuity must be backed by computer-vision detections. A run therefore fails
closed when the producer is unavailable, the sidecar is empty, an analyzed event
cannot be linked to a tracked detection, or a multi-person event is not explicitly
bound to the featured athlete's tracker ID.
"""
from __future__ import annotations

import os
import sys
from typing import Any

_DEFAULT_MODEL = "yolo11s.pt"
_DEFAULT_TRACKER = "config/trackers/sportreel_botsort_reid.yaml"
_DEFAULT_COMMAND = (
    f"{sys.executable} scripts/generate_perception_sidecar.py "
    "{video_path} {sidecar_path} --backend ultralytics "
    f"--ultralytics-model {_DEFAULT_MODEL} "
    f"--ultralytics-tracker {_DEFAULT_TRACKER} --fps 30"
)
_BINDING_FIELDS = ("target_track_id", "primary_track_id", "athlete_track_id")
_VISIBLE_TRACK_FIELDS = (
    "visible_track_ids",
    "all_visible_track_ids",
    "source_window_track_ids",
)
_INSTALLED = False


def _track_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _visible_track_ids(event: dict[str, Any]) -> set[str]:
    visible: set[str] = set()
    for field in _VISIBLE_TRACK_FIELDS:
        raw = event.get(field)
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        visible.update(
            track_id
            for value in values
            if (track_id := _track_id(value)) is not None
        )
    return visible


def _explicit_featured_track_id(event: dict[str, Any]) -> str | None:
    values = {
        track_id
        for field in _BINDING_FIELDS
        if (track_id := _track_id(event.get(field))) is not None
    }
    return next(iter(values)) if len(values) == 1 else None


def _event_has_required_evidence(event: dict[str, Any]) -> bool:
    selected_track = _track_id(event.get("track_id"))
    if not bool(
        event.get("perception_evidence_status") == "tracker_sidecar"
        and selected_track is not None
        and event.get("bbox_xyxy") is not None
        and event.get("perception_frame_width")
        and event.get("perception_frame_height")
    ):
        return False

    visible_tracks = _visible_track_ids(event)
    if visible_tracks and selected_track not in visible_tracks:
        return False

    # In a multi-person window, the highest-confidence detection is not enough:
    # it may belong to a bystander. Require an upstream identity/actor decision to
    # name the featured track, then ensure perception selected that same track.
    if len(visible_tracks) > 1:
        return _explicit_featured_track_id(event) == selected_track

    return True


def install() -> None:
    """Force perception on and reject evidence-free or unbound events."""
    global _INSTALLED
    if _INSTALLED:
        return

    from pipeline.perception import runtime

    os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
    if not os.getenv("SPORTREEL_PERCEPTION_COMMAND", "").strip():
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = _DEFAULT_COMMAND
    if not os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "").strip():
        os.environ["SPORTREEL_ULTRALYTICS_MODEL"] = _DEFAULT_MODEL
    if not os.getenv("SPORTREEL_ULTRALYTICS_TRACKER", "").strip():
        os.environ["SPORTREEL_ULTRALYTICS_TRACKER"] = _DEFAULT_TRACKER
    if not os.getenv("SPORTREEL_ULTRALYTICS_FPS", "").strip():
        os.environ["SPORTREEL_ULTRALYTICS_FPS"] = "30"

    runtime.perception_required = lambda: True

    original_reusable = runtime._is_reusable_sidecar

    def reusable_with_detections(summary: dict[str, Any]) -> bool:
        try:
            detection_count = int(summary.get("detection_count") or 0)
        except (TypeError, ValueError):
            detection_count = 0
        return original_reusable(summary) and detection_count > 0

    runtime._is_reusable_sidecar = reusable_with_detections

    original_enrich = runtime.enrich_session_with_sidecar

    def enrich_and_require(session: dict[str, Any], video_path: str) -> dict[str, Any]:
        enriched = original_enrich(session, video_path)
        missing: list[str] = []
        for person_index, person in enumerate(enriched.get("persons", []) or []):
            for event_index, event in enumerate(person.get("events", []) or []):
                if not _event_has_required_evidence(event):
                    missing.append(f"person={person_index},event={event_index}")
        if missing:
            preview = "; ".join(missing[:10])
            raise RuntimeError(
                "Mandatory perception evidence or featured-athlete track binding "
                f"is missing for analyzed events: {preview}"
            )
        return enriched

    runtime.enrich_session_with_sidecar = enrich_and_require
    _INSTALLED = True


__all__ = ["install"]
