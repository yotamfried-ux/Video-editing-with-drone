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
        "SPORTREEL_ULTRALYTICS_VID_STRIDE",
        "SPORTREEL_ULTRALYTICS_IMGSZ",
        "SPORTREEL_ULTRALYTICS_DEVICE",
    ]:
        os.environ.pop(key, None)


def _require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def _det(track_id: int, time_sec: float, bbox: list[float]) -> dict:
    return {
        "frame_index": int(time_sec * 24),
        "time_sec": time_sec,
        "bbox_xyxy": bbox,
        "frame_width": 1920,
        "frame_height": 1080,
        "confidence": 0.8,
        "class_id": 0,
        "class_name": "person",
        "track_id": track_id,
    }


def main() -> int:
    from pipeline.perception.producer import detections_from_ultralytics_result, generate_sidecar
    from pipeline.perception.runtime import validate_sidecar
    from pipeline.perception.track_stitching import stitch_detection_tracks, stitch_sidecar_payload

    cli = (ROOT / "scripts/generate_perception_sidecar.py").read_text(encoding="utf-8")
    runtime = (ROOT / "pipeline/perception/runtime.py").read_text(encoding="utf-8")
    producer = (ROOT / "pipeline/perception/producer.py").read_text(encoding="utf-8")
    _require_tokens(
        "bounded ultralytics CLI",
        cli,
        [
            "_DEFAULT_VID_STRIDE = 10",
            "_DEFAULT_IMGSZ = 640",
            "--ultralytics-vid-stride",
            "--ultralytics-imgsz",
            "vid_stride",
            "imgsz",
            "classes",
            "[0]",
            "cv2.VideoCapture",
            "result_index * stride",
            "stitch_sidecar_payload",
        ],
    )
    _require_tokens("perception timeout", runtime, ['os.getenv(_TIMEOUT_ENV, "1200")', "return 1200"])
    _require_tokens("perception producer stitching", producer, ["stitch_sidecar_payload", "raw_track_id"])

    raw = [
        _det(10, 10.0, [100, 100, 200, 300]),
        _det(10, 11.0, [115, 105, 215, 305]),
        _det(20, 12.5, [130, 110, 230, 310]),
        _det(30, 13.5, [900, 300, 1010, 520]),
        _det(40, 10.5, [120, 110, 220, 310]),
        _det(40, 12.8, [140, 115, 240, 315]),
    ]
    stitched = stitch_detection_tracks(raw, source_video="source.mp4")
    by_raw: dict[int, set[int]] = {}
    for item in stitched:
        by_raw.setdefault(int(item["raw_track_id"]), set()).add(int(item["track_id"]))
    if by_raw[20] != {10} or by_raw[30] != {30} or by_raw[40] != {40}:
        raise SystemExit(f"track stitching produced unsafe canonical IDs: {by_raw}")
    payload = stitch_sidecar_payload({"source_video": "source.mp4", "status": "ok", "detections": raw})
    if payload["track_stitching"]["raw_track_count"] != 4 or payload["track_stitching"]["canonical_track_count"] != 3:
        raise SystemExit(f"track stitching summary wrong: {payload['track_stitching']}")
    if not any(item.get("raw_track_id") != item.get("track_id") for item in payload["detections"]):
        raise SystemExit("stitched sidecar must preserve raw_track_id and expose canonical track_id")

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
