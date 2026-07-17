#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import os
import subprocess
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


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


class FakeDetections:
    xyxy = [[0, 10, 100, 210], [300, 100, 500, 400]]
    confidence = [0.92, 0.31]
    class_id = [0, 0]
    tracker_id = [7, 8]
    data = {"class_name": ["athlete", "athlete"]}


def require_detection_conversion(detections_obj) -> None:
    from pipeline.perception.supervision_adapter import detections_from_supervision

    detections = detections_from_supervision(
        detections_obj,
        source_video="raw/session/clip.mp4",
        frame_index=12,
        time_sec=1.5,
        frame_width=640,
        frame_height=480,
        min_confidence=0.5,
    )
    if len(detections) != 1:
        raise SystemExit("min_confidence should filter low-confidence detections")
    det = detections[0]
    if det.tracker_id != 7 or det.class_name != "athlete" or det.confidence != 0.92:
        raise SystemExit("adapter did not preserve tracker/class/confidence fields")
    if det.xyxy != (0.0, 10.0, 100.0, 210.0):
        raise SystemExit("adapter did not normalize xyxy bbox")
    if round(det.crop_x, 4) != round(50 / 640, 4):
        raise SystemExit("bbox crop_x should use bbox center")
    if round(det.crop_y, 4) != round(110 / 480, 4):
        raise SystemExit("bbox crop_y should use bbox center")
    if det.visible_ratio != 1.0:
        raise SystemExit("fully in-frame bbox should have visible_ratio=1")

    metadata = det.to_event_metadata()
    required = {"bbox_xyxy", "perception_confidence", "perception_class_name", "track_id", "crop_x", "crop_y", "visible_ratio"}
    missing = required - set(metadata)
    if missing:
        raise SystemExit(f"event metadata missing fields: {sorted(missing)}")


def require_real_supervision_contract() -> None:
    from pipeline.perception.supervision_adapter import supervision_available

    if not supervision_available():
        raise SystemExit("supervision must be installed in the smoke job")

    import numpy as np
    import supervision as sv

    detections = sv.Detections(
        xyxy=np.array([[0, 10, 100, 210], [300, 100, 500, 400]], dtype=float),
        confidence=np.array([0.92, 0.31], dtype=float),
        class_id=np.array([0, 0], dtype=int),
        tracker_id=np.array([7, 8], dtype=int),
        data={"class_name": np.array(["athlete", "athlete"])},
    )
    require_detection_conversion(detections)


def _clear_env() -> None:
    for key in [
        "SPORTREEL_PERCEPTION_COMMAND",
        "SPORTREEL_PERCEPTION_SIDECAR_DIR",
        "SPORTREEL_REQUIRE_PERCEPTION",
        "SPORTREEL_PERCEPTION_TIMEOUT_SEC",
        "SPORTREEL_PERCEPTION_BACKEND",
        "SPORTREEL_PERCEPTION_DETECTIONS_JSON",
        "SPORTREEL_PERCEPTION_MIN_CONFIDENCE",
    ]:
        os.environ.pop(key, None)


