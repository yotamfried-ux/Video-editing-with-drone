"""Make detector/tracker evidence mandatory for every production analysis.

SportReel uses Gemini for semantic understanding, but athlete localization and
continuity must be backed by computer-vision detections.  A run therefore fails
closed when the producer is unavailable, the sidecar is empty, or an analyzed
event cannot be linked to a tracked detection.
"""
from __future__ import annotations

import os
import sys
from typing import Any

_DEFAULT_MODEL = "yolo11s.pt"
_DEFAULT_TRACKER = "botsort.yaml"
_DEFAULT_COMMAND = (
    f"{sys.executable} scripts/generate_perception_sidecar.py "
    "{video_path} {sidecar_path} --backend ultralytics "
    f"--ultralytics-model {_DEFAULT_MODEL} "
    f"--ultralytics-tracker {_DEFAULT_TRACKER} --fps 30"
)
_INSTALLED = False


def _event_has_required_evidence(event: dict[str, Any]) -> bool:
    return bool(
        event.get("perception_evidence_status") == "tracker_sidecar"
        and event.get("track_id") is not None
        and event.get("bbox_xyxy") is not None
        and event.get("perception_frame_width")
        and event.get("perception_frame_height")
    )


def install() -> None:
    """Force perception on and reject evidence-free events."""
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
                "Mandatory perception evidence is missing for analyzed events: "
                f"{preview}"
            )
        return enriched

    runtime.enrich_session_with_sidecar = enrich_and_require
    _INSTALLED = True


__all__ = ["install"]
