#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.perception.producer import detections_from_ultralytics_result, generate_sidecar
from pipeline.perception.track_stitching import stitch_sidecar_payload

_ULTRALYTICS_BACKENDS = {"ultralytics", "yolo", "yolo_track"}
_DEFAULT_TRACKER = "botsort.yaml"
_DEFAULT_VID_STRIDE = 10
_DEFAULT_IMGSZ = 640


def _positive_int(raw: str | None, default: int, label: str) -> int:
    value = (raw or "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _fps(raw: str | None, video_path: str) -> float | None:
    value = (raw or os.getenv("SPORTREEL_ULTRALYTICS_FPS", "")).strip()
    if value:
        fps = float(value)
        if fps <= 0:
            raise ValueError("fps must be positive")
        return fps
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(video_path)
        detected = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap.release()
        return detected if detected > 0 else None
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _fast_ultralytics_sidecar(args: argparse.Namespace) -> dict[str, Any]:
    model = (args.ultralytics_model or os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "")).strip()
    if not model:
        return generate_sidecar(args.video_path, args.output_path, backend="ultralytics")
    tracker = (args.ultralytics_tracker or os.getenv("SPORTREEL_ULTRALYTICS_TRACKER", "")).strip() or _DEFAULT_TRACKER
    stride = _positive_int(args.ultralytics_vid_stride or os.getenv("SPORTREEL_ULTRALYTICS_VID_STRIDE", ""), _DEFAULT_VID_STRIDE, "vid_stride")
    imgsz = _positive_int(args.ultralytics_imgsz or os.getenv("SPORTREEL_ULTRALYTICS_IMGSZ", ""), _DEFAULT_IMGSZ, "imgsz")
    device = (args.ultralytics_device or os.getenv("SPORTREEL_ULTRALYTICS_DEVICE", "")).strip()
    fps = _fps(args.fps, args.video_path)

    from ultralytics import YOLO

    track_kwargs: dict[str, Any] = {
        "source": args.video_path,
        "tracker": tracker,
        "persist": True,
        "stream": True,
        "verbose": False,
        "vid_stride": stride,
        "imgsz": imgsz,
        "classes": [0],
    }
    if device:
        track_kwargs["device"] = device

    model_obj = YOLO(model)
    detections: list[dict[str, Any]] = []
    for result_index, result in enumerate(model_obj.track(**track_kwargs)):
        detections.extend(detections_from_ultralytics_result(result, frame_index=result_index * stride, fps=fps))

    payload = {
        "source_video": args.video_path,
        "status": "ok",
        "backend": "ultralytics",
        "model": model,
        "tracker": tracker,
        "vid_stride": stride,
        "imgsz": imgsz,
        "classes": [0],
        "detections": detections,
    }
    payload = stitch_sidecar_payload(payload, source_video=args.video_path)
    _write_json(Path(args.output_path), payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a SportReel perception sidecar from a configured backend output.")
    parser.add_argument("video_path", help="Input source video path")
    parser.add_argument("output_path", help="Output .perception.json path")
    parser.add_argument("--backend", help="Backend adapter to use, e.g. external_json or ultralytics")
    parser.add_argument("--detections-json", help="External detector/tracker JSON output to normalize")
    parser.add_argument("--ultralytics-model", help="Ultralytics YOLO model path/name; can also use SPORTREEL_ULTRALYTICS_MODEL")
    parser.add_argument("--ultralytics-tracker", help="Ultralytics tracker config; defaults to botsort.yaml for moving-camera/drone footage")
    parser.add_argument("--ultralytics-vid-stride", help="Frame stride for faster long-video tracking; default 10 on CPU runs")
    parser.add_argument("--ultralytics-imgsz", help="Ultralytics inference image size; default 640")
    parser.add_argument("--ultralytics-device", help="Optional Ultralytics device override, e.g. cpu or cuda:0")
    parser.add_argument("--fps", help="FPS override used to derive time_sec for tracker results")
    args = parser.parse_args()

    try:
        backend = (args.backend or "").strip().lower()
        if backend in _ULTRALYTICS_BACKENDS:
            summary = _fast_ultralytics_sidecar(args)
        else:
            summary = generate_sidecar(
                args.video_path,
                args.output_path,
                backend=args.backend,
                detections_json=args.detections_json,
                ultralytics_model=args.ultralytics_model,
                ultralytics_tracker=args.ultralytics_tracker,
                fps=args.fps,
            )
    except Exception as exc:
        print(f"perception sidecar generation failed: {exc}", file=sys.stderr)
        return 1

    status = str(summary.get("status") or "ok").lower()
    stitching = summary.get("track_stitching") if isinstance(summary.get("track_stitching"), dict) else {}
    print(
        f"perception sidecar status={status} detections={len(summary.get('detections', []) or [])} "
        f"tracks={stitching.get('raw_track_count', '?')}→{stitching.get('canonical_track_count', '?')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