def require_sidecar_generator_contract() -> None:
    from pipeline.perception.producer import generate_sidecar
    from pipeline.perception.runtime import validate_sidecar

    producer_dir = ROOT / ".tmp_perception_generator"
    producer_dir.mkdir(exist_ok=True)
    video_path = producer_dir / "source clip.mp4"
    detector_json = producer_dir / "detector_output.json"
    output = producer_dir / "source clip.perception.json"
    cli_output = producer_dir / "cli_output.perception.json"
    detector_json.write_text(
        json.dumps({
            "frames": [
                {
                    "frame_index": 10,
                    "time_sec": 0.33,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "detections": [
                        {
                            "bbox_xyxy": [100, 120, 300, 520],
                            "confidence": 0.93,
                            "class_id": 0,
                            "class_name": "athlete",
                            "track_id": 12,
                        },
                        {
                            "bbox_xyxy": [10, 20, 30, 40],
                            "confidence": 0.11,
                            "class_name": "athlete",
                            "track_id": 13,
                        },
                    ],
                }
            ]
        }),
        encoding="utf-8",
    )
    try:
        _clear_env()
        os.environ["SPORTREEL_PERCEPTION_MIN_CONFIDENCE"] = "0.5"
        generated = generate_sidecar(
            str(video_path),
            str(output),
            backend="external_json",
            detections_json=str(detector_json),
        )
        if generated.get("status") != "ok" or len(generated.get("detections", [])) != 1:
            raise SystemExit("external_json producer should write exactly one filtered detection")
        detection = generated["detections"][0]
        if detection.get("track_id") != 12 or detection.get("class_name") != "athlete":
            raise SystemExit("external_json producer did not preserve track/class evidence")
        if validate_sidecar(str(video_path), output)["detection_count"] != 1:
            raise SystemExit("generated producer sidecar should validate through runtime")

        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/generate_perception_sidecar.py"),
                str(video_path),
                str(cli_output),
                "--backend",
                "external_json",
                "--detections-json",
                str(detector_json),
            ],
            check=True,
            cwd=ROOT,
        )
        if validate_sidecar(str(video_path), cli_output)["detection_count"] != 1:
            raise SystemExit("CLI producer output should validate through runtime")

        skipped = generate_sidecar(str(video_path), str(producer_dir / "skipped.perception.json"))
        if skipped.get("status") != "skipped" or skipped.get("reason") != "perception_backend_not_configured":
            raise SystemExit("unconfigured producer must emit explicit backend_not_configured status")
    finally:
        _clear_env()
        for path in sorted(producer_dir.rglob("*"), reverse=True):
            try:
                path.unlink()
            except IsADirectoryError:
                path.rmdir()
            except FileNotFoundError:
                pass
        try:
            producer_dir.rmdir()
        except OSError:
            pass


