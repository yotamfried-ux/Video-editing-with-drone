"""Adapter from Supervision detections into SportReel perception schema.

The adapter is intentionally thin: Supervision is used as the model-agnostic
normalization layer, while the rest of the pipeline consumes our local schema.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from typing import Any

from .schema import PerceptionDetection


def supervision_available() -> bool:
    return importlib.util.find_spec("supervision") is not None


def _item(values: Any, index: int) -> Any:
    if values is None:
        return None
    try:
        return values[index]
    except TypeError:
        return list(values)[index]


def _optional_int(values: Any, index: int) -> int | None:
    value = _item(values, index)
    if value is None:
        return None
    return int(value)


def _optional_float(values: Any, index: int) -> float | None:
    value = _item(values, index)
    if value is None:
        return None
    return float(value)


def _class_name(data: Mapping[str, Any], class_names: Mapping[int, str] | None, class_id: int | None, index: int) -> str | None:
    if "class_name" in data:
        value = _item(data["class_name"], index)
        return None if value is None else str(value)
    if class_id is not None and class_names:
        return class_names.get(class_id)
    return None


def detections_from_supervision(
    detections: Any,
    *,
    source_video: str,
    frame_index: int,
    time_sec: float,
    frame_width: int,
    frame_height: int,
    class_names: Mapping[int, str] | None = None,
    min_confidence: float = 0.0,
) -> list[PerceptionDetection]:
    """Convert a Supervision-like Detections object to local detections.

    The object must expose Supervision's stable fields: `xyxy`, `confidence`,
    `class_id`, `tracker_id`, and optional `data`. Tests use a fake object with
    the same attributes so CI can validate the contract without installing the
    heavy video stack.
    """
    xyxy: Sequence[Sequence[float]] | None = getattr(detections, "xyxy", None)
    if xyxy is None:
        raise ValueError("detections must expose xyxy bounding boxes")

    confidence = getattr(detections, "confidence", None)
    class_id_values = getattr(detections, "class_id", None)
    tracker_values = getattr(detections, "tracker_id", None)
    data = getattr(detections, "data", {}) or {}

    converted: list[PerceptionDetection] = []
    for index, bbox in enumerate(xyxy):
        conf = _optional_float(confidence, index)
        if conf is not None and conf < min_confidence:
            continue
        class_id = _optional_int(class_id_values, index)
        converted.append(
            PerceptionDetection(
                source_video=source_video,
                frame_index=frame_index,
                time_sec=time_sec,
                xyxy=tuple(float(v) for v in bbox),
                frame_width=frame_width,
                frame_height=frame_height,
                confidence=conf,
                class_id=class_id,
                class_name=_class_name(data, class_names, class_id, index),
                tracker_id=_optional_int(tracker_values, index),
            )
        )
    return converted


def to_event_metadata(detection: PerceptionDetection) -> dict[str, Any]:
    return detection.to_event_metadata()
