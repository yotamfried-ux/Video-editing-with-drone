"""Cross-source event fingerprinting and duplicate selection.

The editor already removes overlapping timestamps inside one source video. This
module handles the harder case: the same physical moment appears in two source
files. It only acts when events carry explicit visual/trajectory fingerprints or
synchronized perception evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
import re
from typing import Any

_STRONG_FINGERPRINT_FIELDS = (
    "event_fingerprint",
    "perception_event_fingerprint",
    "visual_fingerprint",
    "visual_hash",
    "thumbnail_hash",
    "crop_hash",
    "bbox_trajectory_hash",
    "track_trajectory_hash",
    "wave_fingerprint",
    "moment_fingerprint",
)

_TRAJECTORY_FIELDS = (
    "bbox_trajectory",
    "bbox_samples",
    "track_bbox_samples",
    "track_summary",
    "perception_track_summary",
)

_SYNC_TIME_FIELDS = (
    "session_time_sec",
    "sync_time_sec",
    "global_time_sec",
    "event_time_sec",
)


@dataclass(frozen=True)
class EventFingerprint:
    """Source-agnostic identifier for a physical moment candidate."""

    key: str
    reason: str
    strength: str


def _stable_text(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    text = str(value).strip().lower()
    return re.sub(r"\s+", " ", text)


def _stable_digest(value: Any) -> str:
    return sha1(_stable_text(value).encode("utf-8")).hexdigest()[:16]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_id(event: dict[str, Any]) -> str:
    return str(
        event.get("_src")
        or event.get("source_video")
        or event.get("perception_source_video")
        or event.get("video")
        or ""
    ).strip()


def _event_type(event: dict[str, Any]) -> str:
    return _stable_text(event.get("type") or event.get("event_type") or "unknown")


def _sync_time(event: dict[str, Any]) -> float | None:
    for field in _SYNC_TIME_FIELDS:
        if event.get(field) is not None:
            return _as_float(event.get(field))
    return None


def _bbox_center_bucket(event: dict[str, Any]) -> tuple[int, int] | None:
    bbox = event.get("bbox_xyxy")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = (_as_float(v) for v in bbox)
    width = _as_float(event.get("perception_frame_width") or event.get("frame_width"), 0.0)
    height = _as_float(event.get("perception_frame_height") or event.get("frame_height"), 0.0)
    if width <= 0 or height <= 0:
        return None
    cx = ((x1 + x2) / 2.0) / width
    cy = ((y1 + y2) / 2.0) / height
    return round(cx * 20), round(cy * 20)


def event_fingerprint(event: dict[str, Any]) -> EventFingerprint | None:
    """Return a duplicate key only when evidence is strong enough."""
    if event.get("_teaser"):
        return None

    for field in _STRONG_FINGERPRINT_FIELDS:
        value = event.get(field)
        if value not in (None, "", [], {}):
            return EventFingerprint(f"{field}:{_stable_digest(value)}", field, "strong")

    for field in _TRAJECTORY_FIELDS:
        value = event.get(field)
        if value not in (None, "", [], {}):
            return EventFingerprint(f"{field}:{_stable_digest(value)}", field, "strong")

    sync_time = _sync_time(event)
    center = _bbox_center_bucket(event)
    if sync_time is None or center is None:
        return None

    confidence = _as_float(event.get("perception_confidence"), 0.0)
    visible = _as_float(event.get("visible_ratio"), 0.0)
    if confidence < 0.5 or visible < 0.5:
        return None

    duration = max(0.0, _as_float(event.get("end")) - _as_float(event.get("start")))
    payload = {
        "type": _event_type(event),
        "sync_bucket": round(sync_time / 1.5),
        "duration_bucket": round(duration / 1.5),
        "bbox_center_bucket": center,
    }
    return EventFingerprint(f"sync_bbox:{_stable_digest(payload)}", "sync_time+bbox_center", "medium")


def event_quality_score(event: dict[str, Any]) -> float:
    """Quality score used only to choose between duplicate candidates."""
    score = _as_float(event.get("score"), 0.0)
    visible = _as_float(event.get("visible_ratio"), 0.0)
    confidence = _as_float(event.get("perception_confidence"), 0.0)
    duration = max(0.0, _as_float(event.get("end")) - _as_float(event.get("start")))
    bbox_bonus = 0.25 if event.get("bbox_xyxy") is not None else 0.0
    track_bonus = 0.15 if event.get("track_id") is not None else 0.0
    return (score * 10.0) + (visible * 4.0) + (confidence * 4.0) + min(duration, 12.0) * 0.1 + bbox_bonus + track_bonus


def _drop_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": _source_id(event),
        "type": event.get("type"),
        "start": event.get("start"),
        "end": event.get("end"),
        "score": event.get("score"),
        "visible_ratio": event.get("visible_ratio"),
        "perception_confidence": event.get("perception_confidence"),
        "quality_score": round(event_quality_score(event), 3),
    }


def deduplicate_cross_source_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop lower-quality duplicates across different source videos."""
    indexed: list[tuple[int, dict[str, Any], EventFingerprint | None]] = [
        (i, ev, event_fingerprint(ev)) for i, ev in enumerate(events)
    ]
    by_key: dict[str, list[tuple[int, dict[str, Any], EventFingerprint]]] = {}
    for i, ev, fp in indexed:
        if fp is not None:
            by_key.setdefault(fp.key, []).append((i, ev, fp))

    drop_indices: set[int] = set()
    replacements: dict[int, dict[str, Any]] = {}

    for key, group in by_key.items():
        source_ids = {_source_id(ev) for _, ev, _ in group if _source_id(ev)}
        if len(group) < 2 or len(source_ids) < 2:
            continue

        best_i, best_event, best_fp = max(
            group,
            key=lambda item: (event_quality_score(item[1]), -item[0]),
        )
        dropped = [ev for i, ev, _ in group if i != best_i]
        drop_indices.update(i for i, _, _ in group if i != best_i)
        replacements[best_i] = {
            **best_event,
            "dedup_fingerprint": key,
            "dedup_reason": best_fp.reason,
            "dedup_strength": best_fp.strength,
            "dedup_duplicate_count": len(group),
            "dedup_dropped_duplicates": [_drop_summary(ev) for ev in dropped],
        }

    return [replacements.get(i, ev) for i, ev, _ in indexed if i not in drop_indices]