def require_sidecar_producer_contract() -> None:
    from pipeline.perception.runtime import ensure_sidecar_for_video, load_sidecar_detections, sidecar_output_path, validate_sidecar

    producer_dir = ROOT / ".tmp_perception_producer"
    producer_dir.mkdir(exist_ok=True)
    video_path = producer_dir / "producer_sample.mp4"
    sidecar_dir = producer_dir / "sidecars"
    writer = producer_dir / "write_sidecar.py"
    skip_writer = producer_dir / "write_skipped_sidecar.py"
    writer.write_text(
        "import json, os, sys\n"
        "out = os.environ['SPORTREEL_PERCEPTION_OUTPUT']\n"
        "if len(sys.argv) > 1 and sys.argv[1:3] != [os.environ['SPORTREEL_VIDEO_PATH'], out]:\n"
        "    raise SystemExit(f'placeholder argv mismatch: {sys.argv[1:3]!r}')\n"
        "json.dump({'source_video': os.environ['SPORTREEL_VIDEO_PATH'], 'detections': "
        "[{'time_sec': 1.0, 'frame_index': 30, 'bbox_xyxy': [20, 30, 120, 230], "
        "'frame_width': 640, 'frame_height': 480, 'confidence': 0.97, 'class_name': 'athlete', 'track_id': 99}]}, "
        "open(out, 'w', encoding='utf-8'))\n",
        encoding="utf-8",
    )
    skip_writer.write_text(
        "import json, os\n"
        "json.dump({'source_video': os.environ['SPORTREEL_VIDEO_PATH'], 'status': 'skipped', "
        "'reason': 'perception_backend_not_configured', 'detections': []}, "
        "open(os.environ['SPORTREEL_PERCEPTION_OUTPUT'], 'w', encoding='utf-8'))\n",
        encoding="utf-8",
    )
    try:
        _clear_env()
        os.environ["SPORTREEL_PERCEPTION_SIDECAR_DIR"] = str(sidecar_dir)
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{sys.executable} {writer}"
        summary = ensure_sidecar_for_video(str(video_path))
        if summary.get("producer_status") != "created" or summary.get("detection_count") != 1:
            raise SystemExit("producer command should create one valid sidecar detection")
        output = sidecar_output_path(str(video_path))
        loaded = load_sidecar_detections(str(video_path))
        if output.name != "producer_sample.perception.json" or loaded[0].tracker_id != 99:
            raise SystemExit("producer output path or tracker ID is wrong")
        if validate_sidecar(str(video_path))["detection_count"] != 1:
            raise SystemExit("producer sidecar validation did not count detections")

        _clear_env()
        skipped_video = producer_dir / "skipped_sample.mp4"
        skipped_summary = ensure_sidecar_for_video(str(skipped_video))
        if skipped_summary.get("producer_status") != "skipped":
            raise SystemExit("missing producer command should create an explicit skipped status sidecar")
        skipped_payload = json.loads((producer_dir / "skipped_sample.perception.json").read_text(encoding="utf-8"))
        if skipped_payload.get("status") != "skipped" or skipped_payload.get("detections") != []:
            raise SystemExit("skipped sidecar should be explicit and detection-free")

        _clear_env()
        stale_video = producer_dir / "stale skipped sample.mp4"
        stale_summary = ensure_sidecar_for_video(str(stale_video))
        if stale_summary.get("producer_status") != "skipped":
            raise SystemExit("stale setup should first create a skipped sidecar")
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{sys.executable} {writer} {{video_path}} {{sidecar_path}}"
        refreshed_summary = ensure_sidecar_for_video(str(stale_video))
        if refreshed_summary.get("producer_status") != "created" or refreshed_summary.get("detection_count") != 1:
            raise SystemExit("skipped/failed sidecars must not be reused when a producer command is configured")
        if validate_sidecar(str(stale_video))["status"] != "ok":
            raise SystemExit("refreshed producer sidecar should replace the stale skipped marker")

        _clear_env()
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{sys.executable} {skip_writer}"
        skip_command_summary = ensure_sidecar_for_video(str(producer_dir / "command_skipped_sample.mp4"))
        if skip_command_summary.get("producer_status") != "skipped":
            raise SystemExit("producer-written skipped sidecar should not be reported as created")

        _clear_env()
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{sys.executable} {skip_writer}"
        os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
        try:
            ensure_sidecar_for_video(str(producer_dir / "required_command_skipped_sample.mp4"))
        except RuntimeError as exc:
            if "reusable sidecar" not in str(exc):
                raise SystemExit("required perception should fail on producer-written skipped sidecar")
        else:
            raise SystemExit("required mode must reject producer-written skipped sidecars")

        _clear_env()
        required_stale_video = producer_dir / "required_skipped_sample.mp4"
        ensure_sidecar_for_video(str(required_stale_video))
        os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
        try:
            ensure_sidecar_for_video(str(required_stale_video))
        except RuntimeError as exc:
            if "SPORTREEL_PERCEPTION_COMMAND" not in str(exc):
                raise SystemExit("required perception should not accept an existing skipped sidecar")
        else:
            raise SystemExit("required perception mode must reject an existing skipped sidecar")

        _clear_env()
        os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
        try:
            ensure_sidecar_for_video(str(producer_dir / "required_sample.mp4"))
        except RuntimeError as exc:
            if "SPORTREEL_PERCEPTION_COMMAND" not in str(exc):
                raise SystemExit("required perception error should name the missing producer command")
        else:
            raise SystemExit("required perception mode must fail when no producer command is configured")
    finally:
        _clear_env()
        for path in sorted(producer_dir.rglob("*"), reverse=True):
            try:
                path.unlink()
            except IsADirectoryError:
                path.rmdir()
            except FileNotFoundError:
                pass
        try:
            producer_dir.rmdir()
        except OSError:
            pass


