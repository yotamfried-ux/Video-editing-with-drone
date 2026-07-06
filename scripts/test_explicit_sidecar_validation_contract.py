#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.perception.runtime import validate_sidecar


def main() -> int:
    tmp = ROOT / ".tmp_explicit_sidecar_validation"
    tmp.mkdir(exist_ok=True)
    video = tmp / "sample.mp4"
    default_sidecar = tmp / "sample.perception.json"
    explicit_sidecar = tmp / "explicit.perception.json"
    try:
        base_detection = {
            "frame_index": 0,
            "time_sec": 0.0,
            "bbox_xyxy": [10, 20, 110, 220],
            "frame_width": 640,
            "frame_height": 480,
            "confidence": 0.9,
            "class_name": "person",
            "track_id": 1,
        }
        default_sidecar.write_text(json.dumps({"status": "ok", "detections": [base_detection, {**base_detection, "track_id": 2}]}), encoding="utf-8")
        explicit_sidecar.write_text(json.dumps({"status": "ok", "detections": [base_detection]}), encoding="utf-8")
        summary = validate_sidecar(str(video), explicit_sidecar)
        assert summary["path"] == str(explicit_sidecar)
        assert summary["detection_count"] == 1
    finally:
        for path in sorted(tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
        if tmp.exists():
            tmp.rmdir()
    print("Explicit sidecar validation contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
