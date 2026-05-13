"""
pipeline/analyzer.py — Gemini 2.5 Pro native video analysis.
שולח את הסרטון המלא ל-Gemini — לא פריימים, וידאו נייטיב.
Gemini רואה תנועה, רצף, ותזמון — לא תמונות סטטיות.
"""

import json
import logging
import re
import time
from pathlib import Path

import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)

_MODEL        = config.GEMINI_MODEL   # native video understanding
_MIN_CLIP_SEC = 6.0

_ANALYSIS_PROMPT = """
You are a video editor assistant analyzing raw drone footage.
You are watching the FULL video — not frames. Use your understanding of motion, timing, and action sequences.

Your task — completely sport/activity agnostic:
1. Identify what activity is being filmed (describe naturally: "surfing", "football", "skateboarding", "parkour", "skiing", etc.)
2. Find up to 6 of the most exciting, visually impactful action moments
3. Return precise start/end timestamps in seconds

For each highlight:
- type: short snake_case action label (e.g. "wave_catch", "aerial", "goal", "kickflip", "sprint")
- start: exact start in seconds — include 1-2s of buildup before the peak action
- end: exact end in seconds — include followthrough; minimum 6s after start
- score: excitement score 1-10 based on visual intensity and action quality
- description: one sentence describing exactly what happens

Return ONLY valid JSON, no markdown:
{
  "activity": "surfing",
  "events": [
    {
      "type": "aerial",
      "start": 23.5,
      "end": 31.0,
      "score": 9,
      "description": "Surfer launches a full rotation aerial off the lip of a large wave."
    }
  ]
}

If no clear action highlights exist: {"activity": "unknown", "events": []}
"""


def _upload_video(video_path: str):
    """
    מעלה את הסרטון ל-Gemini Files API וממתין עד שהעיבוד הושלם.
    מחזיר את אובייקט הקובץ המוכן לשימוש.
    """
    print(f"📤 Uploading '{Path(video_path).name}' to Gemini Files API...")
    try:
        video_file = genai.upload_file(path=video_path)

        # ממתין עד שהקובץ עבר processing
        while video_file.state.name == "PROCESSING":
            print("  ⏳ Gemini processing video...", end="\r")
            time.sleep(4)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file ended in unexpected state: {video_file.state.name}")

        print(f"\n✅ Video ready in Gemini: {video_file.name}")
        return video_file

    except Exception as e:
        logger.error("Gemini upload failed: %s", e)
        raise


def _delete_video(video_file) -> None:
    """מוחק את הקובץ מ-Gemini Files API אחרי הניתוח לחסוך storage."""
    try:
        genai.delete_file(video_file.name)
        logger.debug("Deleted Gemini file: %s", video_file.name)
    except Exception as e:
        logger.warning("Could not delete Gemini file %s: %s", video_file.name, e)


def _with_retry(fn, attempts: int = 3, base_delay: int = 4):
    """Retry fn() on transient Gemini errors (429 / quota / 503) with exponential back-off."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            transient = any(x in str(e).lower()
                            for x in ["429", "quota", "503", "unavailable", "resource exhausted"])
            if not transient or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))   # 4s, 8s, 16s
            print(f"  ⏳ Gemini error ({attempt}/{attempts}), retry in {delay}s...")
            logger.warning("Gemini transient error, retry %d/%d in %ds: %s", attempt, attempts, delay, e)
            time.sleep(delay)


def _parse_analysis(raw_text: str) -> dict:
    """מנתח את תשובת ה-JSON של Gemini; מסיר markdown fences אם יש."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

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


def analyze_video(video_path: str) -> dict:
    """
    שולח את הסרטון המלא ל-Gemini 2.5 Pro לניתוח נייטיב.
    Gemini רואה תנועה ורצף — לא פריימים.

    Returns:
        {"activity": str, "events": [{"type", "start", "end", "score", "description"}]}
    """
    print(f"🎬 Analyzing '{Path(video_path).name}' with Gemini 2.5 Pro (native video)...")

    video_file = None
    try:
        # 1. העלאה ל-Gemini Files API
        video_file = _with_retry(lambda: _upload_video(video_path))

        # 2. שליחה למודל
        model    = genai.GenerativeModel(model_name=_MODEL)
        print("🎬 Sending to Gemini for highlight detection...")
        response = _with_retry(lambda: model.generate_content(
            [video_file, _ANALYSIS_PROMPT],
            request_options={"timeout": 300},
        ))

        raw_text = response.text
        logger.debug("Gemini raw response: %s", raw_text)

        result = _parse_analysis(raw_text)
        print(f"✅ Activity: '{result['activity']}' | {len(result['events'])} highlight(s) found")
        return result

    except json.JSONDecodeError as e:
        logger.error("Gemini returned non-parseable JSON: %s", e)
        print(f"⚠️ JSON parse error: {e}")
        return {"activity": "unknown", "events": []}

    except Exception as e:
        logger.error("Gemini analysis failed: %s", e)
        print(f"❌ Analysis failed: {e}")
        return {"activity": "unknown", "events": []}

    finally:
        # 3. מחיקת הקובץ מ-Gemini לחסכון ב-storage
        if video_file:
            _delete_video(video_file)
