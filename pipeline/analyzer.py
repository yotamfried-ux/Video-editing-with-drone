"""
pipeline/analyzer.py — Claude vision-based video analysis.
גישה: scene detection → clustering → Claude על פריימים ממוקדים.
ספורט-אגנוסטי: עובד לכל סוג פעילות.
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import anthropic

import config

logger = logging.getLogger(__name__)
_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ── הגדרות ─────────────────────────────────────────────────────────────────
_SCENE_THRESHOLD = 0.22  # רגישות לשינוי ויזואלי (0-1, נמוך = יותר פריימים)
_MAX_FRAMES      = 24    # מקסימום פריימים שנשלחים ל-Claude
_MIN_GAP_SEC     = 4.0   # מרווח מינימלי בין פריימים נבחרים (שניות)
_MIN_CLIP_SEC    = 6.0   # משך מינימלי לקליפ (Claude מתבקש לשמור על זה)

_ANALYSIS_PROMPT = """
You are a video editor assistant analyzing drone footage. I'm sending you frames extracted at moments of significant visual change. Each frame is labeled with its timestamp in seconds.

Your job — sport/activity agnostic:
1. Identify what activity is being filmed (describe naturally: "surfing", "football", "skateboarding", "parkour", "basketball", "skiing", etc.)
2. Select up to 6 of the most visually exciting or action-packed moments
3. For each moment, use the frame timestamps to estimate start and end time

For each highlight:
- type: short snake_case label for the specific action (e.g. "wave_catch", "goal", "kickflip", "sprint")
- start: estimated start in seconds — go 1-2s BEFORE the key frame so we capture the buildup
- end: estimated end in seconds — at least 6s after start to capture the followthrough
- score: visual excitement 1-10
- description: one sentence describing exactly what is happening

Return ONLY valid JSON, no markdown:
{
  "activity": "surfing",
  "events": [
    {
      "type": "aerial",
      "start": 23.0,
      "end": 31.0,
      "score": 9,
      "description": "Surfer launches off the lip and performs a full aerial rotation."
    }
  ]
}

