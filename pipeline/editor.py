"""
pipeline/editor.py — FFmpeg video cutting and watermark overlay.
חותך קליפים לפי timestamps ומוסיף לוגו בפינה הימנית התחתונה.
"""

import logging
import os
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _build_ffmpeg_cmd(
    video_path: str,
    start: float,
    end: float,
    logo_path: str,
    output_path: str,
) -> list[str]:
    """Build the FFmpeg command list for cutting + watermarking a clip."""
    duration = end - start

    # Overlay filter: logo bottom-right, 140px wide, 85% opacity
    overlay_filter = (
        f"[1:v]scale=140:-1,format=rgba,colorchannelmixer=aa=0.85[logo];"
        f"[0:v][logo]overlay=W-w-20:H-h-20[out]"
    )

    return [
        "ffmpeg",
        "-y",                          # overwrite without asking
        "-ss", str(start),             # seek before input (fast)
        "-i", video_path,
        "-i", logo_path,
        "-t", str(duration),
        "-filter_complex", overlay_filter,
        "-map", "[out]",
        "-map", "0:a?",                # include audio if present
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]


def cut_and_watermark(video_path: str, event: dict, index: int) -> str | None:
    """
    Cut a highlight clip and overlay the brand logo.

    Args:
        video_path: Local path to the source video file.
        event: Dict with keys: type, start, end, score, description.
        index: Clip number (used in output filename).

    Returns:
        Local path to the rendered clip, or None on failure.
    """
    start: float = event["start"]
    end: float = event["end"]
    event_type: str = event.get("type", "highlight")

    os.makedirs(config.TMP_DIR, exist_ok=True)

    base_name = Path(video_path).stem
    output_filename = f"{base_name}_clip{index:02d}_{event_type}.mp4"
    output_path = os.path.join(config.TMP_DIR, output_filename)

    logo_path = config.LOGO_PATH
    if not Path(logo_path).exists():
        # Use a transparent 1x1 PNG fallback so FFmpeg doesn't hard-fail
        logger.warning("⚠️ Logo not found at %s — clips will have no watermark", logo_path)
        print(f"⚠️ Logo missing at '{logo_path}' — clip will be cut without watermark")
        return _cut_only(video_path, start, end, output_path)

    print(f"🎬 Cutting clip {index}: {start:.1f}s → {end:.1f}s  [{event_type}]")

    cmd = _build_ffmpeg_cmd(video_path, start, end, logo_path, output_path)
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute cap per clip
        )
        if result.returncode != 0:
            logger.error("❌ FFmpeg error for clip %d:\n%s", index, result.stderr[-2000:])
            print(f"❌ FFmpeg failed for clip {index}: {result.stderr[-500:]}")
            return None

        print(f"✅ Clip {index} rendered: {output_path}")
        return output_path

    except subprocess.TimeoutExpired:
        logger.error("❌ FFmpeg timed out for clip %d", index)
        print(f"❌ FFmpeg timed out on clip {index}")
        return None
    except FileNotFoundError:
        logger.error("❌ FFmpeg not found. Install it: sudo apt install ffmpeg")
        print("❌ FFmpeg not found. Please install FFmpeg and retry.")
        return None
    except Exception as e:
        logger.error("❌ Unexpected editor error for clip %d: %s", index, e)
        print(f"❌ Unexpected error cutting clip {index}: {e}")
        return None


def _cut_only(video_path: str, start: float, end: float, output_path: str) -> str | None:
    """Fallback: cut without watermark when logo is unavailable."""
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return None
        return output_path
    except Exception:
        return None
