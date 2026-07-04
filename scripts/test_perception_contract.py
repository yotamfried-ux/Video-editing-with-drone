#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


class FakeDetections:
    xyxy = [[0, 10, 100, 210], [300, 100, 500, 400]]
    confidence = [0.92, 0.31]
    class_id = [0, 0]
    tracker_id = [7, 8]
    data = {"class_name": ["athlete", "athlete"]}


def require_runtime_contract() -> None:
    from pipeline.perception.crop_math import bbox_center_norm, bbox_to_crop, bbox_visible_ratio
    from pipeline.perception.schema import PerceptionDetection
    from pipeline.perception.supervision_adapter import detections_from_supervision, supervision_available

    detections = detections_from_supervision(
        FakeDetections(),
        source_video="raw/session/clip.mp4",
        frame_index=12,
        time_sec=1.5,
        frame_width=640,
        frame_height=480,
        min_confidence=0.5,
    )
    if len(detections) != 1:
        raise SystemExit("min_confidence should filter low-confidence detections")
    det = detections[0]
    if det.tracker_id != 7 or det.class_name != "athlete" or det.confidence != 0.92:
        raise SystemExit("adapter did not preserve tracker/class/confidence fields")
    if det.xyxy != (0.0, 10.0, 100.0, 210.0):
        raise SystemExit("adapter did not normalize xyxy bbox")

    crop = det.crop
    if round(crop["crop_x"], 4) != round(50 / 640, 4):
        raise SystemExit("bbox crop_x should use bbox center")
    if round(crop["crop_y"], 4) != round(110 / 480, 4):
        raise SystemExit("bbox crop_y should use bbox center")
    if crop["visible_ratio"] != 1.0:
        raise SystemExit("fully in-frame bbox should have visible_ratio=1")

    if round(bbox_visible_ratio((-10, -10, 10, 10), 100, 100), 2) != 0.25:
        raise SystemExit("visible_ratio should account for bbox outside the frame")
    if bbox_center_norm((40, 20, 60, 40), 100, 100) != (0.5, 0.3):
        raise SystemExit("bbox_center_norm should return normalized bbox center")
    if bbox_to_crop((40, 20, 60, 40), 100, 100)["visible_ratio"] != 1.0:
        raise SystemExit("bbox_to_crop should include visible_ratio")

    metadata = det.to_event_metadata()
    required = {"bbox_xyxy", "perception_confidence", "perception_class_name", "track_id", "crop_x", "crop_y", "visible_ratio"}
    missing = required - set(metadata)
    if missing:
        raise SystemExit(f"event metadata missing fields: {sorted(missing)}")

    PerceptionDetection(
        source_video="clip.mp4",
        frame_index=0,
        time_sec=0.0,
        xyxy=(1, 2, 3, 4),
        frame_width=10,
        frame_height=10,
    )
    if not isinstance(supervision_available(), bool):
        raise SystemExit("supervision_available must return bool")


def main() -> int:
    requirements = _read("requirements.txt")
    workflow = _read(".github/workflows/operator-smoke-check.yml")
    schema = _read("pipeline/perception/schema.py")
    adapter = _read("pipeline/perception/supervision_adapter.py")
    crop_math = _read("pipeline/perception/crop_math.py")

    for label, text in {
        "perception schema": schema,
        "supervision adapter": adapter,
        "crop math": crop_math,
        "perception contract": _read("scripts/test_perception_contract.py"),
    }.items():
        ast.parse(text)

    require_tokens("requirements", requirements, ["supervision>=0.29.0,<0.30.0"])
    require_tokens("perception schema", schema, ["class PerceptionDetection", "xyxy", "confidence", "class_id", "class_name", "tracker_id", "visible_ratio", "to_event_metadata", "bbox_xyxy"])
    require_tokens("supervision adapter", adapter, ["def supervision_available()", 'find_spec("supervision")', "def detections_from_supervision", "xyxy", "confidence", "class_id", "tracker_id", "min_confidence", "PerceptionDetection("])
    require_no_tokens("perception foundation", "\n".join([schema, adapter, crop_math]), ["from supervision.tracker", "update_with_detections"])
    require_tokens("operator smoke workflow perception coverage", workflow, ["pipeline/perception/**", "scripts/test_perception_contract.py", "Validate Perception contract"])

    require_runtime_contract()
    print("Perception foundation contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
