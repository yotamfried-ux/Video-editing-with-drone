#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing contract tokens: {missing}")


def main() -> int:
    tracker = read("config/trackers/sportreel_botsort_reid.yaml")
    policy = read("pipeline/required_perception_policy.py")
    producer = read("scripts/generate_perception_sidecar.py")
    preflight_source = read("scripts/print_perception_preflight.py")
    workflow = read(".github/workflows/pipeline-run.yml")
    diagnostics = read("scripts/run_pipeline_with_diagnostics.sh")
    r2 = read("web-api/src/lib/r2-storage.ts")
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    audit = read("docs/audit/remaining-gaps-official-reference-audit-20260721.md")

    require("SportReel tracker", tracker, [
        "tracker_type: botsort",
        "gmc_method: sparseOptFlow",
        "with_reid: true",
        "model: auto",
    ])
    require("mandatory perception policy", policy, [
        'config/trackers/sportreel_botsort_reid.yaml',
        'SPORTREEL_REQUIRE_PERCEPTION',
        'featured-athlete track binding',
    ])
    require("preflight override protection", preflight_source, [
        "_validate_custom_command",
        '"{video_path}"',
        '"{sidecar_path}"',
        '"custom_validated"',
        '"command_sha256"',
    ])
    require("sidecar performance evidence", producer, [
        'time.perf_counter()',
        '"wall_time_seconds"',
        '"processed_frame_count"',
        '"effective_sampling_fps"',
        '"with_reid"',
    ])
    require("pipeline preflight", workflow, [
        "Preflight mandatory perception configuration",
        "scripts/print_perception_preflight.py",
        "SPORTREEL_ULTRALYTICS_VID_STRIDE",
        "config/trackers/sportreel_botsort_reid.yaml",
    ])
    require("diagnostic benchmark", diagnostics, [
        "build_perception_benchmark_report.py",
        "perception_benchmark_report.json",
    ])
    require("R2 signed content type", r2, [
        "requiredHeaders: Record<string, string>",
        "'content-type': mimeType",
        "X-Amz-SignedHeaders",
    ])
    require("upload MIME binding", upload_route, [
        "file.clientUploadId,",
        "file.mimeType,",
    ])
    require("official gap audit", audit, [
        "Ultralytics",
        "Cloudflare R2",
        "Netflix VMAF",
        "Supabase",
        "Vercel",
        "EAS Update",
        "BLOCKS MERGE",
    ])

    for path in [
        "scripts/print_perception_preflight.py",
        "scripts/build_perception_benchmark_report.py",
        "scripts/generate_perception_sidecar.py",
        "scripts/test_remaining_gaps_official_contract.py",
    ]:
        ast.parse(read(path))

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        preflight = temp / "preflight.json"
        env = {
            **os.environ,
            "SPORTREEL_REQUIRE_PERCEPTION": "1",
            "SPORTREEL_PERCEPTION_COMMAND": "",
            "SPORTREEL_ULTRALYTICS_TRACKER": "config/trackers/sportreel_botsort_reid.yaml",
            "SPORTREEL_ULTRALYTICS_MODEL": "fixture-model.pt",
            "SPORTREEL_ULTRALYTICS_VID_STRIDE": "10",
            "SPORTREEL_ULTRALYTICS_IMGSZ": "640",
            "PERCEPTION_PREFLIGHT_OUTPUT": str(preflight),
        }
        subprocess.run(
            ["python", "scripts/print_perception_preflight.py"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        payload = json.loads(preflight.read_text(encoding="utf-8"))
        assert payload["required"] is True
        assert payload["with_reid"] is True
        assert payload["tracker_type"] == "botsort"
        assert payload["command_source"] == "first_party_default"

        bypass = subprocess.run(
            ["python", "scripts/print_perception_preflight.py"],
            cwd=ROOT,
            env={**env, "SPORTREEL_PERCEPTION_COMMAND": "python unsafe.py {video_path} {sidecar_path}"},
            capture_output=True,
            text=True,
        )
        assert bypass.returncode != 0
        assert "cannot bypass" in (bypass.stdout + bypass.stderr)

        valid_custom = subprocess.run(
            ["python", "scripts/print_perception_preflight.py"],
            cwd=ROOT,
            env={
                **env,
                "SPORTREEL_PERCEPTION_COMMAND": (
                    "python scripts/generate_perception_sidecar.py {video_path} {sidecar_path} "
                    "--backend ultralytics --ultralytics-model fixture-model.pt "
                    "--ultralytics-tracker config/trackers/sportreel_botsort_reid.yaml"
                ),
            },
            capture_output=True,
            text=True,
        )
        assert valid_custom.returncode == 0, valid_custom.stdout + valid_custom.stderr
        custom_payload = json.loads(preflight.read_text(encoding="utf-8"))
        assert custom_payload["command_source"] == "custom_validated"
        assert custom_payload["command_sha256"]

        sidecars = temp / "sidecars"
        sidecars.mkdir()
        (sidecars / "fixture.perception.json").write_text(json.dumps({
            "source_video": "fixture.mp4",
            "status": "ok",
            "backend": "ultralytics",
            "model": "fixture-model.pt",
            "tracker": "config/trackers/sportreel_botsort_reid.yaml",
            "with_reid": True,
            "vid_stride": 10,
            "imgsz": 640,
            "detections": [
                {"raw_track_id": 1, "track_id": 1, "time_sec": 0.0},
                {"raw_track_id": 1, "track_id": 1, "time_sec": 2.5},
            ],
            "performance": {
                "wall_time_seconds": 4.0,
                "processed_frame_count": 10,
                "inference_frames_per_second": 2.5,
                "effective_sampling_fps": 3.0,
            },
            "track_stitching": {
                "raw_track_count": 1,
                "canonical_track_count": 1,
                "stitched_track_count": 0,
            },
        }), encoding="utf-8")
        report = temp / "benchmark.json"
        subprocess.run(
            ["python", "scripts/build_perception_benchmark_report.py", str(sidecars), str(report)],
            cwd=ROOT,
            check=True,
        )
        benchmark = json.loads(report.read_text(encoding="utf-8"))
        assert benchmark["video_count"] == 1
        assert benchmark["videos"][0]["raw_track_metrics"]["median_duration_seconds"] == 2.5

    print("Remaining-gap official reference contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
