"""
pipeline/analyzer.py — Gemini 2.5 Pro native video analysis.
שולח את הסרטון המלא ל-Gemini — לא פריימים, וידאו נייטיב.
Gemini רואה תנועה, רצף, ותזמון — לא תמונות סטטיות.
"""

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)

_MODEL        = config.GEMINI_MODEL   # native video understanding
_MIN_CLIP_SEC = 6.0

_ANALYSIS_PROMPT = """
You are a video editor building a highlight reel from drone sports footage.
You are watching the FULL video — not frames. Use motion, timing, and action sequences.

TASK: Identify the activity and select highlight moments using the scoring guide below.

SCORING — relative to THIS video, not world-class standards:
  9-10 : Best moment(s) in this video — exceptional for this athlete
  7-8  : Above average today — clean skill, good execution
  6-7  : Solid positive performance — worth showing
  1-5  : Routine, mistake, blurry, athlete not in focus — EXCLUDE

SELECTION RULES:
- Include ALL moments with score >= 6
- Always include at least the top 2 moments (safety net)
- Do NOT include score < 6 unless no better moments exist

For each event:
- type: snake_case label (e.g. "wave_catch", "aerial", "goal", "kickflip", "sprint")
- start: exact start in seconds — include 1-2s buildup before peak
- end: exact end in seconds — include followthrough; minimum 6s after start
- score: 1-10 relative to this video
- description: one sentence describing exactly what happens
- crop_x: horizontal position of subject (0.0=left, 0.5=center, 1.0=right)

Return ONLY valid JSON, no markdown:
{
  "activity": "surfing",
  "events": [
    {
      "type": "aerial",
      "start": 23.5,
      "end": 31.0,
      "score": 8,
      "description": "Surfer launches off the lip and lands a full rotation aerial.",
      "crop_x": 0.55
    }
  ]
}

If no action moments exist: {"activity": "unknown", "events": []}
"""


def _upload_video(video_path: str):
    """
    מעלה את הסרטון ל-Gemini Files API וממתין עד שהעיבוד הושלם.
    מחזיר את אובייקט הקובץ המוכן לשימוש.
    """
    print(f"📤 Uploading '{Path(video_path).name}' to Gemini Files API...")
    try:
        video_file = genai.upload_file(path=video_path)

        # Wait for Gemini to finish processing — max ~13 minutes (200 × 4s).
        _MAX_WAIT = 200
        for _attempt in range(_MAX_WAIT):
            if video_file.state.name != "PROCESSING":
                break
            print(f"  ⏳ Gemini processing video... ({_attempt * 4}s)", end="\r")
            time.sleep(4)
            video_file = genai.get_file(video_file.name)
        else:
            raise RuntimeError(
                f"Gemini video processing timed out after {_MAX_WAIT * 4}s"
            )

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


def _extract_thumbnail(video_path: str, timestamp: float) -> str | None:
    """Extract a JPEG frame from video at timestamp using FFmpeg. Returns path or None."""
    stem = Path(video_path).stem
    out_path = os.path.join(config.TMP_DIR, f"thumb_{stem}_{timestamp:.3f}.jpg")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0.0, timestamp)),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "3",
            out_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return out_path if os.path.exists(out_path) else None
    except Exception as e:
        logger.debug("Thumbnail extraction failed at %.1fs: %s", timestamp, e)
        return None


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


_IDENTITY_PROMPT = """
You are a video editor building personal highlight reels for athletes from drone footage.
You are watching the FULL video — not frames. Use motion, timing, and action sequences.

TASK:
1. Identify the sport/activity.
2. Identify each DISTINCT person (surfer, player, athlete) visible in the video.
3. For each person, select their highlight moments using the scoring guide below.

SCORING — relative to THIS video, not world-class standards:
Compare moments against each other within this specific footage.
  9-10 : Best moment(s) in this video — exceptional execution for this athlete
  7-8  : Above average for this athlete today — clean skill, good execution
  6-7  : Solid positive performance — worth showing, athlete looks good
  1-5  : Routine action, mistake, wipeout, blurry shot, athlete not in focus — EXCLUDE

SELECTION RULES:
- Include ALL moments with score >= 6 (they improve the athlete's image)
- Always include at least the top 2 moments per person, even if scores are low
  (every athlete deserves some highlights from their session)
- Do NOT include score < 6 unless no other moments exist
- Prefer variety: avoid 3+ nearly identical consecutive moves

TEAM SPORTS — ATTRIBUTION:
In competitive plays (tackle, duel, block, goal, save, interception):
- Assign the event to the person who SUCCEEDED in the interaction.
  Example: a tackle → assign to the TACKLER (won the ball), score 7-9.
           The player who lost the ball may still have this timestamp listed,
           but score it 1-3 (they were beaten) so it will be excluded.
  Example: a goal → assign to the SCORER (score 8-10).
           The goalkeeper who conceded scores 1-3 for that moment → excluded.
- Separate simultaneous events: if player A scores while player B concedes,
  player A's events list gets the goal (high score), player B's does NOT,
  or it appears with a very low score so it is filtered out.

For each PERSON:
- id: "person_A", "person_B", etc. (most screen time first)
- description: list identifying features in this priority order (be specific — used to match
  the same person across multiple clips):
  1. Jersey/bib number ("player #7", "bib #23") — most reliable, always mention if visible
  2. Clothing colors ("red shirt, black shorts", "blue wetsuit, white gloves")
  3. Equipment ("orange surfboard", "yellow helmet", "red mountain bike")
  4. Hair ("long blonde ponytail", "short dark hair")
  5. Body build only when nothing else distinguishes ("tall, broad shoulders")
  Never use vague labels like "athlete" or "person". Be specific enough to match across clips.

For each EVENT:
- type: snake_case label (e.g. "wave_catch", "goal", "cutback", "trick", "tackle")
- start: exact start in seconds — include 1-2s buildup before the action peak
- end: exact end in seconds — include followthrough; minimum 6s after start
- score: 1-10 relative to this video
- description: one sentence — what specifically happens
- crop_x: horizontal position of subject in frame (0.0=left edge, 0.5=center, 1.0=right edge)

Return ONLY valid JSON, no markdown:
{
  "activity": "surfing",
  "persons": [
    {
      "id": "person_A",
      "description": "surfer with red board and black wetsuit",
      "events": [
        {"type": "wave_catch", "start": 12.0, "end": 21.5, "score": 8,
         "description": "Catches a shoulder-high wave and drives a clean bottom turn.",
         "crop_x": 0.4}
      ]
    }
  ]
}

If only one person is visible, use the persons array with one entry.
If no action moments exist at all: {"activity": "unknown", "persons": []}
"""


