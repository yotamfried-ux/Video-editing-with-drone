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
import math
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from integrations import llm_cache as _llm_cache
from .schema import PerceptionDetection

logger = logging.getLogger(__name__)

_INSTALLED_FLAG = "_sportreel_perception_runtime_installed"
_SIDECAR_CACHE_VERSION = "2"
_SIDECAR_ENV = "SPORTREEL_PERCEPTION_SIDECAR_DIR"
_COMMAND_ENV = "SPORTREEL_PERCEPTION_COMMAND"
_REQUIRED_ENV = "SPORTREEL_REQUIRE_PERCEPTION"
_TIMEOUT_ENV = "SPORTREEL_PERCEPTION_TIMEOUT_SEC"
_MAX_NEAREST_SEC = 1.0
_DIAGNOSTIC_LIMIT = 4000
_TRUE_VALUES = {"1", "true", "yes", "on", "required"}
_REUSABLE_SIDECAR_STATUSES = {"ok"}
_DETECTOR_STAT_KEYS = ("frames_processed", "raw_person_boxes", "max_person_confidence", "frame_width", "frame_height")


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


_CONCURRENCY_ENV = "SPORTREEL_PERCEPTION_CONCURRENCY"
_PRODUCER_SLOTS: threading.BoundedSemaphore | None = None
_PRODUCER_SLOTS_LOCK = threading.Lock()


def _producer_slots() -> threading.BoundedSemaphore:
    """Process-wide cap on concurrent CPU-bound perception producers.

    Each producer already saturates every core (multi-threaded 4K decode + torch inference). With
    ANALYSIS_WORKERS=3 on a 4-vCPU runner, three producers at once oversubscribed the CPU so badly that
    three clips took longer than running them one after another. Analysis workers still overlap their
    Gemini uploads/calls (network waits) while one producer owns the CPU.
    """
    global _PRODUCER_SLOTS
    with _PRODUCER_SLOTS_LOCK:
        if _PRODUCER_SLOTS is None:
            try:
                n = max(1, int(os.getenv(_CONCURRENCY_ENV, "1")))
            except ValueError:
                n = 1
            _PRODUCER_SLOTS = threading.BoundedSemaphore(n)
        return _PRODUCER_SLOTS


def _timeout_sec() -> int:
    try:
        return max(1, int(os.getenv(_TIMEOUT_ENV, "1200")))
    except ValueError:
        return 1200


def _clip_diagnostic(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) <= _DIAGNOSTIC_LIMIT:
        return text
    return f"{text[-_DIAGNOSTIC_LIMIT:]} [truncated to last {_DIAGNOSTIC_LIMIT} chars]"


