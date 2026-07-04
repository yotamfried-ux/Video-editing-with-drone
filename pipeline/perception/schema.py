"""Normalized perception schema for pipeline-quality decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .crop_math import BBox, bbox_to_crop, normalize_bbox


@dataclass(frozen=True)
class PerceptionDetection:
    """One detected object/athlete candidate at a specific video frame."""

    source_video: str
    frame_index: int
    time_sec: float
    xyxy: BBox
    frame_width: int
    frame_height: int
    confidence: float | None = None
    class_id: int | None = None
    class_name: str | None = None
    tracker_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "xyxy", normalize_bbox(self.xyxy))
        if self.frame_index < 0:
            raise ValueError("frame_index must be >= 0")
        if self.time_sec < 0:
            raise ValueError("time_sec must be >= 0")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1] when provided")

    @property
    def crop(self) -> dict[str, float]:
        return bbox_to_crop(self.xyxy, self.frame_width, self.frame_height)

    @property
    def crop_x(self) -> float:
        return self.crop["crop_x"]

    @property
    def crop_y(self) -> float:
        return self.crop["crop_y"]

    @property
    def visible_ratio(self) -> float:
        return self.crop["visible_ratio"]

    def to_event_metadata(self) -> dict[str, Any]:
        """Return the event fields later stages can attach to analyzer events."""
        return {
            "perception_source_video": self.source_video,
            "perception_frame_index": self.frame_index,
            "perception_time_sec": self.time_sec,
            "bbox_xyxy": list(self.xyxy),
            "perception_confidence": self.confidence,
            "perception_class_id": self.class_id,
            "perception_class_name": self.class_name,
            "track_id": self.tracker_id,
            "crop_x": self.crop_x,
            "crop_y": self.crop_y,
            "visible_ratio": self.visible_ratio,
        }
