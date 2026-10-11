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
import types
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
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=3",
             "-t", "3", "-vf", "scale=640:384,format=yuv420p",
             "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", "-shortest", str(source)],
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
        # Continue the SAME real detector event into the production FFmpeg editor.
        # This proves real YOLO/BoT-SORT -> canonical event -> actual MP4 render,
        # without replacing detections with synthetic ground truth.
        sys.modules["config"] = types.SimpleNamespace(
            TMP_DIR=str(root), QUALITY_LOG_FILE=str(root / "quality.jsonl"),
            MIN_SOURCE_HEIGHT=1440, SLOWMO_INTERPOLATE=False,
        )
        from pipeline.stages import editor
        from test_pipeline_real_mp4_renderer import probe
        enriched["edit"] = {"zoom": 1.0, "slowmo": False}
        source_info = {"width": 640, "height": 384, "fps": 8.0,
                       "zoom_headroom": 1.0, "can_slowmo": False}
        rendered = editor.cut_clip(str(source), enriched, 0,
                                   sport="surfing", source_info=source_info,
                                   target_fps=24)
        assert rendered and Path(rendered).is_file(), "real detector event failed to render"
        rendered_spec = probe(Path(rendered))
        assert rendered_spec["codec_name"] == "h264", rendered_spec
        audio_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(rendered)],
            check=True, capture_output=True, text=True)
        assert "audio" in audio_probe.stdout, "rendered fixture missing audio"
        assert (rendered_spec["width"], rendered_spec["height"]) == (1080, 1920), rendered_spec
        # Carry the SAME real-detector render into production manifest/QA policy.
        # Controlled QA verdict: this does NOT execute an LLM visual reviewer.
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(root / "manifest.json")
        from pipeline import publishable_reel_policy as policy
        from pipeline.publishable_qa_evidence import record_qa_result, apply_final_qa_evidence
        policy.reset_manifest()
        enriched["athlete_id"] = str(enriched["target_track_id"])
        spec = {"duration": 3, "width": 1080, "height": 1920,
                "aspect": 9 / 16, "has_audio": True}
        policy.record_athlete_outcome(
            sport="surfing", athlete_label="tracked person",
            final_reels=[rendered], events_by_reel={rendered: [enriched]},
            flagged_paths=set(), specs_by_path={rendered: spec})
        token = "real-yolo-render-qa"
        record_qa_result(rendered, {"verdict": "PASS",
                                   "overall": "isolated controlled QA fixture"},
                         invocation_token=token)
        blocked = apply_final_qa_evidence(
            sport="surfing", athlete_label="tracked person",
            final_reels=[rendered], invocation_token=token)
        assert not blocked, blocked
        manifest = json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())
        assert len(manifest["athletes"]) == 1, manifest
        part = manifest["athletes"][0]["parts"][0]
        assert part["qa_verdict"] == "PASS" and part["qa_evidence_recorded"], part
        assert part["render_ready"] is True, part
        assert manifest["summary"]["publishable_athlete_count"] == 0, manifest
        assert manifest["summary"]["coverage_gap_count"] == 1, manifest
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
            "actual_ffmpeg_render": True,
            "actual_manifest_qa_policy": True,
            "qa_verdict_controlled_not_llm": True,
            "upload_executed": False,
            "publication_fail_closed": True,
            "rendered_dimensions": [1080, 1920],
        }
        print(json.dumps(report, indent=2))
        (root / "qualification.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
