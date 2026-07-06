"""Runtime perception evidence enrichment for analyzer events.

This module connects production detector/tracker output into the existing
pipeline contract by consuming a JSON sidecar next to the source video or inside
SPORTREEL_PERCEPTION_SIDECAR_DIR.

It can also run a configured pre-analysis producer command before Gemini
analysis. The command is intentionally external: this repository owns the
contract, validation, ordering and fail-safe behavior, while the actual model can
be swapped without changing downstream crop/identity/QA code.

Expected sidecar shape:
{
  "detections": [
    {
      "frame_index": 90,
      "time_sec": 3.0,
      "bbox_xyxy": [100, 120, 220, 420],
      "frame_width": 1920,
      "frame_height": 1080,
      "confidence": 0.91,
      "class_id": 0,
      "class_name": "athlete",
      "track_id": 7
    }
  ]
}
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .schema import PerceptionDetection

logger = logging.getLogger(__name__)

_INSTALLED_FLAG = "_sportreel_perception_runtime_installed"
_SIDECAR_ENV = "SPORTREEL_PERCEPTION_SIDECAR_DIR"
_COMMAND_ENV = "SPORTREEL_PERCEPTION_COMMAND"
_REQUIRED_ENV = "SPORTREEL_REQUIRE_PERCEPTION"
_TIMEOUT_ENV = "SPORTREEL_PERCEPTION_TIMEOUT_SEC"
_MAX_NEAREST_SEC = 1.0
_TRUE_VALUES = {"1", "true", "yes", "on", "required"}
_REUSABLE_SIDECAR_STATUSES = {"ok"}


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUE_VALUES


def perception_required() -> bool:
    """Return whether missing/invalid perception evidence should fail the run."""
    return _truthy_env(_REQUIRED_ENV)


def candidate_sidecar_paths(video_path: str) -> list[Path]:
    """Return sidecar candidates in deterministic priority order."""
    video = Path(video_path)
    paths = [video.with_suffix(video.suffix + ".perception.json"), video.with_suffix(".perception.json")]
    sidecar_dir = os.getenv(_SIDECAR_ENV, "").strip()
    if sidecar_dir:
        root = Path(sidecar_dir)
        paths.extend([
            root / f"{video.name}.perception.json",
            root / f"{video.stem}.perception.json",
        ])
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def sidecar_output_path(video_path: str) -> Path:
    """Return where the producer should write a sidecar for this local video."""
    video = Path(video_path)
    sidecar_dir = os.getenv(_SIDECAR_ENV, "").strip()
    if sidecar_dir:
        return Path(sidecar_dir) / f"{video.stem}.perception.json"
    return video.with_suffix(".perception.json")


def _sidecar_path(video_path: str) -> Path | None:
    return next((path for path in candidate_sidecar_paths(video_path) if path.exists()), None)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timeout_sec() -> int:
    try:
        return max(1, int(os.getenv(_TIMEOUT_ENV, "600")))
    except ValueError:
        return 600


def _render_command(command: str, video_path: str, sidecar_path: Path) -> list[str]:
    """Render a configured command without using a shell.

    A command may include `{video_path}` and `{sidecar_path}` placeholders. If no
    placeholders are present, both paths are appended as positional arguments.
    The environment also receives SPORTREEL_VIDEO_PATH and
    SPORTREEL_PERCEPTION_OUTPUT.
    """
    args = shlex.split(command)
    if "{video_path}" in command or "{sidecar_path}" in command:
        return [
            arg.replace("{video_path}", video_path).replace("{sidecar_path}", str(sidecar_path))
            for arg in args
        ]
    return [*args, video_path, str(sidecar_path)]


def _write_status_sidecar(video_path: str, sidecar_path: Path, status: str, reason: str) -> None:
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_video": video_path,
        "status": status,
        "reason": reason,
        "detections": [],
    }
    tmp = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(sidecar_path)


def _sidecar_status(summary: dict[str, Any]) -> str:
    return str(summary.get("status") or "ok").strip().lower()


def _is_reusable_sidecar(summary: dict[str, Any]) -> bool:
    """Return whether an existing sidecar can safely short-circuit the producer."""
    return _sidecar_status(summary) in _REUSABLE_SIDECAR_STATUSES


def _non_reusable_error(summary: dict[str, Any]) -> str:
    return f"Perception producer did not create a reusable sidecar: status={summary.get('status')} reason={summary.get('reason')}"


def _producer_status_from_sidecar(summary: dict[str, Any]) -> str:
    status = _sidecar_status(summary)
    return "created" if status in _REUSABLE_SIDECAR_STATUSES else status


def load_sidecar_detections(video_path: str) -> list[PerceptionDetection]:
    """Load normalized detections from the detector/tracker sidecar if present."""
    path = _sidecar_path(video_path)
    if path is None:
        return []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    source_video = str(payload.get("source_video") or video_path)
    default_w = int(payload.get("frame_width") or 0)
    default_h = int(payload.get("frame_height") or 0)
    detections = []
    for item in payload.get("detections", []) or []:
        frame_width = int(item.get("frame_width") or default_w)
        frame_height = int(item.get("frame_height") or default_h)
        detections.append(
            PerceptionDetection(
                source_video=source_video,
                frame_index=int(item.get("frame_index") or 0),
                time_sec=_num(item.get("time_sec")),
                xyxy=tuple(item.get("bbox_xyxy") or item.get("xyxy") or ()),
                frame_width=frame_width,
                frame_height=frame_height,
                confidence=(None if item.get("confidence") is None else float(item.get("confidence"))),
                class_id=(None if item.get("class_id") is None else int(item.get("class_id"))),
                class_name=(None if item.get("class_name") is None else str(item.get("class_name"))),
                tracker_id=(None if item.get("track_id") is None else int(item.get("track_id"))),
            )
        )
    return detections


def validate_sidecar(video_path: str, sidecar_path: Path | None = None) -> dict[str, Any]:
    """Validate sidecar parseability and return a compact summary."""
    path = sidecar_path or _sidecar_path(video_path)
    if path is None or not path.exists():
        raise FileNotFoundError("perception sidecar not found")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload.get("detections", []), list):
        raise ValueError("perception sidecar detections must be a list")
    detections = load_sidecar_detections(video_path)
    return {
        "path": str(path),
        "status": str(payload.get("status") or "ok"),
        "reason": payload.get("reason"),
        "detection_count": len(detections),
    }


def ensure_sidecar_for_video(video_path: str) -> dict[str, Any]:
    """Run the configured pre-analysis producer when a sidecar is missing.

    Without SPORTREEL_PERCEPTION_COMMAND this writes an explicit skipped sidecar
    unless SPORTREEL_REQUIRE_PERCEPTION is enabled, in which case it fails closed.
    """
    existing = _sidecar_path(video_path)
    if existing is not None:
        try:
            summary = validate_sidecar(video_path, existing)
            if _is_reusable_sidecar(summary):
                return {**summary, "producer_status": "existing"}
            logger.info(
                "Ignoring non-reusable perception sidecar for %s: status=%s reason=%s",
                video_path,
                summary.get("status"),
                summary.get("reason"),
            )
        except Exception as exc:
            if perception_required():
                raise RuntimeError(f"Invalid perception sidecar: {exc}") from exc
            logger.warning("Ignoring invalid perception sidecar for %s: %s", video_path, exc)

    output = sidecar_output_path(video_path)
    command = os.getenv(_COMMAND_ENV, "").strip()
    if not command:
        if perception_required():
            raise RuntimeError(f"{_COMMAND_ENV} is required when {_REQUIRED_ENV}=1")
        _write_status_sidecar(video_path, output, "skipped", "perception_command_not_configured")
        return {"path": str(output), "producer_status": "skipped", "detection_count": 0}

    output.parent.mkdir(parents=True, exist_ok=True)
    args = _render_command(command, video_path, output)
    env = {
        **os.environ,
        "SPORTREEL_VIDEO_PATH": video_path,
        "SPORTREEL_PERCEPTION_OUTPUT": str(output),
    }
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=_timeout_sec(), env=env)
    except Exception as exc:
        if perception_required():
            raise RuntimeError(f"Perception producer failed: {exc}") from exc
        logger.warning("Perception producer failed for %s: %s", video_path, exc)
        _write_status_sidecar(video_path, output, "failed", str(exc))
        return {"path": str(output), "producer_status": "failed", "detection_count": 0}

    try:
        summary = validate_sidecar(video_path, output)
    except Exception as exc:
        if perception_required():
            raise RuntimeError(f"Perception producer wrote invalid sidecar: {exc}") from exc
        logger.warning("Perception producer wrote invalid sidecar for %s: %s", video_path, exc)
        _write_status_sidecar(video_path, output, "failed", f"invalid_sidecar: {exc}")
        return {"path": str(output), "producer_status": "failed", "detection_count": 0}
    if not _is_reusable_sidecar(summary):
        if perception_required():
            raise RuntimeError(_non_reusable_error(summary))
        return {**summary, "producer_status": _producer_status_from_sidecar(summary)}
    return {**summary, "producer_status": "created"}


def _event_window(event: dict[str, Any]) -> tuple[float, float]:
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    return (min(start, end), max(start, end))


def _event_mid(event: dict[str, Any]) -> float:
    start, end = _event_window(event)
    return (start + end) / 2.0


def _in_window(detections: list[PerceptionDetection], event: dict[str, Any]) -> list[PerceptionDetection]:
    start, end = _event_window(event)
    return [detection for detection in detections if start <= detection.time_sec <= end]


def _nearest(detections: list[PerceptionDetection], event: dict[str, Any]) -> PerceptionDetection | None:
    if not detections:
        return None
    mid = _event_mid(event)
    nearest = min(detections, key=lambda detection: abs(detection.time_sec - mid))
    return nearest if abs(nearest.time_sec - mid) <= _MAX_NEAREST_SEC else None


def _best_primary(candidates: list[PerceptionDetection], event: dict[str, Any]) -> PerceptionDetection | None:
    if not candidates:
        return None
    mid = _event_mid(event)
    return max(
        candidates,
        key=lambda detection: (
            detection.confidence if detection.confidence is not None else 0.0,
            -abs(detection.time_sec - mid),
            detection.visible_ratio,
        ),
    )


def _track_ids(candidates: list[PerceptionDetection]) -> list[str]:
    ids = {str(detection.tracker_id) for detection in candidates if detection.tracker_id is not None}
    return sorted(ids)


def enrich_event(event: dict[str, Any], detections: list[PerceptionDetection]) -> dict[str, Any]:
    """Attach bbox/track evidence to one event without mutating input."""
    window_detections = _in_window(detections, event)
    primary = _best_primary(window_detections, event) or _nearest(detections, event)
    if primary is None:
        return {**event, "perception_evidence_status": "no_tracker_detection"}
    visible_ids = _track_ids(window_detections or [primary])
    metadata = primary.to_event_metadata()
    if visible_ids:
        metadata.update({
            "source_window_track_ids": visible_ids,
            "visible_track_ids": visible_ids,
            "all_visible_track_ids": visible_ids,
        })
    return {
        **event,
        **metadata,
        "perception_evidence_status": "tracker_sidecar",
        "perception_detection_count": len(window_detections),
    }


def enrich_session_with_sidecar(session: dict[str, Any], video_path: str) -> dict[str, Any]:
    try:
        detections = load_sidecar_detections(video_path)
    except Exception as exc:
        if perception_required():
            raise
        logger.warning("Skipping invalid perception sidecar during enrichment for %s: %s", video_path, exc)
        return {**session, "perception_evidence_source": "tracker_sidecar_error", "perception_evidence_error": str(exc)}
    if not detections:
        return session
    people = []
    for person in session.get("persons", []) or []:
        events = [enrich_event(event, detections) for event in person.get("events", []) or []]
        people.append({**person, "events": events, "perception_evidence_source": "tracker_sidecar"})
    return {**session, "persons": people, "perception_evidence_source": "tracker_sidecar"}


def install() -> None:
    """Patch analyzer so sidecar evidence lands before crop/identity guards."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, _INSTALLED_FLAG, False):
        return
    original = analyzer.analyze_session

    def analyze_with_perception_sidecar(video_path: str) -> dict:
        ensure_sidecar_for_video(video_path)
        result = original(video_path)
        if isinstance(result, dict):
            return enrich_session_with_sidecar(result, video_path)
        return result

    analyzer.analyze_session = analyze_with_perception_sidecar
    setattr(analyzer, _INSTALLED_FLAG, True)


__all__ = [
    "candidate_sidecar_paths",
    "sidecar_output_path",
    "load_sidecar_detections",
    "validate_sidecar",
    "ensure_sidecar_for_video",
    "enrich_event",
    "enrich_session_with_sidecar",
    "install",
]