def require_sidecar_runtime_contract() -> None:
    from pipeline.perception.runtime import enrich_event, enrich_session_with_sidecar, load_sidecar_detections
    from pipeline.perception.schema import PerceptionDetection

    detections = [
        PerceptionDetection(
            source_video="clip.mp4",
            frame_index=30,
            time_sec=1.0,
            xyxy=(100, 100, 300, 500),
            frame_width=1000,
            frame_height=800,
            confidence=0.91,
            class_id=0,
            class_name="athlete",
            tracker_id=7,
        ),
        PerceptionDetection(
            source_video="clip.mp4",
            frame_index=32,
            time_sec=1.2,
            xyxy=(600, 100, 800, 500),
            frame_width=1000,
            frame_height=800,
            confidence=0.84,
            class_id=0,
            class_name="athlete",
            tracker_id=8,
        ),
    ]
    event = {"event_id": "ride", "type": "surf_ride", "score": 8, "start": 0.8, "end": 1.4, "crop_x": 0.5}
    enriched = enrich_event(event, detections)
    if enriched.get("perception_evidence_status") != "tracker_sidecar":
        raise SystemExit("event was not marked as tracker-sidecar enriched")
    if enriched.get("track_id") != 7:
        raise SystemExit("highest-confidence in-window track must become primary track_id")
    if enriched.get("source_window_track_ids") != ["7", "8"]:
        raise SystemExit("visible source-window track IDs must be preserved for multi-person QA")
    if enriched.get("crop_source") != "bbox" or not enriched.get("bbox_xyxy"):
        raise SystemExit("tracker bbox must feed crop metadata")

    missing = enrich_event({"start": 10, "end": 11}, detections)
    if missing.get("perception_evidence_status") != "no_tracker_detection":
        raise SystemExit("sidecar-present events with no detection must expose missing evidence status")

    sidecar_dir = ROOT / ".tmp_perception_contract"
    sidecar_dir.mkdir(exist_ok=True)
    video_path = sidecar_dir / "sample.mp4"
    sidecar_path = sidecar_dir / "sample.perception.json"
    sidecar_path.write_text(json.dumps({"detections": [{"time_sec": 2.0, "frame_index": 60, "bbox_xyxy": [10, 20, 110, 220], "frame_width": 640, "frame_height": 480, "confidence": 0.95, "track_id": 42}]}), encoding="utf-8")
    try:
        loaded = load_sidecar_detections(str(video_path))
        if len(loaded) != 1 or loaded[0].tracker_id != 42:
            raise SystemExit("sidecar loader did not parse detector/tracker evidence")
        session = {"persons": [{"description": "surfer", "events": [{"event_id": "e1", "start": 1.8, "end": 2.2, "score": 8}]}]}
        enriched_session = enrich_session_with_sidecar(session, str(video_path))
        enriched_event = enriched_session["persons"][0]["events"][0]
        if enriched_event.get("track_id") != 42 or enriched_session.get("perception_evidence_source") != "tracker_sidecar":
            raise SystemExit("session enrichment did not attach sidecar tracker evidence")
    finally:
        try:
            sidecar_path.unlink()
            sidecar_dir.rmdir()
        except OSError:
            pass


def require_runtime_contract() -> None:
    from pipeline.perception.crop_math import bbox_center_norm, bbox_to_crop, bbox_visible_ratio
    from pipeline.perception.schema import PerceptionDetection
    from pipeline.perception.supervision_adapter import supervision_available

    require_detection_conversion(FakeDetections())

    if round(bbox_visible_ratio((-10, -10, 10, 10), 100, 100), 2) != 0.25:
        raise SystemExit("visible_ratio should account for bbox outside the frame")
    if bbox_center_norm((40, 20, 60, 40), 100, 100) != (0.5, 0.3):
        raise SystemExit("bbox_center_norm should return normalized bbox center")
    if bbox_to_crop((40, 20, 60, 40), 100, 100)["visible_ratio"] != 1.0:
        raise SystemExit("bbox_to_crop should include visible_ratio")

    PerceptionDetection(
        source_video="clip.mp4",
        frame_index=0,
        time_sec=0.0,
        xyxy=(1, 2, 3, 4),
        frame_width=10,
        frame_height=10,
    )
    if not isinstance(supervision_available(), bool):
        raise SystemExit("supervision_available must return bool")
    require_sidecar_generator_contract()
    require_sidecar_producer_contract()
    require_sidecar_runtime_contract()
    require_real_supervision_contract()


