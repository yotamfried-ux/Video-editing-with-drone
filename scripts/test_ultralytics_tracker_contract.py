#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeBoxes:
    is_track = True
    id = [12, 13]
    xyxy = [[100, 120, 300, 520], [10, 20, 30, 40]]
    conf = [0.93, 0.11]
    cls = [0, 0]


class FakeResult:
    boxes = FakeBoxes()
    orig_shape = (720, 1280)
    names = {0: "person"}
    path = "source clip.mp4"


def _clear_env() -> None:
    for key in [
        "SPORTREEL_PERCEPTION_BACKEND",
        "SPORTREEL_PERCEPTION_MIN_CONFIDENCE",
        "SPORTREEL_ULTRALYTICS_MODEL",
        "SPORTREEL_ULTRALYTICS_TRACKER",
        "SPORTREEL_ULTRALYTICS_FPS",
    ]:
        os.environ.pop(key, None)


def main() -> int:
    from pipeline.perception.producer import detections_from_ultralytics_result, generate_sidecar
    from pipeline.perception.runtime import validate_sidecar

    tmp = ROOT / ".tmp_ultralytics_tracker_contract"
    tmp.mkdir(exist_ok=True)
    video = tmp / "source clip.mp4"
    skipped_output = tmp / "ultralytics_skipped.perception.json"
    cli_output = tmp / "cli_skipped.perception.json"
    try:
        _clear_env()
        os.environ["SPORTREEL_PERCEPTION_MIN_CONFIDENCE"] = "0.5"
        detections = detections_from_ultralytics_result(FakeResult(), frame_index=12, fps=30.0)
        if len(detections) != 1:
            raise SystemExit("Ultralytics mapper must filter low-confidence track boxes")
        detection = detections[0]
        if detection.get("track_id") != 12:
            raise SystemExit("Ultralytics mapper must preserve boxes.id as track_id")
        if detection.get("bbox_xyxy") != [100.0, 120.0, 300.0, 520.0]:
            raise SystemExit("Ultralytics mapper must preserve boxes.xyxy")
        if detection.get("confidence") != 0.93 or detection.get("class_id") != 0 or detection.get("class_name") != "person":
            raise SystemExit("Ultralytics mapper must preserve boxes.conf, boxes.cls, and names")
        if detection.get("frame_width") != 1280 or detection.get("frame_height") != 720:
            raise SystemExit("Ultralytics mapper must preserve result.orig_shape")
        if round(detection.get("time_sec"), 2) != 0.4:
            raise SystemExit("Ultralytics mapper must derive time_sec from frame_index/fps")

        skipped = generate_sidecar(str(video), str(skipped_output), backend="ultralytics")
        if skipped.get("status") != "skipped" or skipped.get("reason") != "ultralytics_model_not_configured":
            raise SystemExit("Unconfigured Ultralytics backend must fail safe")
        skipped_payload = json.loads(skipped_output.read_text(encoding="utf-8"))
        if skipped_payload.get("detections") != [] or skipped_payload.get("backend") != "ultralytics":
            raise SystemExit("Skipped Ultralytics sidecar must be explicit and detection-free")
        if validate_sidecar(str(video), skipped_output).get("status") != "skipped":
            raise SystemExit("Runtime must validate unconfigured Ultralytics output as skipped")

        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_perception_sidecar.py"), str(video), str(cli_output), "--backend", "ultralytics"],
            check=True,
            cwd=ROOT,
        )
        if validate_sidecar(str(video), cli_output).get("status") != "skipped":
            raise SystemExit("CLI Ultralytics backend must fail safe without model")
    finally:
        _clear_env()
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
    print("Ultralytics tracker contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
