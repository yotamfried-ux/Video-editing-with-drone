"""Quality-first 4K framing for SportReel.

The default is a non-destructive ``contain`` render: the complete source frame is
kept inside a 2160x3840 vertical canvas.  A tracked crop is an emergency repair,
not an artistic default.  It is allowed only when measured detector/tracker
evidence proves that the athlete would otherwise be unreadably small, clipped by
the frame edge, or ambiguous among multiple tracked people.

Gemini edit hints never authorize crop or zoom on their own.
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 2160
OUTPUT_HEIGHT = 3840
OUTPUT_FPS = 30
MIN_TRACK_CONFIDENCE = 0.60
MIN_VISIBLE_RATIO = 0.55
SMALL_ATHLETE_HEIGHT_RATIO = 0.065
SMALL_ATHLETE_AREA_RATIO = 0.0025
AMBIGUOUS_ATHLETE_AREA_RATIO = 0.006
EDGE_MARGIN = 0.08
MAX_EMERGENCY_ZOOM = 1.30
_INSTALLED = False
_DECISION_LOCK = threading.Lock()


@dataclass(frozen=True)
class FramingDecision:
    mode: str
    reason: str
    zoom: float
    crop_x: float
    crop_y: float
    confidence: float
    visible_ratio: float
    athlete_height_ratio: float
    athlete_area_ratio: float
    visible_track_count: int


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _bbox_metrics(event: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    bbox = event.get("bbox_xyxy")
    width = _number(event.get("perception_frame_width") or event.get("frame_width"))
    height = _number(event.get("perception_frame_height") or event.get("frame_height"))
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or width <= 0 or height <= 0:
        raise RuntimeError("Mandatory perception bbox/frame dimensions are missing")
    x1, y1, x2, y2 = (_number(value) for value in bbox)
    if x2 <= x1 or y2 <= y1:
        raise RuntimeError("Mandatory perception bbox is invalid")
    center_x = max(0.0, min(1.0, ((x1 + x2) / 2.0) / width))
    center_y = max(0.0, min(1.0, ((y1 + y2) / 2.0) / height))
    height_ratio = max(0.0, (y2 - y1) / height)
    area_ratio = max(0.0, ((x2 - x1) * (y2 - y1)) / (width * height))
    return center_x, center_y, height_ratio, area_ratio, width, height


def _visible_track_count(event: dict[str, Any]) -> int:
    raw = (
        event.get("visible_track_ids")
        or event.get("all_visible_track_ids")
        or event.get("source_window_track_ids")
        or []
    )
    if isinstance(raw, (list, tuple, set)):
        return len({str(item) for item in raw if item is not None})
    return 1 if raw else 0


def decide_framing(
    event: dict[str, Any],
    *,
    sport: str = "",
    source_info: dict[str, Any] | None = None,
) -> FramingDecision:
    """Return a deterministic contain-or-emergency-crop decision.

    ``source_info`` is accepted for call-site symmetry and future diagnostics;
    crop permission is intentionally based on measured per-event CV evidence.
    """
    del source_info
    if event.get("perception_evidence_status") != "tracker_sidecar":
        raise RuntimeError("Framing requires tracker_sidecar evidence")
    if event.get("track_id") is None:
        raise RuntimeError("Framing requires a stable track_id")

    crop_x, crop_y, height_ratio, area_ratio, _, _ = _bbox_metrics(event)
    confidence = _number(event.get("perception_confidence"))
    visible_ratio = _number(event.get("visible_ratio"), 1.0)
    track_count = max(1, _visible_track_count(event))

    reasons: list[str] = []
    if height_ratio < SMALL_ATHLETE_HEIGHT_RATIO or area_ratio < SMALL_ATHLETE_AREA_RATIO:
        reasons.append("athlete_unreadably_small")
    if crop_x < EDGE_MARGIN or crop_x > 1.0 - EDGE_MARGIN or visible_ratio < 0.80:
        reasons.append("athlete_near_or_beyond_safe_edge")
    if track_count > 1 and area_ratio < AMBIGUOUS_ATHLETE_AREA_RATIO:
        reasons.append("multiple_tracks_with_small_primary_athlete")

    if not reasons:
        return FramingDecision(
            mode="contain",
            reason="full_frame_readable",
            zoom=1.0,
            crop_x=crop_x,
            crop_y=crop_y,
            confidence=confidence,
            visible_ratio=visible_ratio,
            athlete_height_ratio=height_ratio,
            athlete_area_ratio=area_ratio,
            visible_track_count=track_count,
        )

    if confidence < MIN_TRACK_CONFIDENCE or visible_ratio < MIN_VISIBLE_RATIO:
        raise RuntimeError(
            "Crop appears necessary but tracker evidence is not reliable enough: "
            f"confidence={confidence:.3f}, visible_ratio={visible_ratio:.3f}"
        )

    desired_height_ratio = 0.16 if sport.lower() == "surfing" else 0.18
    zoom = max(1.0, min(MAX_EMERGENCY_ZOOM, desired_height_ratio / max(height_ratio, 0.001)))
    return FramingDecision(
        mode="tracked_crop",
        reason="+".join(reasons),
        zoom=round(zoom, 3),
        crop_x=crop_x,
        crop_y=crop_y,
        confidence=confidence,
        visible_ratio=visible_ratio,
        athlete_height_ratio=height_ratio,
        athlete_area_ratio=area_ratio,
        visible_track_count=track_count,
    )


def _decision_log_path() -> Path:
    root = Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "pipeline-debug"
    root.mkdir(parents=True, exist_ok=True)
    return root / "framing_decisions.jsonl"


def _record_decision(video_path: str, event: dict[str, Any], decision: FramingDecision) -> None:
    payload = {
        "source_video": Path(video_path).name,
        "event_id": event.get("event_id") or event.get("id"),
        "event_type": event.get("type"),
        "sport": event.get("sport"),
        **asdict(decision),
    }
    with _DECISION_LOCK:
        with _decision_log_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _even(value: float, minimum: int = 2) -> int:
    result = max(minimum, int(round(value)))
    return result if result % 2 == 0 else result - 1


def _render_clip(
    video_path: str,
    event: dict[str, Any],
    index: int,
    decision: FramingDecision,
) -> str | None:
    from pipeline.stages import editor

    clamped = editor._clamp(event["start"], event["end"], video_path)
    if clamped is None:
        return None
    start, end = clamped
    duration = max(0.0, end - start)
    if duration <= 0:
        return None

    if decision.mode == "contain":
        filter_complex = (
            f"[0:v]split[bg_in][fg_in];"
            f"[bg_in]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
            "force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},gblur=sigma=30:steps=2[bg];"
            f"[fg_in]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
            "force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        )
    else:
        frame_w = _number(event.get("perception_frame_width") or event.get("frame_width"))
        frame_h = _number(event.get("perception_frame_height") or event.get("frame_height"))
        base_crop_h = frame_h
        base_crop_w = frame_h * 9.0 / 16.0
        if base_crop_w > frame_w:
            base_crop_w = frame_w
            base_crop_h = frame_w * 16.0 / 9.0
        crop_w = _even(base_crop_w / decision.zoom)
        crop_h = _even(base_crop_h / decision.zoom)
        center_x = decision.crop_x * frame_w
        center_y = decision.crop_y * frame_h
        x = max(0, min(_even(frame_w - crop_w, 0), int(round(center_x - crop_w / 2))))
        y = max(0, min(_even(frame_h - crop_h, 0), int(round(center_y - crop_h / 2))))
        filter_complex = (
            f"[0:v]crop={crop_w}:{crop_h}:{x}:{y},"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=lanczos,"
            "format=yuv420p[out]"
        )

    os.makedirs(os.getenv("TMP_DIR", "/tmp/dtor"), exist_ok=True)
    out = os.path.join(
        os.getenv("TMP_DIR", "/tmp/dtor"),
        f"{Path(video_path).stem}_clip{index:02d}.mp4",
    )
    command = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-an",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-crf", "12",
        "-preset", "slow",
        "-maxrate", "45M",
        "-bufsize", "90M",
        "-r", str(OUTPUT_FPS),
        "-g", str(OUTPUT_FPS * 2),
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart",
        out,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("4K framing render failed for %s: %s", video_path, exc)
        return None
    if completed.returncode != 0:
        logger.error("4K framing render failed: %s", completed.stderr[-1500:])
        try:
            os.remove(out)
        except OSError:
            pass
        return None
    return out


def quality_output_issues(specs: dict[str, Any], base_issues: list[str]) -> list[str]:
    issues = list(base_issues)
    try:
        width = int(specs.get("width") or 0)
        height = int(specs.get("height") or 0)
    except (TypeError, ValueError):
        width, height = 0, 0
    fps = _number(specs.get("fps"))
    if (width, height) != (OUTPUT_WIDTH, OUTPUT_HEIGHT):
        issues.append("resolution_not_4k_vertical")
    if abs(fps - OUTPUT_FPS) > 0.1:
        issues.append("frame_rate_not_30fps")
    return list(dict.fromkeys(issues))


def install() -> None:
    """Install quality-first framing and the 4K/30 publishability gate."""
    global _INSTALLED
    if _INSTALLED:
        return

    from integrations import ffmpeg as ffmpeg_helpers
    from pipeline import publishable_reel_policy
    from pipeline import silent_output_policy
    from pipeline.stages import editor

    editor.REEL_W = OUTPUT_WIDTH
    editor.REEL_H = OUTPUT_HEIGHT
    editor.CLIP_CRF = "12"
    editor.REEL_CRF = "14"
    editor.X264_PRESET = "slow"

    original_cut_clip = editor.cut_clip
    original_compile_reel = editor.compile_reel
    original_specs = ffmpeg_helpers.get_reel_specs
    original_issues = publishable_reel_policy.social_ready_issues

    def quality_cut_clip(
        video_path: str,
        event: dict[str, Any],
        index: int,
        slowmo: bool = False,
        sport: str = "",
        source_info: dict[str, Any] | None = None,
        session_peak: int = 10,
        target_fps: int | None = None,
    ) -> str | None:
        del slowmo, session_peak, target_fps
        decision = decide_framing(event, sport=sport, source_info=source_info)
        _record_decision(video_path, {**event, "sport": sport}, decision)
        return _render_clip(video_path, event, index, decision)

    def compile_4k_30(*args, **kwargs):
        mutable_args = list(args)
        if len(mutable_args) > 8:
            mutable_args[8] = OUTPUT_FPS
        else:
            kwargs["fps"] = OUTPUT_FPS
        return original_compile_reel(*mutable_args, **kwargs)

    def specs_with_fps(path: str) -> dict[str, Any]:
        specs = original_specs(path)
        return {**specs, "fps": ffmpeg_helpers.get_source_fps(path)}

    def publishable_issues(specs: dict[str, Any]) -> list[str]:
        return quality_output_issues(specs, original_issues(specs))

    editor.cut_clip = quality_cut_clip
    editor.compile_reel = compile_4k_30
    ffmpeg_helpers.get_reel_specs = specs_with_fps
    publishable_reel_policy.social_ready_issues = publishable_issues
    silent_output_policy.silent_social_ready_issues = publishable_issues
    setattr(editor, "_sportreel_quality_first_framing_installed", True)
    setattr(editor, "_sportreel_original_cut_clip_before_quality_first", original_cut_clip)
    _INSTALLED = True


__all__ = [
    "FramingDecision",
    "OUTPUT_WIDTH",
    "OUTPUT_HEIGHT",
    "OUTPUT_FPS",
    "decide_framing",
    "install",
    "quality_output_issues",
]
