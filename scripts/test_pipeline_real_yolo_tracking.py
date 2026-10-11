#!/usr/bin/env python3
"""Run real Ultralytics YOLO + BoT-SORT on an isolated encoded MP4 fixture.

Uses the public Ultralytics bus.jpg people sample (not surfing ground truth).
No production videos or providers. Fails if model inference yields no tracked
person or if the sidecar cannot be loaded into SportReel runtime.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLE_URL = "https://ultralytics.com/images/bus.jpg"


def main() -> None:
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="sportreel-real-yolo-") as d:
        root = Path(d)
        source_image = root / "people.jpg"
        urllib.request.urlretrieve(SAMPLE_URL, source_image)
        assert source_image.stat().st_size > 10000, "sample image missing"
        source = root / "people.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-loop", "1", "-framerate", "8", "-i", str(source_image),
             "-t", "3", "-vf", "scale=640:384,format=yuv420p",
             "-c:v", "libx264", "-preset", "ultrafast", str(source)],
            check=True, timeout=90,
        )
        from pipeline.perception.producer import sidecar_from_ultralytics
        from pipeline.perception.runtime import _detections_from_payload, enrich_event
        sidecar_path = Path(str(source) + ".perception.json")
        os.environ["YOLO_CONFIG_DIR"] = str(root / "yolo-config")
        sidecar = sidecar_from_ultralytics(
            str(source), sidecar_path, model="yolo11n.pt",
            tracker="botsort.yaml", fps="8",
        )
        assert sidecar["status"] == "ok" and sidecar["backend"] == "ultralytics", sidecar
        assert sidecar_path.is_file()
        people = [item for item in sidecar["detections"] if item.get("class_id") == 0]
        tracked = [item for item in people if item.get("track_id") is not None]
        assert len(people) >= 2, f"expected >=2 person detections across video; got {len(people)}"
        assert len(tracked) >= 2, "no tracked people found; tracker integration not proven"
        loaded = _detections_from_payload(str(source), sidecar)
        assert len(loaded) == len(sidecar["detections"])
        event = {"start": 0, "end": 3, "crop_x": .5, "crop_y": .5}
        enriched = enrich_event(event, loaded)
        assert enriched["perception_evidence_status"] == "tracker_sidecar", enriched
        assert enriched.get("target_track_id") is not None, enriched
        report = {
            "result": "PASS",
            "scope": "real YOLO11n + BoT-SORT on public person video fixture",
            "model": "yolo11n.pt",
            "tracker": "botsort.yaml",
            "frames": 24,
            "person_detections": len(people),
            "tracked_person_detections": len(tracked),
            "raw_track_count": sidecar.get("track_stitching", {}).get("raw_track_count"),
            "canonical_track_count": sidecar.get("track_stitching", {}).get("canonical_track_count"),
            "event_primary_track_id": enriched["target_track_id"],
            "real_surf_footage": False,
            "production_access": False,
        }
        print(json.dumps(report, indent=2))
        (root / "qualification.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
