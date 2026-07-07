"""Sidecar producer adapter for external detector/tracker outputs.

This module does not invent detections. It normalizes output from a configured
perception backend into the SportReel `.perception.json` contract. When no
backend is configured it writes an explicit skipped sidecar so the runtime can
fail closed when perception is required.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .schema import PerceptionDetection
from .track_stitching import stitch_sidecar_payload

_BACKEND_ENV = "SPORTREEL_PERCEPTION_BACKEND"
_DETECTIONS_JSON_ENV = "SPORTREEL_PERCEPTION_DETECTIONS_JSON"
_MIN_CONFIDENCE_ENV = "SPORTREEL_PERCEPTION_MIN_CONFIDENCE"
_ULTRALYTICS_MODEL_ENV = "SPORTREEL_ULTRALYTICS_MODEL"
_ULTRALYTICS_TRACKER_ENV = "SPORTREEL_ULTRALYTICS_TRACKER"
_ULTRALYTICS_FPS_ENV = "SPORTREEL_ULTRALYTICS_FPS"
_DEFAULT_ULTRALYTICS_TRACKER = "botsort.yaml"
_JSON_BACKENDS = {"json", "external_json", "detector_json"}
_ULTRALYTICS_BACKENDS = {"ultralytics", "yolo", "yolo_track"}
_NOT_CONFIGURED = {"", "none", "not_configured", "disabled"}


def _num(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc


def _int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _bbox(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise ValueError("bbox_xyxy must contain four numeric values")
    return tuple(float(v) for v in value)  # type: ignore[return-value]


def _min_confidence() -> float:
    raw = os.getenv(_MIN_CONFIDENCE_ENV, "0").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{_MIN_CONFIDENCE_ENV} must be numeric") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{_MIN_CONFIDENCE_ENV} must be in [0, 1]")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def write_status_sidecar(video_path: str, output_path: Path, status: str, reason: str, *, backend: str | None = None) -> dict[str, Any]:
    payload = {
        "source_video": video_path,
        "status": status,
        "reason": reason,
        "backend": backend,
        "detections": [],
    }
    _write_json_atomic(output_path, payload)
    return payload


def _iter_detection_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if isinstance(payload.get("detections"), list):
        return [item for item in payload["detections"] if isinstance(item, Mapping)]

    items: list[Mapping[str, Any]] = []
    frames = payload.get("frames")
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, Mapping):
                continue
            detections = frame.get("detections")
            if not isinstance(detections, list):
                continue
            defaults = {
                "frame_index": frame.get("frame_index"),
                "time_sec": frame.get("time_sec"),
                "frame_width": frame.get("frame_width") or frame.get("width"),
                "frame_height": frame.get("frame_height") or frame.get("height"),
            }
            for detection in detections:
                if isinstance(detection, Mapping):
                    items.append({**defaults, **detection})
    return items


def _normalize_detection(source_video: str, item: Mapping[str, Any], *, min_confidence: float) -> dict[str, Any] | None:
    confidence = _optional_float(item.get("confidence"))
    if confidence is not None and confidence < min_confidence:
        return None
    class_id = _optional_int(item.get("class_id"))
    class_name = item.get("class_name")
    if class_name is None and class_id is None:
        raise ValueError("each detection must include class_id or class_name")
    tracker_id = _optional_int(item.get("canonical_track_id", item.get("track_id")))
    detection = PerceptionDetection(
        source_video=source_video,
        frame_index=_int(item.get("frame_index"), "frame_index"),
        time_sec=_num(item.get("time_sec"), "time_sec"),
        xyxy=_bbox(item.get("bbox_xyxy") or item.get("xyxy")),
        frame_width=_int(item.get("frame_width"), "frame_width"),
        frame_height=_int(item.get("frame_height"), "frame_height"),
        confidence=confidence,
        class_id=class_id,
        class_name=(None if class_name is None else str(class_name)),
        tracker_id=tracker_id,
    )
    if detection.tracker_id is None:
        raise ValueError("each production detection must include track_id")
    normalized = {
        "frame_index": detection.frame_index,
        "time_sec": detection.time_sec,
        "bbox_xyxy": list(detection.xyxy),
        "frame_width": detection.frame_width,
        "frame_height": detection.frame_height,
        "confidence": detection.confidence,
        "class_id": detection.class_id,
        "class_name": detection.class_name,
        "track_id": detection.tracker_id,
    }
    if item.get("raw_track_id") is not None:
        normalized["raw_track_id"] = item.get("raw_track_id")
    return normalized


def _tensor_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value if isinstance(value, list) else list(value)


def detections_from_ultralytics_result(result: Any, *, frame_index: int, fps: float | None = None) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or not bool(getattr(boxes, "is_track", False)):
        return []
    track_ids = _tensor_values(getattr(boxes, "id", None))
    if not track_ids:
        return []
    xyxy = _tensor_values(getattr(boxes, "xyxy", None))
    confidence = _tensor_values(getattr(boxes, "conf", None))
    class_ids = _tensor_values(getattr(boxes, "cls", None))
    names = getattr(result, "names", {}) or {}
    height, width = (getattr(result, "orig_shape", None) or (0, 0))[:2]
    detections = []
    for index, track_id in enumerate(track_ids):
        class_id = None if index >= len(class_ids) else int(class_ids[index])
        class_name = names.get(class_id) if isinstance(names, dict) and class_id is not None else None
        item = {
            "frame_index": frame_index,
            "time_sec": 0.0 if fps is None else frame_index / fps,
            "bbox_xyxy": [float(value) for value in xyxy[index]],
            "frame_width": int(width),
            "frame_height": int(height),
            "confidence": None if index >= len(confidence) else float(confidence[index]),
            "class_id": class_id,
            "class_name": None if class_name is None else str(class_name),
            "track_id": int(track_id),
        }
        normalized = _normalize_detection(str(getattr(result, "path", "")), item, min_confidence=_min_confidence())
        if normalized is not None:
            detections.append(normalized)
    return detections


def _optional_fps(value: str | None = None) -> float | None:
    raw = (value if value is not None else os.getenv(_ULTRALYTICS_FPS_ENV, "")).strip()
    if not raw:
        return None
    fps = float(raw)
    if fps <= 0:
        raise ValueError(f"{_ULTRALYTICS_FPS_ENV} must be positive")
    return fps


def sidecar_from_detection_json(video_path: str, output_path: Path, detections_json: Path, *, backend: str = "external_json") -> dict[str, Any]:
    with open(detections_json, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("detector JSON root must be an object")
    detections = []
    for item in _iter_detection_items(payload):
        detection = _normalize_detection(video_path, item, min_confidence=_min_confidence())
        if detection is not None:
            detections.append(detection)
    sidecar = {
        "source_video": video_path,
        "status": "ok",
        "backend": backend,
        "detections": detections,
    }
    sidecar = stitch_sidecar_payload(sidecar, source_video=video_path)
    _write_json_atomic(output_path, sidecar)
    return sidecar


def sidecar_from_ultralytics(video_path: str, output_path: Path, *, model: str | None = None, tracker: str | None = None, fps: str | None = None) -> dict[str, Any]:
    model_path = (model if model is not None else os.getenv(_ULTRALYTICS_MODEL_ENV, "")).strip()
    if not model_path:
        return write_status_sidecar(video_path, output_path, "skipped", "ultralytics_model_not_configured", backend="ultralytics")
    try:
        from ultralytics import YOLO
    except ImportError:
        return write_status_sidecar(video_path, output_path, "skipped", "ultralytics_not_installed", backend="ultralytics")
    tracker_name = (tracker if tracker is not None else os.getenv(_ULTRALYTICS_TRACKER_ENV, "")).strip() or _DEFAULT_ULTRALYTICS_TRACKER
    model_obj = YOLO(model_path)
    detections: list[dict[str, Any]] = []
    for frame_index, result in enumerate(model_obj.track(source=video_path, tracker=tracker_name, persist=True, stream=True, verbose=False)):
        detections.extend(detections_from_ultralytics_result(result, frame_index=frame_index, fps=_optional_fps(fps)))
    sidecar = {
        "source_video": video_path,
        "status": "ok",
        "backend": "ultralytics",
        "model": model_path,
        "tracker": tracker_name,
        "detections": detections,
    }
    sidecar = stitch_sidecar_payload(sidecar, source_video=video_path)
    _write_json_atomic(output_path, sidecar)
    return sidecar


def generate_sidecar(
    video_path: str,
    output_path: str,
    *,
    backend: str | None = None,
    detections_json: str | None = None,
    ultralytics_model: str | None = None,
    ultralytics_tracker: str | None = None,
    fps: str | None = None,
) -> dict[str, Any]:
    selected_backend = (backend if backend is not None else os.getenv(_BACKEND_ENV, "")).strip().lower()
    output = Path(output_path)
    if selected_backend in _NOT_CONFIGURED:
        return write_status_sidecar(video_path, output, "skipped", "perception_backend_not_configured", backend=selected_backend or None)
    if selected_backend in _JSON_BACKENDS:
        detector_output = (detections_json if detections_json is not None else os.getenv(_DETECTIONS_JSON_ENV, "")).strip()
        if not detector_output:
            return write_status_sidecar(video_path, output, "skipped", "perception_detections_json_not_configured", backend=selected_backend)
        return sidecar_from_detection_json(video_path, output, Path(detector_output), backend=selected_backend)
    if selected_backend in _ULTRALYTICS_BACKENDS:
        return sidecar_from_ultralytics(video_path, output, model=ultralytics_model, tracker=ultralytics_tracker, fps=fps)
    return write_status_sidecar(video_path, output, "skipped", f"unsupported_perception_backend:{selected_backend}", backend=selected_backend)


__all__ = [
    "detections_from_ultralytics_result",
    "generate_sidecar",
    "sidecar_from_detection_json",
    "sidecar_from_ultralytics",
    "write_status_sidecar",
]
