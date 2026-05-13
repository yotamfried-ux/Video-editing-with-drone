"""
pipeline/editor.py — FFmpeg reel compilation pipeline.
חותך קליפים ל-9:16, מוסיף color grade, ומחבר לריל אחד עם crossfade.
האתלט בוחר מוזיקה ומעלה ישיר לרשתות.
"""

import logging
import os
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# ── פורמט תוצאה: 9:16 לאינסטגרם Reels / TikTok ───────────────────────────
REEL_W, REEL_H = 1080, 1920
XFADE_DUR      = 0.4   # חפיפה בין קליפים (שניות)
CLIP_FADE_DUR  = 0.25  # fade in/out בתוך כל קליפ
MAX_REEL_SEC   = 88    # בטיחות: מתחת ל-90s של Instagram Reels


# ── ffprobe helpers ────────────────────────────────────────────────────────

def _get_duration(path: str) -> float:
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


def _clamp(start: float, end: float, video_path: str) -> tuple[float, float]:
    """Clamp timestamps so they don't exceed actual video length."""
    total = _get_duration(video_path)
    start = max(0.0, min(start, total - 4))
    end   = min(end, total)
    if end - start < 4:
        end = min(start + 4, total)
    return round(start, 2), round(end, 2)


# ── שלב 1: חיתוך קליפ בודד ────────────────────────────────────────────────

def cut_clip(video_path: str, event: dict, index: int) -> str | None:
    """
    חותך רגע שיא אחד ומעבד אותו:
    - חיתוך לפי timestamps
    - המרה ל-9:16 (רקע מטושטש + תמונה חדה במרכז)
    - color grade: contrast / saturation / sharpening
    - fade in + fade out קצר
    - ללא אודיו (האתלט מוסיף מוזיקה בעצמו)
    """
    start, end = _clamp(event["start"], event["end"], video_path)
    duration   = end - start
    event_type = event.get("type", "highlight")
    clip_fade  = min(CLIP_FADE_DUR, duration / 6)

    os.makedirs(config.TMP_DIR, exist_ok=True)
    out = os.path.join(config.TMP_DIR, f"{Path(video_path).stem}_clip{index:02d}.mp4")

    if (event["start"], event["end"]) != (start, end):
        logger.warning("⚠️ Timestamps clamped [%.1f,%.1f]→[%.1f,%.1f]",
                       event["start"], event["end"], start, end)

    # split → רקע מטושטש (fill) + תמונה חדה (fit) → overlay → grade → fade
    vf = (
        f"[0:v]split[bg_in][fg_in];"

        # רקע: מגדיל עד שממלא 9:16, חותך, מטשטש
        f"[bg_in]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{REEL_H},boxblur=28:5[bg];"

        # תמונה: מכווץ עד שנכנס בתוך 9:16 (ללא חיתוך)
        f"[fg_in]scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease[fg];"

        # חיבור: תמונה על רקע מטושטש
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"

        # color grade: מעט contrast, saturation, חידוד קל
        f"eq=contrast=1.08:saturation=1.18:brightness=0.01,"
        f"unsharp=5:5:0.35,"

        # fade in + fade out
        f"fade=t=in:st=0:d={clip_fade:.2f},"
        f"fade=t=out:st={duration - clip_fade:.2f}:d={clip_fade:.2f}"

        f"[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-filter_complex", vf,
        "-map", "[out]",
        "-an",                         # ללא אודיו
        "-c:v", "libx264",
        "-crf", "20",
        "-preset", "fast",
        "-r", "30",                    # normalize fps
        "-movflags", "+faststart",
        out,
    ]

    print(f"🎬 Clip {index}: {start:.1f}s → {end:.1f}s  [{event_type}]  ({duration:.1f}s)")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logger.error("FFmpeg clip %d: %s", index, r.stderr[-1500:])
            print(f"❌ Clip {index} failed: {r.stderr[-300:]}")
            return None
        return out
    except subprocess.TimeoutExpired:
        print(f"❌ Clip {index} timed out")
        return None
    except FileNotFoundError:
        print("❌ FFmpeg not found — install: sudo apt install ffmpeg")
        return None
    except Exception as e:
        logger.error("Clip %d unexpected: %s", index, e)
        return None


# ── שלב 2: compilation לריל אחד ──────────────────────────────────────────

