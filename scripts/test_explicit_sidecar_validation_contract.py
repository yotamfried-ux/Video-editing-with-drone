#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from pipeline.perception.runtime import validate_sidecar

ROOT = Path(__file__).resolve().parents[1]


def _write_sidecar(path: Path, detection_count: int) -> None:
    path.write_text(
        json.dumps({
            "source_video": "sample.mp4",
            "status": "ok",
            "detections": [
                {
                    "frame_index": index,
                    "time_sec": float(index),
                    "bbox_xyxy": [10, 20, 110, 220],
                    "frame_width": 640,
                    "frame_height": 480,
                    "confidence": 0.9,
                    "class_name": "person",
                    "track_id": index + 1,
                }
                for index in range(detection_count)
            ],
        }),
        encoding="utf-8",
    )


def main() -> int:
    tmp = ROOT / ".tmp_explicit_sidecar_validation"
    tmp.mkdir(exist_ok=True)
    video = tmp / "sample.mp4"
    default_sidecar = tmp / "sample.perception.json"
    explicit_sidecar = tmp / "explicit.perception.json"
    try:
        _write_sidecar(default_sidecar, 2)
        _write_sidecar(explicit_sidecar, 1)
        summary = validate_sidecar(str(video), explicit_sidecar)
        if summary.get("path") != str(explicit_sidecar):
            raise SystemExit("validate_sidecar must report the explicit sidecar path")
        if summary.get("detection_count") != 1:
            raise SystemExit("validate_sidecar must count detections from the explicit sidecar payload")
    finally:
        for path in sorted(tmp.rglob("*"), reverse=True):
            try:
                path.unlink()
            except IsADirectoryError:
                path.rmdir()
            except FileNotFoundError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass
    print("Explicit sidecar validation contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
