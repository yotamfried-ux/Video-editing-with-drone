"""
integrations/ffmpeg.py — FFprobe/FFmpeg utility helpers.
Provides reusable functions for querying video metadata via ffprobe.
"""

import json
import logging
import subprocess
from functools import lru_cache

import config

logger = logging.getLogger(__name__)

# Minimum FPS for smooth slow-motion (duplicated from editor constants for isolation)
_SLOWMO_FPS_MIN = 50
_REEL_1080_W = 1080
_REEL_1080_H = 1920
_REEL_720_W = 720
_REEL_720_H = 1280


@lru_cache(maxsize=256)
def get_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe. Returns inf on error."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        return float(subprocess.check_output(cmd, text=True, timeout=30).strip())
    except Exception:
        return float("inf")


@lru_cache(maxsize=256)
def get_source_fps(video_path: str) -> float:
    """Return source video FPS via ffprobe. Returns 30.0 on error."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        raw = subprocess.check_output(cmd, text=True, timeout=15).strip()
        num, den = raw.split("/")
        return round(float(num) / float(den), 2)
    except Exception:
        return 30.0


def _safe_zoom_headroom(width: int, height: int) -> float:
    """Return the no-upscale zoom ceiling for a 9:16 1080x1920 render.

    The previous implementation used only source width (width / 1920). That is
    unsafe for landscape footage: 1920x1080 looks like it has 1.0x horizontal
    headroom, but a 1080x1920 portrait reel must already upscale the source
    vertically by 1.78x before any artistic zoom. For quality preservation, the
    ceiling must consider both output dimensions.
    """
    if width <= 0 or height <= 0:
        return 1.0
    return min(width / _REEL_1080_W, height / _REEL_1080_H)


def _render_profile(width: int, height: int) -> dict:
    """Summarize quality risk for the current editor render path."""
    safe_zoom = _safe_zoom_headroom(width, height)
    upscale_1080 = _REEL_1080_H / height if height else float("inf")
    upscale_720 = _REEL_720_H / height if height else float("inf")
    full_hd_safe = height >= config.REEL_FULL_HD_MIN_SOURCE_HEIGHT
    recommended_w, recommended_h = (
        (_REEL_1080_W, _REEL_1080_H) if full_hd_safe else (_REEL_720_W, _REEL_720_H)
    )

    warnings: list[str] = []
    if upscale_1080 >= config.REEL_WARN_UPSCALE_FACTOR:
        warnings.append(
            f"1080x1920 render would upscale source height by {upscale_1080:.2f}x"
        )
    if safe_zoom < 1.15:
        warnings.append("disable extra zoom to avoid upscaling/crop softness")
    if height < config.MIN_SOURCE_HEIGHT:
        warnings.append(
            f"source height {height}px below quality floor {config.MIN_SOURCE_HEIGHT}px"
        )

    if height >= 2160:
        tier = "4k_safe"
    elif height >= config.REEL_FULL_HD_MIN_SOURCE_HEIGHT:
        tier = "hd_safe"
    elif height >= 1080:
        tier = "upscale_risk"
    else:
        tier = "low_res"

    return {
        "render_quality_tier": tier,
        "safe_zoom_headroom": round(safe_zoom, 2),
        "portrait_upscale_1080": round(max(1.0, upscale_1080), 2),
        "portrait_upscale_720": round(max(1.0, upscale_720), 2),
        "recommended_reel_width": recommended_w,
        "recommended_reel_height": recommended_h,
        "quality_warnings": warnings,
    }


def get_source_info(video_path: str) -> dict:
    """Return source metadata and render-risk diagnostics for a video file."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-of", "json", video_path],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        s    = data["streams"][0]
        w, h = int(s["width"]), int(s["height"])
        num, den = s["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        profile = _render_profile(w, h)
        return {
            "width": w, "height": h, "fps": round(fps, 1),
            # Used by editor.cut_clip() to cap zoom. This is now the safe 9:16
            # no-upscale ceiling, not width-only headroom.
            "zoom_headroom": profile["safe_zoom_headroom"],
            "can_slowmo": fps >= _SLOWMO_FPS_MIN,
            **profile,
        }
    except Exception as e:
        logger.debug("get_source_info failed for %s: %s", video_path, e)
        profile = _render_profile(1920, 1080)
        return {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": profile["safe_zoom_headroom"],
                "can_slowmo": False, **profile}


def get_reel_specs(path: str) -> dict:
    """Technical specs for social-media compliance checks. Best-effort; never raises.

    Returns: width, height, aspect (w/h), duration (None on error), has_audio.
    """
    info = get_source_info(path)          # width, height, fps (with safe fallbacks)
    dur  = get_duration(path)             # seconds (inf on error)
    has_audio = False
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        has_audio = "audio" in r.stdout
    except Exception:
        pass
    w, h = info["width"], info["height"]
    return {
        "width": w, "height": h,
        "aspect": round(w / h, 3) if h else 0,
        "duration": None if dur == float("inf") else round(dur, 1),
        "has_audio": has_audio,
    }