"""Runtime perception evidence enrichment for analyzer events.

This module does not run a detector by itself. It connects production detector /
tracker output into the existing pipeline contract by consuming a JSON sidecar
next to the source video or inside SPORTREEL_PERCEPTION_SIDECAR_DIR.

Expected sidecar shape:
{
  "detections": [
    {
      "frame_index": 90,
      "time_sec": 3.0,
      "bbox_xyxy": [100, 120, 220, 420],
      "frame_width": 1920,
      "frame_height": 1080,
      "confidence": 0.91,
      "class_id": 0,
      "class_name": "athlete",
      "track_id": 7
    }
  ]
}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .schema import PerceptionDetection

_INSTALLED_FLAG = "_sportreel_perception_runtime_installed"
_SIDECAR_ENV = "SPORTREEL_PERCEPTION_SIDECAR_DIR"
_MAX_NEAREST_SEC = 1.0


def candidate_sidecar_paths(video_path: str) -> list[Path]:
    """Return sidecar candidates in deterministic priority order."""
    video = Path(video_path)
    paths = [video.with_suffix(video.suffix + ".perception.json"), video.with_suffix(".perception.json")]
    sidecar_dir = os.getenv(_SIDECAR_ENV, "").strip()
    if sidecar_dir:
        root = Path(sidecar_dir)
        paths.extend([
            root / f"{video.name}.perception.json",
            root / f"{video.stem}.perception.json",
        ])
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _sidecar_path(video_path: str) -> Path | None:
    return next((path for path in candidate_sidecar_paths(video_path) if path.exists()), None)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_sidecar_detections(video_path: str) -> list[PerceptionDetection]:
    """Load normalized detections from the detector/tracker sidecar if present."""
    path = _sidecar_path(video_path)
    if path is None:
        return []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    source_video = str(payload.get("source_video") or video_path)
    default_w = int(payload.get("frame_width") or 0)
    default_h = int(payload.get("frame_height") or 0)
    detections = []
    for item in payload.get("detections", []) or []:
        frame_width = int(item.get("frame_width") or default_w)
        frame_height = int(item.get("frame_height") or default_h)
        detections.append(
            PerceptionDetection(
                source_video=source_video,
                frame_index=int(item.get("frame_index") or 0),
                time_sec=_num(item.get("time_sec")),
                xyxy=tuple(item.get("bbox_xyxy") or item.get("xyxy") or ()),
                frame_width=frame_width,
                frame_height=frame_height,
                confidence=(None if item.get("confidence") is None else float(item.get("confidence"))),
                class_id=(None if item.get("class_id") is None else int(item.get("class_id"))),
                class_name=(None if item.get("class_name") is None else str(item.get("class_name"))),
                tracker_id=(None if item.get("track_id") is None else int(item.get("track_id"))),
            )
        )
    return detections


def _event_window(event: dict[str, Any]) -> tuple[float, float]:
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    return (min(start, end), max(start, end))


def _event_mid(event: dict[str, Any]) -> float:
    start, end = _event_window(event)
    return (start + end) / 2.0


def _in_window(detections: list[PerceptionDetection], event: dict[str, Any]) -> list[PerceptionDetection]:
    start, end = _event_window(event)
    return [detection for detection in detections if start <= detection.time_sec <= end]


def _nearest(detections: list[PerceptionDetection], event: dict[str, Any]) -> PerceptionDetection | None:
    if not detections:
        return None
    mid = _event_mid(event)
    nearest = min(detections, key=lambda detection: abs(detection.time_sec - mid))
    return nearest if abs(nearest.time_sec - mid) <= _MAX_NEAREST_SEC else None


def _best_primary(candidates: list[PerceptionDetection], event: dict[str, Any]) -> PerceptionDetection | None:
    if not candidates:
        return None
    mid = _event_mid(event)
    return max(
        candidates,
        key=lambda detection: (
            detection.confidence if detection.confidence is not None else 0.0,
            -abs(detection.time_sec - mid),
            detection.visible_ratio,
        ),
    )


def _track_ids(candidates: list[PerceptionDetection]) -> list[str]:
    ids = {str(detection.tracker_id) for detection in candidates if detection.tracker_id is not None}
    return sorted(ids)


def enrich_event(event: dict[str, Any], detections: list[PerceptionDetection]) -> dict[str, Any]:
    """Attach bbox/track evidence to one event without mutating input."""
    window_detections = _in_window(detections, event)
    primary = _best_primary(window_detections, event) or _nearest(detections, event)
    if primary is None:
        return {**event, "perception_evidence_status": "no_tracker_detection"}
    visible_ids = _track_ids(window_detections or [primary])
    metadata = primary.to_event_metadata()
    if visible_ids:
        metadata.update({
            "source_window_track_ids": visible_ids,
            "visible_track_ids": visible_ids,
            "all_visible_track_ids": visible_ids,
        })
    return {
        **event,
        **metadata,
        "perception_evidence_status": "tracker_sidecar",
        "perception_detection_count": len(window_detections),
    }


def enrich_session_with_sidecar(session: dict[str, Any], video_path: str) -> dict[str, Any]:
    detections = load_sidecar_detections(video_path)
    if not detections:
        return session
    people = []
    for person in session.get("persons", []) or []:
        events = [enrich_event(event, detections) for event in person.get("events", []) or []]
        people.append({**person, "events": events, "perception_evidence_source": "tracker_sidecar"})
    return {**session, "persons": people, "perception_evidence_source": "tracker_sidecar"}


def install() -> None:
    """Patch analyzer so tracker sidecar evidence lands before crop/identity guards."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, _INSTALLED_FLAG, False):
        return
    original = analyzer.analyze_session

    def analyze_with_perception_sidecar(video_path: str) -> dict:
        result = original(video_path)
        if isinstance(result, dict):
            return enrich_session_with_sidecar(result, video_path)
        return result

    analyzer.analyze_session = analyze_with_perception_sidecar
    setattr(analyzer, _INSTALLED_FLAG, True)


__all__ = [
    "candidate_sidecar_paths",
    "load_sidecar_detections",
    "enrich_event",
    "enrich_session_with_sidecar",
    "install",
]
