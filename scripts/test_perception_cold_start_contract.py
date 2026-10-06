#!/usr/bin/env python3
"""Cold-start producer -> sidecar -> consumer contract for Perception.

Regression for the production failure
``Perception producer did not create a reusable sidecar: status=ok``: a sidecar the
real producer writes with status "ok" must be accepted immediately, without any
pre-existing sidecar, and be consumable by the analyzer enrichment.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.perception.runtime as rt  # noqa: E402

DETECTIONS = {
    "frame_width": 1920,
    "frame_height": 1080,
    "detections": [
        {"frame_index": 90, "time_sec": 3.0, "bbox_xyxy": [100, 120, 220, 420], "frame_width": 1920,
         "frame_height": 1080, "confidence": 0.91, "class_id": 0, "class_name": "athlete", "track_id": 7},
    ],
}


def _env(tmp: Path) -> None:
    for key in ("SPORTREEL_PERCEPTION_SIDECAR_DIR", "SPORTREEL_PERCEPTION_COMMAND", "SPORTREEL_REQUIRE_PERCEPTION"):
        os.environ.pop(key, None)
    det = tmp / "det.json"
    det.write_text(json.dumps(DETECTIONS))
    os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
    os.environ["SPORTREEL_PERCEPTION_COMMAND"] = " ".join(
        shlex.quote(p) for p in [
            sys.executable, str(ROOT / "scripts" / "generate_perception_sidecar.py"),
            "--backend", "external_json", "--detections-json", str(det),
        ]
    )


def test_cold_start_real_producer_sidecar_is_reusable_and_consumed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _env(tmp)
        video = str(tmp / "clip.MP4")
        assert rt._sidecar_path(video) is None, "cold start: no sidecar may pre-exist"
        first = rt.ensure_sidecar_for_video(video)  # required mode: must not raise
        assert first["producer_status"] == "created", first
        assert first["status"] == "ok" and first["detection_count"] == 1
        second = rt.ensure_sidecar_for_video(video)  # warm path reuses it
        assert second["producer_status"] == "existing", second

        session = {"persons": [{"events": [{"start": 2.5, "end": 3.5, "crop_x": 0.08, "crop_y": 0.25}]}]}
        enriched = rt.enrich_session_with_sidecar(session, video)
        event = enriched["persons"][0]["events"][0]
        assert event["perception_evidence_status"] == "tracker_sidecar", event
        assert event["target_track_id"] == "7"
        assert enriched["perception_evidence_source"] == "tracker_sidecar"


def test_cold_start_with_sidecar_dir_as_in_production_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _env(tmp)
        sidecars = tmp / "sidecars"
        os.environ["SPORTREEL_PERCEPTION_SIDECAR_DIR"] = str(sidecars)
        video = str(tmp / "dl" / "2026-10-03T12-19-53_DJI_0070_D.MP4")
        result = rt.ensure_sidecar_for_video(video)
        assert result["producer_status"] == "created" and Path(result["path"]).parent == sidecars
        assert len(rt.load_sidecar_detections(video)) == 1


def test_status_ok_is_reusable_regardless_of_case_or_spacing() -> None:
    for status in ("ok", "OK", " Ok ", None, ""):
        summary = {"status": status}
        assert rt._is_reusable_sidecar(summary), f"status {status!r} must be reusable"
        assert rt._producer_status_from_sidecar(summary) == "created"


def test_non_ok_status_still_fails_closed_when_required() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _env(tmp)
        producer = tmp / "skipping_producer.py"
        producer.write_text(
            "import json,sys\n"
            "json.dump({'status':'skipped','reason':'x','detections':[]}, open(sys.argv[2],'w'))\n"
        )
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{shlex.quote(sys.executable)} {shlex.quote(str(producer))}"
        try:
            rt.ensure_sidecar_for_video(str(tmp / "clip.MP4"))
        except RuntimeError as exc:
            assert "did not create a reusable sidecar" in str(exc) and "status=skipped" in str(exc)
        else:
            raise AssertionError("a skipped sidecar must not satisfy required perception")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    try:
        for fn in tests:
            fn()
            print(f"ok  {fn.__name__}")
    finally:
        for key in ("SPORTREEL_PERCEPTION_SIDECAR_DIR", "SPORTREEL_PERCEPTION_COMMAND", "SPORTREEL_REQUIRE_PERCEPTION"):
            os.environ.pop(key, None)
    print(f"{len(tests)} perception cold-start checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