If you see no clear action highlights, return: {"activity": "unknown", "events": []}
"""


# ── utils ──────────────────────────────────────────────────────────────────

def _get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        return float(subprocess.check_output(cmd, text=True, timeout=30).strip())
    except Exception:
        return 60.0


def _clear_dir(path: str) -> None:
    for f in Path(path).glob("*"):
        try:
            f.unlink()
        except OSError:
            pass


# ── Pass 1: scene detection ────────────────────────────────────────────────

def _extract_scene_frames(video_path: str) -> list[tuple[float, str]]:
    """
    מחלץ פריימים ב-timestamps של שינוי ויזואלי משמעותי.
    משתמש ב-FFmpeg select='gt(scene,threshold)' + showinfo לקבלת timestamps מדויקים.
    מחזיר רשימה של (timestamp_seconds, base64_jpeg).
    """
    frames_dir = os.path.join(config.TMP_DIR, "_frames")
    os.makedirs(frames_dir, exist_ok=True)
    _clear_dir(frames_dir)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", (
            f"select='gt(scene,{_SCENE_THRESHOLD})',"
            f"showinfo,"          # מדפיס pts_time ל-stderr בסדר הפריימים
            f"scale=640:-1"
        ),
        "-vsync", "vfr",
        "-q:v", "4",
        "-frames:v", "64",       # תקרה גבוהה — נסנן אחר-כך
        os.path.join(frames_dir, "scene_%04d.jpg"),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # parse timestamps מ-showinfo בסדר הפריימים
    raw_ts: list[float] = []
    for line in result.stderr.split("\n"):
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            raw_ts.append(float(m.group(1)))

    frame_files = sorted(Path(frames_dir).glob("scene_*.jpg"))
    n = min(len(frame_files), len(raw_ts))

    pairs: list[tuple[float, str]] = []
    for i in range(n):
        try:
            b64 = base64.standard_b64encode(frame_files[i].read_bytes()).decode()
            pairs.append((round(raw_ts[i], 2), b64))
        except OSError:
            continue

    return pairs


# ── Pass 2: clustering ─────────────────────────────────────────────────────

def _cluster(frames: list[tuple[float, str]], min_gap: float = _MIN_GAP_SEC) -> list[tuple[float, str]]:
    """
    מסנן פריימים קרובים מדי.
    שומר רק פריים אחד לכל חלון של min_gap שניות.
    כך אנחנו מקבלים כיסוי שווה לאורך הסרטון ולא ריכוז של פריימים ברגע שינוי אחד.
    """
    if not frames:
        return []
    kept = [frames[0]]
    for ts, b64 in frames[1:]:
        if ts - kept[-1][0] >= min_gap:
            kept.append((ts, b64))
    return kept


# ── Fallback: even sampling ────────────────────────────────────────────────

def _even_frames(video_path: str, n: int = 16) -> list[tuple[float, str]]:
    """
    גיבוי כשscene detection מחזיר פחות מדי פריימים (סרטון סטטי / ערפל).
    דגימה שווה לאורך הסרטון.
    """
    frames_dir = os.path.join(config.TMP_DIR, "_frames")
    os.makedirs(frames_dir, exist_ok=True)
    _clear_dir(frames_dir)

    duration   = _get_video_duration(video_path)
    actual_fps = min(0.5, n / max(duration, 1))
    interval   = 1.0 / actual_fps

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={actual_fps},scale=640:-1",
        "-frames:v", str(n),
        "-q:v", "5",
        os.path.join(frames_dir, "frame_%04d.jpg"),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    frames: list[tuple[float, str]] = []
    for i, f in enumerate(sorted(Path(frames_dir).glob("frame_*.jpg"))):
        try:
            b64 = base64.standard_b64encode(f.read_bytes()).decode()
            frames.append((round(i * interval, 2), b64))
        except OSError:
            continue
    return frames


# ── Main extraction ────────────────────────────────────────────────────────

def _extract_frames(video_path: str) -> list[tuple[float, str]]:
    """
    לוגיקת הבחירה המלאה:
    1. Scene detection
    2. Clustering — מסנן פריימים קרובים
    3. גיבוי לדגימה שווה אם נמצאו פחות מ-5 פריימים
    4. תת-דגימה ל-_MAX_FRAMES אם יש יותר מדי
    """
    duration = _get_video_duration(video_path)
    print(f"🎬 Scene detection on '{Path(video_path).name}' ({duration:.0f}s)...")

    frames = _extract_scene_frames(video_path)
    frames = _cluster(frames, min_gap=_MIN_GAP_SEC)

    if len(frames) < 5:
        # scene detection לא מצא מספיק — מוסיפים דגימה שווה
        print(f"⚠️ Only {len(frames)} scene-change frames — supplementing with even sampling")
        even   = _even_frames(video_path, n=16)
        merged = sorted(frames + even, key=lambda x: x[0])
        frames = _cluster(merged, min_gap=_MIN_GAP_SEC)

    # תת-דגימה שווה אם יותר מ-_MAX_FRAMES
    if len(frames) > _MAX_FRAMES:
        step   = len(frames) / _MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(_MAX_FRAMES)]

    shutil.rmtree(os.path.join(config.TMP_DIR, "_frames"), ignore_errors=True)

    print(f"✅ {len(frames)} action frames selected across {duration:.0f}s")
    return frames


# ── Parse ──────────────────────────────────────────────────────────────────

def _parse_analysis(raw_text: str) -> dict:
    """Parse Claude's JSON response; strips markdown fences if present."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

    # תמיכה ב-"activity" (חדש) וב-"sport" (לגאסי)
    activity = str(data.get("activity") or data.get("sport") or "other").lower()

    if "events" not in data:
        raise ValueError("Response missing 'events'")

    cleaned: list[dict] = []
    for ev in data["events"][:6]:
        start = float(ev.get("start", 0))
        end   = float(ev.get("end", start + 10))
        if end - start < _MIN_CLIP_SEC:
            end = start + _MIN_CLIP_SEC
        cleaned.append({
            "type":        str(ev.get("type", "highlight")),
            "start":       round(start, 2),
            "end":         round(end, 2),
            "score":       int(ev.get("score", 5)),
            "description": str(ev.get("description", "")),
        })

    cleaned.sort(key=lambda x: x["score"], reverse=True)
    return {"activity": activity, "events": cleaned}


# ── Public API ─────────────────────────────────────────────────────────────

def analyze_video(video_path: str) -> dict:
    """
    מנתח סרטון ומחזיר רגעי שיא + סוג פעילות.
    ספורט-אגנוסטי: עובד לכל פעילות.

    Returns:
        {
            "activity": str,   # "surfing", "football", "skateboarding", ...
            "events": [
                {"type": str, "start": float, "end": float,
                 "score": int, "description": str}
            ]
        }
    """
    print(f"🎬 Analyzing: {Path(video_path).name}")

    try:
        frames = _extract_frames(video_path)
        if not frames:
            return {"activity": "unknown", "events": []}

        # בניית הודעה: [timestamp] [תמונה] ... [prompt]
        content: list[dict] = []
        for ts, b64 in frames:
            content.append({"type": "text", "text": f"[{ts}s]"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
        content.append({"type": "text", "text": _ANALYSIS_PROMPT})

        print(f"🎬 Sending {len(frames)} action frames to Claude...")
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )

        result = _parse_analysis(response.content[0].text)
        print(f"✅ Activity: '{result['activity']}' | {len(result['events'])} highlight(s) found")
        return result

    except json.JSONDecodeError as e:
        logger.error("Claude returned non-parseable JSON: %s", e)
        print(f"⚠️ JSON parse error: {e}")
        return {"activity": "unknown", "events": []}

    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        print(f"❌ Claude API error: {e}")
        return {"activity": "unknown", "events": []}

    except Exception as e:
        logger.error("Analysis error: %s", e)
        print(f"❌ Analysis failed: {e}")
        return {"activity": "unknown", "events": []}