def main() -> int:
    requirements = _read("requirements.txt")
    workflow = _read(".github/workflows/operator-smoke-check.yml")
    schema = _read("pipeline/perception/schema.py")
    adapter = _read("pipeline/perception/supervision_adapter.py")
    producer = _read("pipeline/perception/producer.py")
    crop_math = _read("pipeline/perception/crop_math.py")
    runtime = _read("pipeline/perception/runtime.py")
    generator_cli = _read("scripts/generate_perception_sidecar.py")
    run_tracked = _read("scripts/run_tracked.py")
    bootstrap = _read("pipeline/bootstrap.py")

    for label, text in {
        "perception schema": schema,
        "supervision adapter": adapter,
        "perception producer": producer,
        "crop math": crop_math,
        "perception runtime": runtime,
        "perception generator cli": generator_cli,
        "perception contract": _read("scripts/test_perception_contract.py"),
    }.items():
        ast.parse(text)

    require_tokens("requirements", requirements, ["supervision>=0.29.0,<0.30.0"])
    require_tokens("perception schema", schema, ["class PerceptionDetection", "xyxy", "confidence", "class_id", "class_name", "tracker_id", "visible_ratio", "to_event_metadata", "bbox_xyxy"])
    require_tokens("supervision adapter", adapter, ["def supervision_available()", 'find_spec("supervision")', "def detections_from_supervision", "xyxy", "confidence", "class_id", "tracker_id", "min_confidence", "PerceptionDetection("])
    require_tokens("perception producer", producer, ["SPORTREEL_PERCEPTION_BACKEND", "SPORTREEL_PERCEPTION_DETECTIONS_JSON", "SPORTREEL_PERCEPTION_MIN_CONFIDENCE", "def generate_sidecar", "def sidecar_from_detection_json", "perception_backend_not_configured", "each production detection must include track_id", "status", "ok"])
    require_tokens("perception generator cli", generator_cli, ["generate_sidecar", "--backend", "--detections-json", "perception sidecar status="])
    require_tokens("perception runtime", runtime, ["SPORTREEL_PERCEPTION_SIDECAR_DIR", "SPORTREEL_PERCEPTION_COMMAND", "SPORTREEL_REQUIRE_PERCEPTION", "sidecar_output_path", "ensure_sidecar_for_video", "validate_sidecar", "subprocess.run", "load_sidecar_detections", "enrich_event", "enrich_session_with_sidecar", "source_window_track_ids", "visible_track_ids", "perception_evidence_status", "tracker_sidecar", "_is_reusable_sidecar", "_producer_status_from_sidecar", "Perception producer did not create a reusable sidecar", "shlex.split(command)", "ensure_sidecar_for_video(video_path)", "analyzer.analyze_session = analyze_with_perception_sidecar"])
    require_tokens("tracked canonical bootstrap", run_tracked, ["install_pre_orchestrator_patches()", "install_post_orchestrator_patches()"] )
    require_tokens("canonical perception runtime install", bootstrap, ["pipeline.perception.runtime", "pipeline.runtime_quality"])
    require_no_tokens("perception foundation", "\n".join([schema, adapter, crop_math]), ["from supervision.tracker", "update_with_detections"])
    require_tokens("operator smoke workflow perception coverage", workflow, ["pipeline/perception/**", "scripts/test_perception_contract.py", "Install perception dependency", "Validate Perception contract"])

    require_runtime_contract()
    print("Perception foundation contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
