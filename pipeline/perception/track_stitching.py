"""Deterministic post-processing for fragmented tracker IDs.

Ultralytics trackers can fragment one visible athlete into many short-lived raw
track IDs, especially on long drone footage with sparse CPU inference. This
module keeps the original raw ID as evidence and writes a canonical track ID when
short adjacent segments are temporally and spatially continuous.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping

DEFAULT_MAX_GAP_SEC = 3.0
DEFAULT_MAX_CENTER_DISTANCE_RATIO = 0.12
DEFAULT_MIN_IOU = 0.05


def _time(item: Mapping[str, Any]) -> float:
    try:
        value = float(item.get("time_sec"))
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def _frame_index(item: Mapping[str, Any]) -> int:
    try:
        return int(item.get("frame_index") or 0)
    except (TypeError, ValueError):
        return 0


def _bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    value = item.get("bbox_xyxy") or item.get("xyxy")
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(part) for part in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(part) for part in (x1, y1, x2, y2)) or x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _source(item: Mapping[str, Any], default_source: str = "") -> str:
    return str(item.get("source_video") or item.get("_source_video") or default_source or "")


def _class_key(item: Mapping[str, Any]) -> str:
    if item.get("class_id") is not None:
        return f"id:{item.get('class_id')}"
    return f"name:{item.get('class_name') or ''}"


def _raw_track_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("raw_track_id", item.get("track_id", item.get("tracker_id")))
    return None if value is None else str(value)


def _canonical_track_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("track_id", item.get("canonical_track_id", item.get("tracker_id")))
    return None if value is None else str(value)


def _center_distance(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx = (left[0] + left[2]) / 2.0
    ly = (left[1] + left[3]) / 2.0
    rx = (right[0] + right[2]) / 2.0
    ry = (right[1] + right[3]) / 2.0
    return math.hypot(lx - rx, ly - ry)


def _frame_diag(item: Mapping[str, Any]) -> float:
    try:
        width = float(item.get("frame_width") or 0)
        height = float(item.get("frame_height") or 0)
    except (TypeError, ValueError):
        return 1.0
    diag = math.hypot(width, height)
    return diag if diag > 0 else 1.0


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    denom = left_area + right_area - inter
    return inter / denom if denom > 0 else 0.0


def _area_ratio(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    if left_area <= 0 or right_area <= 0:
        return 0.0
    return min(left_area, right_area) / max(left_area, right_area)


def _canonical_value(raw: str) -> int | str:
    try:
        return int(raw)
    except ValueError:
        return raw


def _segment_key(item: Mapping[str, Any], default_source: str) -> tuple[str, str, str] | None:
    raw = _raw_track_id(item)
    if raw is None:
        return None
    return (_source(item, default_source), _class_key(item), raw)


def stitch_detection_tracks(
    detections: list[dict[str, Any]],
    *,
    source_video: str = "",
    max_gap_sec: float = DEFAULT_MAX_GAP_SEC,
    max_center_distance_ratio: float = DEFAULT_MAX_CENTER_DISTANCE_RATIO,
    min_iou: float = DEFAULT_MIN_IOU,
) -> list[dict[str, Any]]:
    """Return detections with canonical track IDs and preserved raw_track_id.

    Stitching is intentionally conservative:
    - segments must belong to the same source video and class
    - they may not overlap in time
    - the next segment must start within `max_gap_sec`
    - the last bbox and next first bbox must overlap or be spatially close
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    passthrough: list[dict[str, Any]] = []
    for item in detections:
        key = _segment_key(item, source_video)
        copied = dict(item)
        raw = _raw_track_id(item)
        if raw is not None:
            copied["raw_track_id"] = _canonical_value(raw)
        if key is None:
            passthrough.append(copied)
        else:
            grouped[key].append(copied)

    segments: list[dict[str, Any]] = []
    for (source, class_key, raw), items in grouped.items():
        ordered = sorted(items, key=lambda item: (_time(item), _frame_index(item)))
        if not ordered:
            continue
        segments.append({
            "source": source,
            "class_key": class_key,
            "raw": raw,
            "detections": ordered,
            "start": _time(ordered[0]),
            "end": _time(ordered[-1]),
            "first": ordered[0],
            "last": ordered[-1],
            "canonical": _canonical_value(raw),
        })

    canonical_segments: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    raw_to_canonical: dict[tuple[str, str, str], int | str] = {}

    for segment in sorted(segments, key=lambda seg: (seg["source"], seg["class_key"], seg["start"], seg["end"], seg["raw"])):
        group_key = (segment["source"], segment["class_key"])
        first_bbox = _bbox(segment["first"])
        best: dict[str, Any] | None = None
        best_score: tuple[float, float, float] | None = None
        for candidate in canonical_segments[group_key]:
            gap = float(segment["start"]) - float(candidate["end"])
            if gap < 0 or gap > max_gap_sec:
                continue
            last_bbox = _bbox(candidate["last"])
            if first_bbox is None or last_bbox is None:
                continue
            overlap = _iou(last_bbox, first_bbox)
            center_ratio = _center_distance(last_bbox, first_bbox) / _frame_diag(segment["first"])
            if overlap < min_iou and center_ratio > max_center_distance_ratio:
                continue
            if _area_ratio(last_bbox, first_bbox) < 0.15:
                continue
            score = (center_ratio, gap, -overlap)
            if best is None or score < best_score:  # type: ignore[operator]
                best = candidate
                best_score = score
        if best is None:
            raw_to_canonical[(segment["source"], segment["class_key"], segment["raw"])] = segment["canonical"]
            canonical_segments[group_key].append(segment)
        else:
            raw_to_canonical[(segment["source"], segment["class_key"], segment["raw"])] = best["canonical"]
            if float(segment["end"]) >= float(best["end"]):
                best["end"] = segment["end"]
                best["last"] = segment["last"]

    stitched: list[dict[str, Any]] = []
    for segment in segments:
        canonical = raw_to_canonical[(segment["source"], segment["class_key"], segment["raw"])]
        for item in segment["detections"]:
            stitched.append({**item, "track_id": canonical, "track_stitching_status": "canonicalized"})
    stitched.extend({**item, "track_stitching_status": "passthrough"} for item in passthrough)
    return sorted(stitched, key=lambda item: (_source(item, source_video), _time(item), _frame_index(item), str(item.get("raw_track_id", item.get("track_id")))))


def track_stitching_summary(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    raw_ids = {_raw_track_id(item) for item in before if _raw_track_id(item) is not None}
    canonical_ids = {_canonical_track_id(item) for item in after if _canonical_track_id(item) is not None}
    return {
        "enabled": True,
        "raw_track_count": len(raw_ids),
        "canonical_track_count": len(canonical_ids),
        "stitched_track_count": max(0, len(raw_ids) - len(canonical_ids)),
        "max_gap_sec": DEFAULT_MAX_GAP_SEC,
        "max_center_distance_ratio": DEFAULT_MAX_CENTER_DISTANCE_RATIO,
        "min_iou": DEFAULT_MIN_IOU,
        "raw_track_id_preserved": True,
    }


def stitch_sidecar_payload(payload: dict[str, Any], *, source_video: str = "") -> dict[str, Any]:
    detections = [dict(item) for item in payload.get("detections", []) if isinstance(item, dict)]
    if not detections:
        payload["track_stitching"] = track_stitching_summary([], [])
        return payload
    stitched = stitch_detection_tracks(detections, source_video=source_video or str(payload.get("source_video") or ""))
    payload["detections"] = stitched
    payload["track_stitching"] = track_stitching_summary(detections, stitched)
    return payload
