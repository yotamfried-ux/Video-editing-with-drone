#!/usr/bin/env python3
"""Validate and record the resolved production perception configuration."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "yolo11s.pt"
DEFAULT_TRACKER = "config/trackers/sportreel_botsort_reid.yaml"
DEFAULT_OUTPUT = "/tmp/dtor/pipeline-debug/perception_preflight.json"


def _scalar(value: str) -> Any:
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null", "~"}:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text.strip("'\"")


def _simple_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = _scalar(value)
    return data


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value <= 0:
        raise SystemExit(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    value = float(raw) if raw else default
    if value <= 0:
        raise SystemExit(f"{name} must be positive")
    return value


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _validate_custom_command(command: str, model: str, tracker: str) -> None:
    if not command:
        return
    required_tokens = ["{video_path}", "{sidecar_path}", model, tracker]
    missing = [token for token in required_tokens if token not in command]
    if missing:
        raise SystemExit(
            "Custom SPORTREEL_PERCEPTION_COMMAND cannot bypass the mandatory "
            f"model/tracker contract; missing tokens: {missing}"
        )


def main() -> int:
    required = os.getenv("SPORTREEL_REQUIRE_PERCEPTION", "1").strip() == "1"
    model = os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "").strip() or DEFAULT_MODEL
    tracker_value = os.getenv("SPORTREEL_ULTRALYTICS_TRACKER", "").strip() or DEFAULT_TRACKER
    tracker_path = Path(tracker_value)
    if not tracker_path.is_absolute():
        tracker_path = ROOT / tracker_path
    if not tracker_path.is_file():
        raise SystemExit(f"Perception tracker config does not exist: {tracker_path}")

    tracker = _simple_yaml(tracker_path)
    if tracker.get("tracker_type") != "botsort":
        raise SystemExit("Production tracker must use BoT-SORT for moving-camera compensation")
    if required and tracker.get("with_reid") is not True:
        raise SystemExit("Mandatory production perception requires BoT-SORT ReID to be enabled")

    custom_command = os.getenv("SPORTREEL_PERCEPTION_COMMAND", "").strip()
    if required:
        _validate_custom_command(custom_command, model, tracker_value)

    payload = {
        "schema_version": "sportreel.perception_preflight.v1",
        "required": required,
        "model": model,
        "tracker": tracker_value,
        "tracker_path": str(tracker_path),
        "tracker_type": tracker.get("tracker_type"),
        "with_reid": tracker.get("with_reid"),
        "reid_model": tracker.get("model"),
        "gmc_method": tracker.get("gmc_method"),
        "command_source": "custom_validated" if custom_command else "first_party_default",
        "command_sha256": hashlib.sha256(custom_command.encode("utf-8")).hexdigest() if custom_command else None,
        "vid_stride": _positive_int("SPORTREEL_ULTRALYTICS_VID_STRIDE", 10),
        "imgsz": _positive_int("SPORTREEL_ULTRALYTICS_IMGSZ", 640),
        "device": os.getenv("SPORTREEL_ULTRALYTICS_DEVICE", "").strip() or "auto",
        "source_fps": _positive_float("SPORTREEL_ULTRALYTICS_FPS", 30.0),
        "ultralytics_version": _package_version("ultralytics"),
        "torch_version": _package_version("torch"),
    }

    output = Path(os.getenv("PERCEPTION_PREFLIGHT_OUTPUT", DEFAULT_OUTPUT))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = (
        "Perception preflight: "
        f"model={payload['model']} tracker={payload['tracker']} "
        f"reid={payload['with_reid']} stride={payload['vid_stride']} "
        f"imgsz={payload['imgsz']} device={payload['device']} "
        f"command={payload['command_source']}"
    )
    print(summary)

    github_summary = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as handle:
            handle.write("## Mandatory perception preflight\n\n")
            handle.write(f"- Model: `{payload['model']}`\n")
            handle.write(f"- Tracker: `{payload['tracker']}`\n")
            handle.write(f"- ReID enabled: `{payload['with_reid']}`\n")
            handle.write(f"- Command source: `{payload['command_source']}`\n")
            handle.write(f"- Frame stride: `{payload['vid_stride']}`\n")
            handle.write(f"- Inference image size: `{payload['imgsz']}`\n")
            handle.write(f"- Device: `{payload['device']}`\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
