"""
pipeline/editor.py — FFmpeg video cutting and watermark overlay.
חותך קליפים לפי timestamps, מוסיף לוגו שמותאם לרזולוציה, ו-fade in/out.
"""

import logging
import os
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _get_video_duration(video_path: str) -> float:
    """Return video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=30).strip()
        return float(out)
    except Exception:
        return float("inf")  # אם לא ידוע — נניח שהסרטון ארוך מספיק


def _clamp_timestamps(start: float, end: float, video_path: str) -> tuple[float, float]:
    """Clamp start/end so they don't exceed actual video duration."""
    duration = _get_video_duration(video_path)
    start = max(0.0, min(start, duration - 4))   # לפחות 4 שניות לפני הסוף
    end   = min(end, duration)
    if end - start < 4:
        end = min(start + 4, duration)
    return round(start, 2), round(end, 2)


def _build_ffmpeg_cmd(
    video_path: str,
    start: float,
    end: float,
    logo_path: str,
    output_path: str,
) -> list[str]:
    duration = end - start
    fade_dur = min(0.5, duration / 4)  # fade קצר אם הקליפ קצר מאוד

    # לוגו: 8% מרוחב הסרטון (scale2ref), 85% opacity, פינה ימין-תחתון
    # fade in + fade out על הוידאו הסופי
    overlay_filter = (
        f"[1:v][0:v]scale2ref=w=iw/12:h=-1[logo_scaled][base];"
        f"[logo_scaled]format=rgba,colorchannelmixer=aa=0.85[logo];"
        f"[base][logo]overlay=W-w-20:H-h-20[watermarked];"
        f"[watermarked]fade=t=in:st=0:d={fade_dur:.2f},"
        f"fade=t=out:st={duration - fade_dur:.2f}:d={fade_dur:.2f}[out]"
    )

    return [
        "ffmpeg",
        "-y",
        "-ss", str(start),        # fast seek לפני ה-input
        "-i", video_path,
        "-i", logo_path,
        "-t", str(duration),
        "-filter_complex", overlay_filter,
        "-map", "[out]",
        "-map", "0:a?",           # אודיו אופציונלי
        "-c:v", "libx264",
        "-crf", "22",             # שדרגנו מ-23 ל-22 לאיכות טובה יותר לספורט
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
        video_path: Local path to the source video.
        event:      Dict with keys: type, start, end, score, description.
        index:      Clip number (used in output filename).

    Returns:
        Local path to the rendered clip, or None on failure.
    """
    raw_start: float = event["start"]
    raw_end:   float = event["end"]
    event_type: str  = event.get("type", "highlight")

    # אמת timestamps מול אורך הסרטון האמיתי
    start, end = _clamp_timestamps(raw_start, raw_end, video_path)
    if (raw_start, raw_end) != (start, end):
        logger.warning("⚠️ Timestamps clamped: [%.1f,%.1f] → [%.1f,%.1f]", raw_start, raw_end, start, end)

    os.makedirs(config.TMP_DIR, exist_ok=True)

    base_name       = Path(video_path).stem
    output_filename = f"{base_name}_clip{index:02d}_{event_type}.mp4"
    output_path     = os.path.join(config.TMP_DIR, output_filename)

    logo_path = config.LOGO_PATH
    if not Path(logo_path).exists():
        logger.warning("⚠️ Logo not found at %s — cutting without watermark", logo_path)
        print(f"⚠️ Logo missing — clip will have no watermark")
        return _cut_only(video_path, start, end, output_path)

    print(f"🎬 Cutting clip {index}: {start:.1f}s → {end:.1f}s  [{event_type}]  ({end-start:.1f}s)")

    cmd = _build_ffmpeg_cmd(video_path, start, end, logo_path, output_path)
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("❌ FFmpeg error clip %d:\n%s", index, result.stderr[-2000:])
            print(f"❌ FFmpeg failed on clip {index}: {result.stderr[-400:]}")
            return None

        size_mb = os.path.getsize(output_path) / 1_000_000
        print(f"✅ Clip {index} rendered: {output_path}  ({size_mb:.1f} MB)")
        return output_path

    except subprocess.TimeoutExpired:
        logger.error("❌ FFmpeg timed out on clip %d", index)
        print(f"❌ FFmpeg timed out on clip {index}")
        return None
    except FileNotFoundError:
        logger.error("❌ FFmpeg not found")
        print("❌ FFmpeg not found — install with: sudo apt install ffmpeg")
        return None
    except Exception as e:
        logger.error("❌ Unexpected editor error clip %d: %s", index, e)
        print(f"❌ Unexpected error on clip {index}: {e}")
        return None


def _cut_only(video_path: str, start: float, end: float, output_path: str) -> str | None:
    """Fallback: cut with fade but no watermark."""
    duration  = end - start
    fade_dur  = min(0.5, duration / 4)
    fade_vf   = (
        f"fade=t=in:st=0:d={fade_dur:.2f},"
        f"fade=t=out:st={duration - fade_dur:.2f}:d={fade_dur:.2f}"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", fade_vf,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return output_path if result.returncode == 0 else None
    except Exception:
        return None
