#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp_run_quality_report_contract"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    if TMP.exists():
        shutil.rmtree(TMP)
    debug = TMP / "pipeline-debug"
    sidecars = debug / "sidecars"
    source = TMP / "source.mp4"
    draft = TMP / "DRAFT_surfer.mp4"
    source.write_bytes(b"source")
    draft.write_bytes(b"draft")
    sidecar = TMP / "source.perception.json"
    write_json(
        sidecar,
        {
            "source_video": str(source),
            "status": "ok",
            "backend": "ultralytics",
            "detections": [
                {
                    "frame_index": 10,
                    "time_sec": 0.5,
                    "bbox_xyxy": [10, 10, 50, 80],
                    "frame_width": 100,
                    "frame_height": 100,
                    "confidence": 0.9,
                    "class_id": 0,
                    "class_name": "person",
                    "track_id": 7,
                }
            ],
        },
    )
    write_json(
        debug / "summary.json",
        {
            "exit_code": 0,
            "tmp_dir": str(TMP),
            "file_count": 3,
            "sidecar_count": 1,
            "sidecars": [sidecar.name],
            "files": [
                {"path": source.name, "size_bytes": 6},
                {"path": draft.name, "size_bytes": 5},
                {"path": sidecar.name, "size_bytes": sidecar.stat().st_size},
            ],
        },
    )
    (debug / "run_tracked.log").write_text("pipeline ok", encoding="utf-8")
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        report = json.loads((debug / "run_quality_report.json").read_text(encoding="utf-8"))
        require(report["schema_version"] == "sportreel.run_quality_report.v1", "report schema version missing")
        require(report["metrics"]["draft_count"] == 1, "draft_count metric missing")
        require(report["metrics"]["sidecar_count"] == 1, "sidecar_count metric missing")
        require(report["metrics"]["track_id_missing_rate"] == 0.0, "track id should be present")
        require(report["metrics"]["bbox_out_of_bounds_rate"] == 0.0, "bbox should be valid")
        require(report["status"] in {"fail", "inconclusive"}, "missing decision trace must not pass")
        codes = {item["code"] for item in report["bug_classifications"]}
        require("BUG_SELECTION_BYPASSED_EVIDENCE" in codes, "missing decision trace bug classification")
        require("BUG_RECALL_UNKNOWN" in codes, "missing dropped reasons bug classification")

        (TMP / "candidate_decision_ledger.json").write_text("{}", encoding="utf-8")
        (TMP / "dropped_reasons.json").write_text('{"dropped_reason":"fixture"}', encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_run_quality_report.py"), str(debug), str(TMP), "0"],
            cwd=ROOT,
            check=True,
        )
        report = json.loads((debug / "run_quality_report.json").read_text(encoding="utf-8"))
        require(report["status"] == "pass", "complete evidence fixture should pass")
        print("Run quality report contract checks passed")
        return 0
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
