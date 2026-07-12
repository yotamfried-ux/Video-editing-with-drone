"""
integrations/ffmpeg.py — FFprobe/FFmpeg utility helpers.
Provides reusable functions for querying video metadata via ffprobe.
"""

import json
import logging
import os
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


def _file_revision(path: str) -> tuple[int | None, int | None, int | None, int | None]:
    """Return a cache key that changes for in-place and atomic file replacement."""
    try:
        stat = os.stat(path)
    except OSError:
        return None, None, None, None
    # inode catches atomic os.replace publication even when a filesystem assigns
    # identical timestamp values and the replacement has the same byte size.
    return stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


@lru_cache(maxsize=512)
def _get_duration_cached(
    path: str,
    inode: int | None,
    mtime_ns: int | None,
    ctime_ns: int | None,
    size_bytes: int | None,
) -> float:
    # Revision fields are deliberately part of the cache key. QA re-edit writes a
    # longer clip back to the same path; path-only caching returned the old duration
    # and caused compile_reel to fade the replacement clip to black too early.
    del inode, mtime_ns, ctime_ns, size_bytes
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


def get_duration(path: str) -> float:
    """Return video duration, invalidating cached values after file rewrites."""
    normalized = os.fspath(path)
    return _get_duration_cached(normalized, *_file_revision(normalized))


def clear_duration_cache() -> None:
    """Clear all cached FFprobe durations, primarily for tests and explicit resets."""
    _get_duration_cached.cache_clear()


# Preserve the cache-control surface callers may expect from the previous
# @lru_cache-decorated public function.
get_duration.cache_clear = clear_duration_cache  # type: ignore[attr-defined]
get_duration.cache_info = _get_duration_cached.cache_info  # type: ignore[attr-defined]


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
        s = data["streams"][0]
        w, h = int(s["width"]), int(s["height"])
        num, den = s["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        profile = _render_profile(w, h)
        return {
            "width": w, "height": h, "fps": round(fps, 1),
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
    """Technical specs for social-media compliance checks. Best-effort; never raises."""
    info = get_source_info(path)
    dur = get_duration(path)
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
