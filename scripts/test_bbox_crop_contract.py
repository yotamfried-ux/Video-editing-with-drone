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


def main() -> int:
    crop_math = _read("pipeline/perception/crop_math.py")
    schema = _read("pipeline/perception/schema.py")
    runtime = _read("pipeline/runtime_quality.py")
    workflow = _read(".github/workflows/operator-smoke-check.yml")
    for text in (crop_math, schema, runtime, _read("scripts/test_bbox_crop_contract.py")):
        ast.parse(text)

    require_tokens("schema metadata", schema, ["perception_frame_width", "perception_frame_height"])
    require_tokens("crop resolver", crop_math, ["def resolve_event_crop", "perception_crop_usable", "missing_frame_dimensions", "low_visible_ratio"])
    require_tokens("runtime guard", runtime, ["_MIN_VISIBLE_RATIO = 0.35", "def _normalize_event_crop", "weak/framing-risk"])
    require_tokens("workflow coverage", workflow, ["scripts/test_bbox_crop_contract.py", "Validate BBox crop contract"])

    from pipeline.perception.crop_math import resolve_event_crop
    import pipeline.runtime_quality as rq

    event = {
        "type": "snap", "score": 8, "start": 1.0, "end": 8.0,
        "crop_x": 0.99, "crop_y": 0.99,
        "bbox_xyxy": [100, 200, 300, 400],
        "perception_frame_width": 800, "perception_frame_height": 600,
    }
    resolved = resolve_event_crop(event)
    if round(resolved["crop_x"], 4) != 0.25 or round(resolved["crop_y"], 4) != 0.5:
        raise SystemExit("bbox crop must override event crop values")
    normalized = rq._normalize_event_crop(event)
    if normalized is None or normalized["crop_x"] != 0.25 or normalized["crop_y"] != 0.5:
        raise SystemExit("runtime quality must pass bbox crop values onward")

    low_visible = {**event, "bbox_xyxy": [-1000, -1000, -900, -900]}
    if rq._normalize_event_crop(low_visible) is not None:
        raise SystemExit("low-visible bbox event should fail safe")

    missing_dimensions = {"bbox_xyxy": [0, 0, 10, 10], "crop_x": 0.5, "crop_y": 0.5}
    if resolve_event_crop(missing_dimensions)["perception_crop_usable"]:
        raise SystemExit("bbox event without frame dimensions must be unusable")

    no_bbox = resolve_event_crop({"crop_x": 1.7, "crop_y": -1.2})
    if no_bbox["crop_x"] != 1.0 or no_bbox["crop_y"] != 0.0 or no_bbox["crop_source"] != "event":
        raise SystemExit("legacy events should keep clamped event crop")

    print("BBox crop contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
