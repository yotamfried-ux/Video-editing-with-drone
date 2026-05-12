"""
pipeline/analyzer.py — Gemini 1.5 Pro video analysis.
שולח את הסרטון ל-Gemini ומקבל חזרה timestamps של רגעי שיא.
"""

import json
import logging
import re
import time

import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)

_MODEL_NAME = "gemini-1.5-pro"

_ANALYSIS_PROMPT = """
You are a sports video editor assistant. Analyze this drone footage and identify the most exciting highlight moments.

Detect the sport type: either "surfing" or "football" (soccer). If neither, use "other".

Find up to 6 highlight moments. For each moment, return:
- type: brief label (e.g. "wave_catch", "aerial", "tube_ride", "goal", "key_play")
- start: start time in seconds (float)
- end: end time in seconds (float, minimum 4 seconds after start)
- score: excitement score 1-10 (integer)
- description: one sentence in English describing the highlight

Respond ONLY with valid JSON in this exact format (no markdown fences, no extra text):
{
  "sport": "surfing",
  "events": [
    {
      "type": "wave_catch",
      "start": 12.5,
      "end": 22.0,
      "score": 8,
      "description": "Surfer drops into a large set wave and executes a powerful bottom turn."
    }
  ]
}
"""


def _upload_to_gemini(video_path: str):
    """Upload video file to Gemini Files API and wait until it is ready."""
    print(f"🎬 Uploading video to Gemini: {video_path}")
    try:
        video_file = genai.upload_file(path=video_path)
        # Gemini file processing can take a moment — poll until ACTIVE
        while video_file.state.name == "PROCESSING":
            print("  ⏳ Gemini processing file...", end="\r")
            time.sleep(3)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file ended in state: {video_file.state.name}")

        print(f"\n✅ Gemini file ready: {video_file.name}")
        return video_file
    except Exception as e:
        logger.error("❌ Gemini file upload failed: %s", e)
        print(f"❌ Gemini file upload failed: {e}")
        raise


def _parse_analysis(raw_text: str) -> dict:
    """
    Parse Gemini's response into a structured dict.
    Handles cases where the model wraps JSON in markdown code fences.
    """
    # Strip markdown fences if present
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

    # Validate minimal structure
    if "sport" not in data or "events" not in data:
        raise ValueError("Response missing required fields 'sport' or 'events'")

    # Clamp and sanitise event fields
    cleaned_events = []
    for ev in data["events"][:6]:  # max 6 events
        start = float(ev.get("start", 0))
        end = float(ev.get("end", start + 10))
        if end - start < 4:
            end = start + 4  # enforce minimum clip length
        cleaned_events.append({
            "type": str(ev.get("type", "highlight")),
            "start": round(start, 2),
            "end": round(end, 2),
            "score": int(ev.get("score", 5)),
            "description": str(ev.get("description", "")),
        })

    # Sort by score descending
    cleaned_events.sort(key=lambda x: x["score"], reverse=True)

    return {
        "sport": str(data.get("sport", "other")).lower(),
        "events": cleaned_events,
    }


def analyze_video(video_path: str) -> dict:
    """
    Upload video to Gemini 1.5 Pro and extract highlight timestamps.

    Returns:
        {
            "sport": "surfing" | "football" | "other",
            "events": [
                {
                    "type": str,
                    "start": float,   # seconds
                    "end": float,     # seconds
                    "score": int,     # 1-10
                    "description": str
                },
                ...
            ]
        }
    Returns {"sport": "unknown", "events": []} on failure.
    """
    print(f"🎬 Analyzing video with Gemini: {video_path}")

    try:
        video_file = _upload_to_gemini(video_path)
        model = genai.GenerativeModel(model_name=_MODEL_NAME)

        print("🎬 Sending to Gemini for highlight detection...")
        response = model.generate_content(
            [video_file, _ANALYSIS_PROMPT],
            request_options={"timeout": 300},  # 5-minute timeout for long videos
        )

        raw_text = response.text
        logger.debug("Gemini raw response: %s", raw_text)

        result = _parse_analysis(raw_text)
        print(f"✅ Gemini detected sport='{result['sport']}', {len(result['events'])} highlight(s)")
        return result

    except json.JSONDecodeError as e:
        logger.error("❌ Failed to parse Gemini JSON response: %s", e)
        print(f"⚠️ Gemini returned non-parseable JSON, skipping video. Error: {e}")
        return {"sport": "unknown", "events": []}

    except Exception as e:
        logger.error("❌ Gemini analysis failed: %s", e)
        print(f"❌ Gemini analysis failed: {e}")
        return {"sport": "unknown", "events": []}
