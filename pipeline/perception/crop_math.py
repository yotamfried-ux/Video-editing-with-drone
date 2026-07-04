"""BBox-to-crop math for deterministic perception metadata.

These helpers are deliberately dependency-free so contract tests can run in the
lightweight Operator Smoke Check job without installing the full video stack.
"""
from __future__ import annotations

from typing import Any, Sequence

BBox = tuple[float, float, float, float]


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _validate_frame(frame_width: int, frame_height: int) -> None:
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")


def normalize_bbox(xyxy: Sequence[float]) -> BBox:
    if len(xyxy) != 4:
        raise ValueError("xyxy bbox must contain exactly four coordinates")
    x1, y1, x2, y2 = (float(v) for v in xyxy)
    if x2 < x1 or y2 < y1:
        raise ValueError("xyxy bbox must be ordered as x1 <= x2 and y1 <= y2")
    return x1, y1, x2, y2


def clip_bbox(xyxy: Sequence[float], frame_width: int, frame_height: int) -> BBox:
    _validate_frame(frame_width, frame_height)
    x1, y1, x2, y2 = normalize_bbox(xyxy)
    return (
        max(0.0, min(float(frame_width), x1)),
        max(0.0, min(float(frame_height), y1)),
        max(0.0, min(float(frame_width), x2)),
        max(0.0, min(float(frame_height), y2)),
    )


def bbox_visible_ratio(xyxy: Sequence[float], frame_width: int, frame_height: int) -> float:
    """Return how much of the bbox area is visible inside the frame."""
    x1, y1, x2, y2 = normalize_bbox(xyxy)
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if area == 0:
        return 0.0
    cx1, cy1, cx2, cy2 = clip_bbox(xyxy, frame_width, frame_height)
    clipped_area = max(0.0, cx2 - cx1) * max(0.0, cy2 - cy1)
    return clamp(clipped_area / area)


def bbox_center_norm(xyxy: Sequence[float], frame_width: int, frame_height: int) -> tuple[float, float]:
    """Return the normalized center of the visible part of a bbox."""
    _validate_frame(frame_width, frame_height)
    cx1, cy1, cx2, cy2 = clip_bbox(xyxy, frame_width, frame_height)
    if cx2 <= cx1 or cy2 <= cy1:
        x1, y1, x2, y2 = normalize_bbox(xyxy)
        return clamp(((x1 + x2) / 2.0) / frame_width), clamp(((y1 + y2) / 2.0) / frame_height)
    return clamp(((cx1 + cx2) / 2.0) / frame_width), clamp(((cy1 + cy2) / 2.0) / frame_height)


def bbox_to_crop(xyxy: Sequence[float], frame_width: int, frame_height: int) -> dict[str, float]:
    crop_x, crop_y = bbox_center_norm(xyxy, frame_width, frame_height)
    return {
        "crop_x": crop_x,
        "crop_y": crop_y,
        "visible_ratio": bbox_visible_ratio(xyxy, frame_width, frame_height),
    }


def _maybe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def event_has_bbox_metadata(event: dict[str, Any]) -> bool:
    return event.get("bbox_xyxy") is not None


def event_frame_dimensions(event: dict[str, Any]) -> tuple[int, int] | None:
    width = _maybe_int(event.get("perception_frame_width") or event.get("frame_width"))
    height = _maybe_int(event.get("perception_frame_height") or event.get("frame_height"))
    if width is None or height is None:
        return None
    return width, height


def resolve_event_crop(
    event: dict[str, Any],
    *,
    default_crop_y: float = 0.65,
    min_visible_ratio: float = 0.35,
) -> dict[str, Any]:
    """Resolve editor crop values, preferring measured perception bbox data.

    Events without bbox metadata keep the historical Gemini crop contract. Events
    with bbox metadata must also include frame dimensions; otherwise they are
    marked unusable so the runtime layer can fail safe instead of using a risky
    LLM crop for a supposedly measured detection.
    """
    fallback = {
        "crop_x": clamp(float(event.get("crop_x", 0.5))),
        "crop_y": clamp(float(event.get("crop_y", default_crop_y))),
        "visible_ratio": event.get("visible_ratio"),
        "crop_source": "event",
        "perception_crop_status": "no_bbox",
        "perception_crop_usable": True,
    }
    if not event_has_bbox_metadata(event):
        return fallback

    dimensions = event_frame_dimensions(event)
    if dimensions is None:
        return {
            **fallback,
            "crop_source": "bbox",
            "perception_crop_status": "missing_frame_dimensions",
            "perception_crop_usable": False,
        }

    try:
        crop = bbox_to_crop(event["bbox_xyxy"], dimensions[0], dimensions[1])
    except (TypeError, ValueError):
        return {
            **fallback,
            "crop_source": "bbox",
            "perception_crop_status": "invalid_bbox",
            "perception_crop_usable": False,
        }

    usable = crop["visible_ratio"] >= min_visible_ratio
    return {
        **crop,
        "crop_source": "bbox",
        "perception_crop_status": "ok" if usable else "low_visible_ratio",
        "perception_crop_usable": usable,
    }
