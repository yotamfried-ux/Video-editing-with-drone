"""BBox-to-crop math for deterministic perception metadata.

These helpers are deliberately dependency-free so contract tests can run in the
lightweight Operator Smoke Check job without installing the full video stack.
"""
from __future__ import annotations

from typing import Sequence

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
