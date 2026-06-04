"""
integrations/ffmpeg.py — FFprobe/FFmpeg utility helpers.
Provides reusable functions for querying video metadata via ffprobe.
"""

import json
import logging
import subprocess
from functools import lru_cache

logger = logging.getLogger(__name__)

# Minimum FPS for smooth slow-motion (duplicated from editor constants for isolation)
_SLOWMO_FPS_MIN = 50


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


def get_source_info(video_path: str) -> dict:
    """Return dict with width, height, fps, zoom_headroom, can_slowmo for a video file."""
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
        zoom_headroom = w / 1920
        return {
            "width": w, "height": h, "fps": round(fps, 1),
            "zoom_headroom": round(zoom_headroom, 2),
            "can_slowmo": fps >= _SLOWMO_FPS_MIN,
        }
    except Exception as e:
        logger.debug("get_source_info failed for %s: %s", video_path, e)
        return {"width": 1920, "height": 1080, "fps": 30.0,
                "zoom_headroom": 1.0, "can_slowmo": False}


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
