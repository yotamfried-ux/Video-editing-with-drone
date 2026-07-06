#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.perception.producer import generate_sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a SportReel perception sidecar from a configured backend output.")
    parser.add_argument("video_path", help="Input source video path")
    parser.add_argument("output_path", help="Output .perception.json path")
    parser.add_argument("--backend", help="Backend adapter to use, e.g. external_json or ultralytics")
    parser.add_argument("--detections-json", help="External detector/tracker JSON output to normalize")
    parser.add_argument("--ultralytics-model", help="Ultralytics YOLO model path/name; can also use SPORTREEL_ULTRALYTICS_MODEL")
    parser.add_argument("--ultralytics-tracker", help="Ultralytics tracker config; defaults to botsort.yaml for moving-camera/drone footage")
    parser.add_argument("--fps", help="FPS override used to derive time_sec for tracker results")
    args = parser.parse_args()

    try:
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
    print(f"perception sidecar status={status} detections={len(summary.get('detections', []) or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