def _parse_session(raw_text: str) -> dict:
    """Parse Gemini's multi-person JSON response into structured session data."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data     = json.loads(text)
    activity = str(data.get("activity") or "other").lower()

    persons: list[dict] = []
    for p in data.get("persons", []):
        all_events: list[dict] = []
        for ev in p.get("events", []):
            start  = float(ev.get("start", 0))
            end    = float(ev.get("end", start + 10))
            if end - start < _MIN_CLIP_SEC:
                end = start + _MIN_CLIP_SEC
            crop_x = float(ev.get("crop_x", 0.5))
            crop_x = max(0.0, min(1.0, crop_x))
            all_events.append({
                "type":        str(ev.get("type", "highlight")),
                "start":       round(start, 2),
                "end":         round(end, 2),
                "score":       int(ev.get("score", 5)),
                "description": str(ev.get("description", "")),
                "crop_x":      round(crop_x, 3),
            })

        # Keep only score >= 6 (positive for the athlete's brand).
        # Safety net: always include at least the top 2 so no athlete is left empty.
        good = [ev for ev in all_events if ev["score"] >= 6]
        if not good and all_events:
            good = sorted(all_events, key=lambda x: x["score"], reverse=True)[:2]

        good.sort(key=lambda x: x["score"], reverse=True)
        persons.append({
            "id":          str(p.get("id", "person_?")),
            "description": str(p.get("description", "unknown")),
            "events":      good,
        })

    return {"activity": activity, "persons": persons}


def analyze_session(video_path: str) -> dict:
    """
    Identifies distinct persons and their highlight moments via Gemini.
    Used for multi-person sessions (full games, surf sessions, etc.).

    Returns:
        {"activity": str, "persons": [{"id", "description", "events": [...]}]}
    """
    print(f"🔍 Analyzing '{Path(video_path).name}' — multi-person session mode...")

    video_file = None
    try:
        video_file = _with_retry(lambda: _upload_video(video_path))

        model    = genai.GenerativeModel(model_name=_MODEL)
        print("🔍 Sending to Gemini for identity + highlight detection...")
        response = _with_retry(lambda: model.generate_content(
            [video_file, _IDENTITY_PROMPT],
            request_options={"timeout": 300},
        ))

        result = _parse_session(response.text)
        n      = len(result["persons"])
        print(f"✅ Activity: '{result['activity']}' | {n} person(s) identified")

        # Extract reference thumbnail for each person's best event (for visual Re-ID).
        for person in result.get("persons", []):
            events = person.get("events", [])
            if events:
                best = events[0]  # sorted by score desc in _parse_session
                mid = (best["start"] + best["end"]) / 2
                thumb = _extract_thumbnail(video_path, mid)
                if thumb:
                    person["thumbnail"] = thumb

        return result

    except json.JSONDecodeError as e:
        # Gemini returned something but we couldn't parse it — treat as no persons found.
        # (A retry would likely give the same bad JSON, so don't re-raise.)
        logger.error("Gemini session JSON parse error: %s", e)
        print(f"⚠️ JSON parse error from Gemini: {e}")
        return {"activity": "unknown", "persons": []}

    except Exception as e:
        # API / network / timeout failure — re-raise so the caller can skip this
        # video without marking it as processed, allowing a retry next run.
        logger.error("Gemini session analysis failed: %s", e)
        print(f"❌ Session analysis failed: {e}")
        raise

    finally:
        if video_file:
            _delete_video(video_file)


def _parse_analysis(raw_text: str) -> dict:
    """מנתח את תשובת ה-JSON של Gemini; מסיר markdown fences אם יש."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

    activity = str(data.get("activity") or data.get("sport") or "other").lower()

    if "events" not in data:
        raise ValueError("Response missing 'events'")

    all_events: list[dict] = []
    for ev in data["events"]:
        start  = float(ev.get("start", 0))
        end    = float(ev.get("end", start + 10))
        if end - start < _MIN_CLIP_SEC:
            end = start + _MIN_CLIP_SEC
        crop_x = max(0.0, min(1.0, float(ev.get("crop_x", 0.5))))
        all_events.append({
            "type":        str(ev.get("type", "highlight")),
            "start":       round(start, 2),
            "end":         round(end, 2),
            "score":       int(ev.get("score", 5)),
            "description": str(ev.get("description", "")),
            "crop_x":      round(crop_x, 3),
        })

    # Keep only score >= 6; safety net: top 2 if none qualify.
    good = [ev for ev in all_events if ev["score"] >= 6]
    if not good and all_events:
        good = sorted(all_events, key=lambda x: x["score"], reverse=True)[:2]
    good.sort(key=lambda x: x["score"], reverse=True)
    return {"activity": activity, "events": good}
