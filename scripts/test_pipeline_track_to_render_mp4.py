#!/usr/bin/env python3
"""Isolated real MP4: detector JSON -> canonical tracks -> event binding -> real editor.

The detections are synthetic ground truth, NOT a run of YOLO/BoT-SORT. The
production normalization, stitching, binding and FFmpeg renderer ARE exercised.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_pipeline_real_mp4_renderer import run, probe, pixel_at


def main() -> None:
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="sportreel-track-render-") as d:
        folder = Path(d)
        sys.modules["config"] = types.SimpleNamespace(
            TMP_DIR=str(folder), QUALITY_LOG_FILE=str(folder / "quality.jsonl"),
            MIN_SOURCE_HEIGHT=1440, SLOWMO_INTERPOLATE=False,
        )
        from pipeline.perception.producer import sidecar_from_detection_json
        from pipeline.perception.runtime import load_sidecar_detections, enrich_event
        from pipeline.stages import editor

        source = folder / "tracked_two_subjects.mp4"
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:r=30:d=6",
            "-vf", "drawbox=x=140:y=300:w=450:h=450:color=green:t=fill,"
                   "drawbox=x=1330:y=300:w=450:h=450:color=red:t=fill",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(source))
        items = []
        for t in (0.5, 1.5, 2.5, 3.5):
            for label, x1, track in (("left", 140, 10 if t < 2 else 20),
                                      ("right", 1330, 30)):
                items.append({
                    "frame_index": int(t * 30), "time_sec": t,
                    "bbox_xyxy": [x1, 300, x1 + 450, 750],
                    "frame_width": 1920, "frame_height": 1080,
                    "confidence": 0.98, "class_id": 0, "class_name": "person",
                    "track_id": track,
                })
        detections_json = folder / "detections.json"
        detections_json.write_text(json.dumps({"detections": items}))
        sidecar = sidecar_from_detection_json(
            str(source), Path(str(source) + ".perception.json"), detections_json)
        by_raw = {}
        for item in sidecar["detections"]:
            by_raw.setdefault(item["raw_track_id"], set()).add(item["track_id"])
        assert by_raw[10] == {10} and by_raw[20] == {10}, by_raw
        assert by_raw[30] == {30}, by_raw
        detections = load_sidecar_detections(str(source))
        assert len(detections) == 8

        info = {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": 1.0, "can_slowmo": False}
        outputs = {}
        for index, (label, cx, expected_id) in enumerate(
                (("left", .20, "10"), ("right", .80, "30"))):
            event = {"start": 0, "end": 4, "type": "highlight", "score": 6,
                     "crop_x": cx, "crop_y": .5,
                     "edit": {"zoom": 1.0, "slowmo": False}}
            enriched = enrich_event(event, detections)
            assert enriched["perception_evidence_status"] == "tracker_sidecar", enriched
            assert enriched["target_track_id"] == expected_id, enriched
            assert enriched["perception_detection_count"] == 8, enriched
            result = editor.cut_clip(str(source), enriched, index,
                                     sport="surfing", source_info=info, target_fps=30)
            assert result and Path(result).is_file()
            spec = probe(Path(result))
            assert spec["codec_name"] == "h264" and (
                spec["width"], spec["height"]) == (1080, 1920), spec
            rgb = pixel_at(Path(result), 540, 960)
            if label == "left":
                assert rgb[1] > rgb[0] * 1.25 and rgb[1] > rgb[2] * 1.25, rgb
            else:
                assert rgb[0] > rgb[1] * 1.25 and rgb[0] > rgb[2] * 1.25, rgb
            outputs[label] = {"canonical_track_id": enriched["target_track_id"],
                              "crop_x": enriched["crop_x"], "decoded_rgb": rgb,
                              "rendered_video": Path(result).name}
        missing = enrich_event({"start": 0, "end": 4, "crop_x": .5}, [])
        assert missing["perception_evidence_status"] == "no_tracker_detection"
        assert "target_track_id" not in missing
        print(json.dumps({"status": "PASS", "scope": "synthetic detection JSON to real FFmpeg",
                          "actual_detector_executed": False,
                          "canonical_stitch": {str(k): list(v) for k, v in by_raw.items()},
                          "outputs": outputs, "missing_detection": "flagged"}, indent=2))


if __name__ == "__main__":
    main()