def _xfade_filter(n: int, durations: list[float]) -> str:
    """
    בונה filter_complex ל-xfade בין n קליפים.
    offset לכל xfade = סכום משכי הקליפים הקודמים פחות מספר המעברים כפול XFADE_DUR.
    """
    if n == 1:
        return "[0:v]null[xfout]"

    parts   = []
    offset  = round(durations[0] - XFADE_DUR, 3)
    out_lbl = "[xfout]" if n == 2 else "[xf1]"
    parts.append(
        f"[0:v][1:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}{out_lbl}"
    )

    cumulative = durations[0] + durations[1] - XFADE_DUR
    for i in range(2, n):
        offset  = round(cumulative - XFADE_DUR, 3)
        prev    = "[xf1]" if i == 2 else f"[xf{i-1}]"
        out_lbl = "[xfout]" if i == n - 1 else f"[xf{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}{out_lbl}"
        )
        cumulative += durations[i] - XFADE_DUR

    return ";".join(parts)


def compile_reel(clip_paths: list[str], logo_path: str, output_path: str) -> str | None:
    """
    מחבר את כל הקליפים לריל אחד עם:
    - crossfade transitions בין קליפים
    - לוגו watermark בפינה ימין-תחתון
    - export ב-H.264 ב-CRF 18 (איכות גבוהה לרשתות)
    """
    n = len(clip_paths)
    if n == 0:
        return None

    durations   = [_get_duration(p) for p in clip_paths]
    total_dur   = sum(durations) - XFADE_DUR * (n - 1)

    if total_dur > MAX_REEL_SEC:
        logger.warning("⚠️ Reel %.0fs exceeds Instagram 90s limit", total_dur)
        print(f"⚠️ Reel {total_dur:.0f}s — longer than Instagram 90s limit")

    # בניית inputs: קליפים + לוגו (אופציונלי)
    inputs     = []
    for p in clip_paths:
        inputs += ["-i", p]

    has_logo  = logo_path and Path(logo_path).exists()
    logo_idx  = n
    if has_logo:
        inputs += ["-i", logo_path]

    # xfade filter chain
    xfade_f = _xfade_filter(n, durations)

    if has_logo:
        # לוגו: ~8% מרוחב הריל (1080/13 ≈ 83px), 85% opacity
        logo_w = REEL_W // 13
        logo_f = (
            f"[{logo_idx}:v]scale={logo_w}:-1,format=rgba,"
            f"colorchannelmixer=aa=0.85[logo];"
            f"[xfout][logo]overlay=W-w-20:H-h-20[final]"
        )
        filter_complex = xfade_f + ";" + logo_f
        map_out = "[final]"
    else:
        filter_complex = xfade_f
        map_out = "[xfout]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", map_out,
        "-an",
        "-c:v", "libx264",
        "-crf", "18",              # איכות גבוהה לתוצאה הסופית
        "-preset", "fast",
        "-r", "30",
        "-movflags", "+faststart",
        output_path,
    ]

    print(f"🎬 Compiling reel: {n} clip(s), {total_dur:.0f}s total → {Path(output_path).name}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            logger.error("Reel compile error: %s", r.stderr[-2000:])
            print(f"❌ Reel compilation failed: {r.stderr[-400:]}")
            return None

        size_mb = os.path.getsize(output_path) / 1_000_000
        print(f"✅ Reel ready: {output_path}  ({size_mb:.1f} MB, {total_dur:.0f}s)")
        return output_path

    except subprocess.TimeoutExpired:
        print("❌ Reel compilation timed out")
        return None
    except Exception as e:
        logger.error("Reel compile unexpected: %s", e)
        return None


# ── ממשק ראשי ─────────────────────────────────────────────────────────────

def create_reel(video_path: str, events: list[dict], sport: str = "") -> str | None:
    """
    הכניסה הראשית: מקבל סרטון גולמי + events מ-Claude,
    מחזיר path לריל מוכן להעלאה.
    """
    print(f"\n🎬 Creating reel from '{Path(video_path).name}' ({len(events)} event(s))")

    # שלב 1: חיתוך קליפים בודדים
    clip_paths = []
    for i, event in enumerate(events, start=1):
        clip = cut_clip(video_path, event, i)
        if clip:
            clip_paths.append(clip)
        else:
            print(f"⚠️ Event {i} skipped")

    if not clip_paths:
        print("❌ No clips produced — cannot create reel")
        return None

    # שלב 2: compilation לריל אחד
    sport_tag = f"_{sport}" if sport else ""
    reel_name = f"REEL_{Path(video_path).stem}{sport_tag}.mp4"
    reel_path = os.path.join(config.TMP_DIR, reel_name)
    reel      = compile_reel(clip_paths, config.LOGO_PATH, reel_path)

    # ניקוי קליפים זמניים
    for p in clip_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    return reel