def _producer_failure_message(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return (
            "Perception producer failed: "
            f"returncode={exc.returncode}; "
            f"stdout={_clip_diagnostic(exc.stdout)!r}; "
            f"stderr={_clip_diagnostic(exc.stderr)!r}"
        )
    if isinstance(exc, subprocess.TimeoutExpired):
        return (
            "Perception producer timed out: "
            f"timeout={exc.timeout}; "
            f"stdout={_clip_diagnostic(exc.stdout)!r}; "
            f"stderr={_clip_diagnostic(exc.stderr)!r}"
        )
    return f"Perception producer failed: {exc}"


def _render_command(command: str, video_path: str, sidecar_path: Path) -> list[str]:
    """Render a configured command without using a shell.

    A command may include `{video_path}` and `{sidecar_path}` placeholders. If no
    placeholders are present, both paths are appended as positional arguments.
    The environment also receives SPORTREEL_VIDEO_PATH and
    SPORTREEL_PERCEPTION_OUTPUT.
    """
    args = shlex.split(command)
    if os.name == "nt":
        raw_tokens = shlex.split(command, posix=False)
        merged_tokens: list[str] = []
        i = 0
        while i < len(raw_tokens):
            tok = raw_tokens[i].strip('"')
            if not os.path.exists(tok) and i + 1 < len(raw_tokens):
                for j in range(len(raw_tokens), i + 1, -1):
                    candidate = " ".join(t.strip('"') for t in raw_tokens[i:j])
                    if os.path.exists(candidate):
                        tok = candidate
                        i = j - 1
                        break
            merged_tokens.append(tok)
            i += 1
        args = merged_tokens
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
    status = summary.get('status')
    reason = summary.get('reason')
    if summary.get('technical_failure'):
        return f"Perception producer encountered a technical failure: status={status} reason={reason}"
    message = f"Perception producer did not create a reusable sidecar: status={status} reason={reason}"
    if "frames_processed" in summary:
        raw = summary.get("raw_person_boxes")
        message += (
            f" (detection_count={summary.get('detection_count')} frames_processed={summary.get('frames_processed')} "
            f"raw_person_boxes={raw} max_person_confidence={summary.get('max_person_confidence')} "
            f"frame_size={summary.get('frame_width')}x{summary.get('frame_height')}; "
            + ("persons were detected but the tracker never confirmed a track"
               if isinstance(raw, int) and raw > 0 and not summary.get("detection_count")
               else "no person-like detection in any sampled frame")
            + ")"
        )
    return message


def _producer_status_from_sidecar(summary: dict[str, Any]) -> str:
    status = _sidecar_status(summary)
    return "created" if status in _REUSABLE_SIDECAR_STATUSES else status


def _detections_from_payload(video_path: str, payload: dict[str, Any]) -> list[PerceptionDetection]:
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


def load_sidecar_detections(video_path: str) -> list[PerceptionDetection]:
    """Load normalized detections from the detector/tracker sidecar if present."""
    path = _sidecar_path(video_path)
    if path is None:
        return []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return _detections_from_payload(video_path, payload)


def validate_sidecar(video_path: str, sidecar_path: Path | None = None) -> dict[str, Any]:
    """Validate sidecar parseability, source identity, and return a compact summary."""
    path = sidecar_path or _sidecar_path(video_path)
    if path is None or not path.exists():
        raise FileNotFoundError("perception sidecar not found")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("perception sidecar root must be a JSON object")
    if not isinstance(payload.get("detections", []), list):
        raise ValueError("perception sidecar detections must be a list")
    recorded_sha = payload.get("source_sha256")
    if recorded_sha and os.path.exists(video_path):
        actual_sha = _llm_cache.file_sha256(video_path)
        if str(recorded_sha) != str(actual_sha):
            raise ValueError("perception sidecar source_sha256 mismatch with source video")
    detections = _detections_from_payload(video_path, payload)
    claimed_empty = bool(payload.get("empty_scene_verified")) or payload.get("classification") == "empty_scene"
    if claimed_empty and detections:
        raise ValueError("empty_scene assertion contradicts actual person detections")
    # Detector output is not an independent emptiness proof. Do not trust
    # legacy/imported sidecar flags to erase a surfer's LLM/GT events.
    # Independently verified emptiness needs a separate trusted review boundary.
    unverified_empty_claim = claimed_empty and not detections
    summary = {
        "path": str(path),
        "status": str(payload.get("status") or "ok"),
        "reason": "empty_scene_claim_lacks_independent_evidence" if unverified_empty_claim else payload.get("reason"),
        "detection_count": len(detections),
        "classification": "review_required" if unverified_empty_claim else payload.get("classification"),
        "empty_scene_verified": False if unverified_empty_claim else bool(payload.get("empty_scene_verified")),
        "technical_failure": bool(payload.get("technical_failure")),
    }
    # Detector-side counters written by scripts/generate_perception_sidecar.py (absent in older sidecars).
    for key in _DETECTOR_STAT_KEYS:
        if key in payload:
            summary[key] = payload[key]
    return summary


def load_sidecar_context(video_path: str) -> dict[str, Any]:
    """Load equipment links and activity profiles from the sidecar (computing if absent)."""
    path = _sidecar_path(video_path)
    if path is None or not path.exists():
        return {"athlete_equipment_links": {}, "track_activity_profiles": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return {"athlete_equipment_links": {}, "track_activity_profiles": {}}
        links = payload.get("athlete_equipment_links")
        profiles = payload.get("track_activity_profiles")
        if isinstance(links, dict) and isinstance(profiles, dict):
            return {"athlete_equipment_links": links, "track_activity_profiles": profiles}
        from .equipment_association import associate_equipment_with_athletes, classify_track_activity_profiles
        raw_dets = [d for d in (payload.get("detections") or []) if isinstance(d, dict)]
        raw_equips = [d for d in (payload.get("equipment_detections") or []) if isinstance(d, dict)]
        enriched_dets, computed_links = associate_equipment_with_athletes(raw_dets, raw_equips)
        computed_profiles = classify_track_activity_profiles(enriched_dets, computed_links)
        return {"athlete_equipment_links": computed_links, "track_activity_profiles": computed_profiles}
    except Exception:
        return {"athlete_equipment_links": {}, "track_activity_profiles": {}}


def _sidecar_cache_key(video_path: str, command: str) -> str | None:
    """Return a content-addressed cache key for the video's perception sidecar (GATE-06)."""
    if not _llm_cache.enabled() or not os.path.exists(video_path):
        return None
    try:
        media_sha = _llm_cache.file_sha256(video_path)
        model = os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "yolo11s.pt").strip()
        tracker = os.getenv("SPORTREEL_ULTRALYTICS_TRACKER", "botsort.yaml").strip()
        stride = os.getenv("SPORTREEL_ULTRALYTICS_VID_STRIDE", "5").strip()
        imgsz = os.getenv("SPORTREEL_ULTRALYTICS_IMGSZ", "640").strip()
        min_conf = os.getenv("SPORTREEL_PERCEPTION_MIN_CONFIDENCE", "0").strip()
        fps_cfg = os.getenv("SPORTREEL_ULTRALYTICS_FPS", "auto").strip().lower()
        if fps_cfg in {"", "auto", "detect", "native"}:
            try:
                import cv2
                cap = cv2.VideoCapture(video_path)
                detected = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                cap.release()
                fps = f"{round(detected, 2)}" if detected > 0 else "30"
            except Exception:
                fps = "30"
        else:
            fps = fps_cfg
        detect_eq = os.getenv("SPORTREEL_DETECT_EQUIPMENT", "1").strip()
        adaptive = os.getenv("SPORTREEL_ADAPTIVE_INFERENCE", "1").strip()
        extra = (
            f"tracker={tracker}|stride={stride}|imgsz={imgsz}|conf={min_conf}"
            f"|fps={fps}|equip={detect_eq}|adaptive={adaptive}|stitch=v2"
        )
        return _llm_cache.make_key(
            "perception-sidecar",
            media_sha256=media_sha,
            prompt=command,
            model=model,
            version=_SIDECAR_CACHE_VERSION,
            extra=extra,
        )
    except Exception as exc:
        logger.debug("sidecar cache key skipped: %s", exc)
        return None


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
    cache_key = _sidecar_cache_key(video_path, command)
    if cache_key:
        cached_json = _llm_cache.get(cache_key)
        if cached_json:
            try:
                tmp = output.with_suffix(output.suffix + ".cache.tmp")
                tmp.write_text(cached_json, encoding="utf-8")
                tmp.replace(output)
                summary = validate_sidecar(video_path, output)
                if _is_reusable_sidecar(summary) and int(summary.get("detection_count") or 0) > 0:
                    print(f"♻️  Perception sidecar cache hit for '{Path(video_path).name}' ({summary.get('detection_count')} detections)")
                    return {**summary, "producer_status": "existing"}
            except Exception as exc:
                logger.debug("Cached perception sidecar unusable for %s: %s", video_path, exc)

    args = _render_command(command, video_path, output)
    env = {
        **os.environ,
        "SPORTREEL_VIDEO_PATH": video_path,
        "SPORTREEL_PERCEPTION_OUTPUT": str(output),
    }
    try:
        from integrations.stage_timer import timed
        waited = time.monotonic()
        with _producer_slots():
            waited = time.monotonic() - waited
            if waited >= 1.0:
                print(f"⏳ Perception slot acquired for '{Path(video_path).name}' after {waited:.0f}s (one CPU-bound producer at a time)")
            # The timeout bounds the producer itself, never time spent waiting for a slot.
            with timed("yolo_perception", source=Path(video_path).name):
                subprocess.run(args, check=True, capture_output=True, text=True, timeout=_timeout_sec(), env=env)
    except Exception as exc:
        message = _producer_failure_message(exc)
        if perception_required():
            raise RuntimeError(message) from exc
        logger.warning("%s", message)
        _write_status_sidecar(video_path, output, "failed", message)
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
    if cache_key and int(summary.get("detection_count") or 0) > 0:
        try:
            _llm_cache.put(
                cache_key,
                output.read_text(encoding="utf-8"),
                source=Path(video_path).name,
                detection_count=summary.get("detection_count"),
            )
        except Exception as exc:
            logger.debug("Perception sidecar cache write skipped: %s", exc)
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


def _event_crop_point(event: dict[str, Any]) -> tuple[float, float] | None:
    try:
        x = float(event.get("crop_x"))
        y = float(event.get("crop_y"))
    except (TypeError, ValueError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return None
    return x, y


def _track_score(
    detections: list[PerceptionDetection],
    event: dict[str, Any],
    *,
    max_window_len: int | None = None,
) -> tuple[float, float, float, float]:
    """Rank a whole track using persistence, kinematic motion, and spatial proximity.

    Never allow a 1-4 frame noise detection or stationary bystander to beat a
    sustained moving athlete track simply because of a slightly closer single-point
    Euclidean distance to a static crop hint.
    """
    if not detections:
        return (-1.0, -1.0, -1.0, -1.0)
    n = len(detections)
    start, end = _event_window(event)
    window_dur = max(0.5, end - start)

    times = [float(d.time_sec) for d in detections]
    span = max(0.0, max(times) - min(times))
    coverage = min(1.0, span / window_dur) if window_dur >= 1.5 else 1.0

    ref_len = max(n, int(max_window_len or n))
    persistence = min(1.0, n / max(4.0, float(ref_len) * 0.65)) if ref_len >= 4 else 1.0
    if ref_len >= 8 and n < 4:
        micro_penalty = 0.15
    elif ref_len >= 15 and n < 6:
        micro_penalty = 0.45
    else:
        micro_penalty = 1.0

    cxs = [((d.xyxy[0] + d.xyxy[2]) / 2.0) / max(1.0, float(d.frame_width)) for d in detections]
    cys = [((d.xyxy[1] + d.xyxy[3]) / 2.0) / max(1.0, float(d.frame_height)) for d in detections]
    disp = math.hypot(max(cxs) - min(cxs), max(cys) - min(cys))
    motion_score = min(1.0, disp / 0.25) if ref_len >= 6 else 0.5

    crop = _event_crop_point(event)
    crop_match = 0.5
    if crop is not None:
        distances = sorted(math.hypot(cx - crop[0], cy - crop[1]) for cx, cy in zip(cxs, cys))
        k = max(1, len(distances) // 3)
        best_dist = sum(distances[:k]) / k
        mean_dist = sum(distances) / len(distances)
        crop_match = 0.65 * (1.0 - min(1.0, best_dist)) + 0.35 * (1.0 - min(1.0, mean_dist))

    confidence = sum((d.confidence or 0.0) for d in detections) / n
    visible = sum(d.visible_ratio for d in detections) / n

    if ref_len <= 2:
        composite = crop_match if crop is not None else confidence
    else:
        composite = micro_penalty * (
            0.42 * crop_match
            + 0.28 * persistence
            + 0.15 * coverage
            + 0.10 * motion_score
            + 0.05 * confidence
        )
    return (round(composite, 6), float(n), round(confidence, 4), round(visible, 4))


def _best_primary(
    candidates: list[PerceptionDetection],
    event: dict[str, Any],
    *,
    claimed_tracks: set[str] | None = None,
    track_profiles: dict[str, dict[str, Any]] | None = None,
) -> PerceptionDetection | None:
    if not candidates:
        return None
    by_track: dict[str, list[PerceptionDetection]] = {}
    for detection in candidates:
        if detection.tracker_id is not None:
            by_track.setdefault(str(detection.tracker_id), []).append(detection)
    if not by_track:
        return None
    max_len = max((len(items) for items in by_track.values()), default=1)
    claimed = claimed_tracks or set()

    def _rank_key(item: tuple[str, list[PerceptionDetection]]) -> tuple[float, float, float, float]:
        tid, dets = item
        score = _track_score(dets, event, max_window_len=max_len)
        comp = score[0]
        if track_profiles and len(by_track) > 1:
            prof = track_profiles.get(tid) or {}
            state = prof.get("activity_state")
            eq_ratio = float(prof.get("equipment_association_ratio") or 0.0)
            if state == "active":
                comp += 0.04 + min(0.04, eq_ratio * 0.06)
            elif state == "waiting":
                comp *= 0.85
            elif state == "background_passerby":
                comp *= 0.65
        if tid in claimed and len(by_track) > 1:
            comp *= 0.72
        return (round(comp, 6), score[1], score[2], score[3])

    best_id, track_detections = max(by_track.items(), key=_rank_key)
    mid = _event_mid(event)
    primary = min(track_detections, key=lambda detection: abs(detection.time_sec - mid))
    return primary


def _track_ids(candidates: list[PerceptionDetection]) -> list[str]:
    ids = {str(detection.tracker_id) for detection in candidates if detection.tracker_id is not None}
    return sorted(ids)


def enrich_event(
    event: dict[str, Any],
    detections: list[PerceptionDetection],
    *,
    claimed_tracks: set[str] | None = None,
    sidecar_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach bbox/track evidence to one event without mutating input."""
    profiles = (sidecar_context or {}).get("track_activity_profiles") or {}
    equip_links = (sidecar_context or {}).get("athlete_equipment_links") or {}
    window_detections = _in_window(detections, event)
    primary = (
        _best_primary(window_detections, event, claimed_tracks=claimed_tracks, track_profiles=profiles)
        or _nearest(detections, event)
    )
    if primary is None:
        return {**event, "perception_evidence_status": "no_tracker_detection"}
    visible_ids = _track_ids(window_detections or [primary])
    metadata = primary.to_event_metadata()
    if primary.tracker_id is not None:
        tid_str = str(primary.tracker_id)
        metadata.update({
            "target_track_id": tid_str,
            "track_binding_source": "cv_track_continuity_with_llm_crop_hint" if _event_crop_point(event) else "cv_track_continuity",
        })
        if tid_str in profiles:
            metadata["athlete_activity_state"] = profiles[tid_str].get("activity_state")
            metadata["athlete_activity_score"] = profiles[tid_str].get("activity_score")
        if tid_str in equip_links:
            metadata["associated_equipment"] = equip_links[tid_str].get("primary_equipment")
            metadata["equipment_association_ratio"] = equip_links[tid_str].get("equipment_association_ratio")
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


def _window_refiner():
    """Window trimming against the tracked athlete span; a no-op when disabled or on any error."""
    try:
        from pipeline import window_refinement
        if not window_refinement.enabled():
            return lambda event, _detections: event
    except Exception as exc:  # fail open: refinement must never break enrichment
        logger.warning("window refinement unavailable: %s", exc)
        return lambda event, _detections: event

    def refine(event: dict[str, Any], detections: list[PerceptionDetection]) -> dict[str, Any]:
        try:
            return window_refinement.refine_event_window(event, detections)
        except Exception as exc:
            logger.warning("window refinement skipped for event at %s: %s", event.get("start"), exc)
            return event

    return refine


def _windows_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    sa, ea = _event_window(a)
    sb, eb = _event_window(b)
    overlap = max(0.0, min(ea, eb) - max(sa, sb))
    return overlap >= 1.5


def enrich_session_with_sidecar(session: dict[str, Any], video_path: str) -> dict[str, Any]:
    try:
        detections = load_sidecar_detections(video_path)
    except Exception as exc:
        if perception_required():
            raise
        logger.warning("Skipping invalid perception sidecar during enrichment for %s: %s", video_path, exc)
        return {**session, "perception_evidence_source": "tracker_sidecar_error", "perception_evidence_error": str(exc)}
    if not detections:
        sidecar_p = _sidecar_path(video_path)
        if sidecar_p and sidecar_p.exists():
            try:
                summary = validate_sidecar(video_path, sidecar_p)
                if summary.get("classification") == "review_required":
                    persons = list(session.get("persons", []) or [])
                    return {
                        **session,
                        # Mandatory-CV policy cannot render untracked actions, but
                        # retain the originals and an explicit source/athlete reason.
                        "persons": [
                            {
                                **person,
                                "unverified_events": list(person.get("events", []) or []),
                                "events": [],
                                "no_output_reason": "perception_zero_detection_unverified",
                                "review_required": True,
                            }
                            for person in persons
                        ],
                        "perception_evidence_source": "zero_detection_after_escalation",
                        "perception_evidence_status": "review_required",
                        "perception_review_required": True,
                        "perception_unverified_events_count": sum(
                            len(person.get("events", []) or []) for person in persons
                        ),
                        "empty_scene_verified": False,
                    }
                if summary.get("empty_scene_verified") or summary.get("classification") == "empty_scene":
                    return {
                        **session,
                        "persons": [],
                        "perception_evidence_source": "empty_scene",
                        "perception_evidence_status": "empty_scene",
                        "empty_scene_verified": True,
                    }
            except Exception:
                pass
        return session
    refine = _window_refiner()
    sidecar_ctx = load_sidecar_context(video_path)
    people = []
    assigned_events: list[tuple[dict[str, Any], str]] = []
    for person in session.get("persons", []) or []:
        events = []
        for event in person.get("events", []) or []:
            claimed = {
                tid for prev_ev, tid in assigned_events if _windows_overlap(event, prev_ev)
            }
            enriched = enrich_event(event, detections, claimed_tracks=claimed, sidecar_context=sidecar_ctx)
            tid = enriched.get("target_track_id") or enriched.get("track_id")
            if tid is not None:
                assigned_events.append((event, str(tid)))
            events.append(refine(enriched, detections))
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
