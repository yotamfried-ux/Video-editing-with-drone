"""
pipeline/analyzer.py — Claude vision-based video analysis.
מחלץ פריימים מהסרטון ושולח ל-Claude לניתוח רגעי שיא במקום Gemini.
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess

import anthropic

import config

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

_ANALYSIS_PROMPT = """
You are a sports video editor assistant. I'm sending you frames extracted from drone footage.
Each frame is labeled with its timestamp in seconds — use these to estimate highlight start/end times.

Detect the sport type: either "surfing" or "football" (soccer). If neither, use "other".

Find up to 6 highlight moments. Each highlight must be at least 4 seconds long.
For each moment return:
- type: brief label (e.g. "wave_catch", "aerial", "tube_ride", "goal", "key_play")
- start: start time in seconds (float) — based on nearest frame timestamp
- end: end time in seconds (float, at least 4s after start)
- score: excitement score 1-10 (integer)
- description: one sentence in English describing the highlight

Respond ONLY with valid JSON (no markdown fences, no extra text):
{
  "sport": "surfing",
  "events": [
    {
      "type": "wave_catch",
      "start": 12.0,
      "end": 22.0,
      "score": 8,
      "description": "Surfer drops into a large set wave and executes a powerful bottom turn."
    }
  ]
}
"""

_MAX_FRAMES = 16   # Claude's vision handles up to ~20 images well
_FRAME_FPS  = 0.5  # default: one frame every 2 seconds


def _get_video_duration(video_path: str) -> float:
    """Use ffprobe to get video duration in seconds."""
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
        return 60.0  # fallback assumption


def _extract_frames(video_path: str) -> list[tuple[float, str]]:
    """
    Extract up to _MAX_FRAMES evenly-spaced JPEG frames from the video.
    Returns list of (timestamp_seconds, base64_jpeg_string).
    """
    frames_dir = os.path.join(config.TMP_DIR, "_frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Clean up any leftover frames from a previous run
    for f in os.listdir(frames_dir):
        try:
            os.remove(os.path.join(frames_dir, f))
        except OSError:
            pass

    duration = _get_video_duration(video_path)
    # Spread _MAX_FRAMES evenly; never exceed _FRAME_FPS
    actual_fps = min(_FRAME_FPS, _MAX_FRAMES / max(duration, 1))
    interval = 1.0 / actual_fps

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps={actual_fps},scale=640:-1",
        "-frames:v", str(_MAX_FRAMES),
        "-q:v", "5",                          # JPEG quality (2=best, 31=worst)
        os.path.join(frames_dir, "frame_%04d.jpg"),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error("FFmpeg frame extraction stderr: %s", result.stderr[-500:])
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg frame extraction timed out")
        return []
    except FileNotFoundError:
        logger.error("FFmpeg not found — install it first")
        print("❌ FFmpeg not found. Please install FFmpeg.")
        return []

    frames: list[tuple[float, str]] = []
    for i, fname in enumerate(sorted(f for f in os.listdir(frames_dir) if f.endswith(".jpg"))):
        ts = round(i * interval, 2)
        fpath = os.path.join(frames_dir, fname)
        try:
            with open(fpath, "rb") as img:
                b64 = base64.standard_b64encode(img.read()).decode()
            frames.append((ts, b64))
        except OSError:
            continue

    shutil.rmtree(frames_dir, ignore_errors=True)

    print(f"🎬 Extracted {len(frames)} frames (1 every {interval:.1f}s) from {os.path.basename(video_path)}")
    return frames


def _parse_analysis(raw_text: str) -> dict:
    """Parse Claude's JSON response; strips markdown fences if present."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

    if "sport" not in data or "events" not in data:
        raise ValueError("Response missing 'sport' or 'events'")

    cleaned: list[dict] = []
    for ev in data["events"][:6]:
        start = float(ev.get("start", 0))
        end   = float(ev.get("end", start + 10))
        if end - start < 4:
            end = start + 4
        cleaned.append({
            "type":        str(ev.get("type", "highlight")),
            "start":       round(start, 2),
            "end":         round(end, 2),
            "score":       int(ev.get("score", 5)),
            "description": str(ev.get("description", "")),
        })

    cleaned.sort(key=lambda x: x["score"], reverse=True)
    return {
        "sport":  str(data.get("sport", "other")).lower(),
        "events": cleaned,
    }


def analyze_video(video_path: str) -> dict:
    """
    Extract frames from the video and send to Claude for highlight detection.

    Returns:
        {
            "sport": "surfing" | "football" | "other",
            "events": [{"type", "start", "end", "score", "description"}, ...]
        }
    Returns {"sport": "unknown", "events": []} on any failure.
    """
    print(f"🎬 Analyzing video with Claude: {video_path}")

    try:
        frames = _extract_frames(video_path)
        if not frames:
            logger.error("No frames extracted from %s", video_path)
            return {"sport": "unknown", "events": []}

        # Build message: [timestamp label] [image] ... [prompt]
        content: list[dict] = []
        for ts, b64 in frames:
            content.append({"type": "text", "text": f"[Frame at {ts}s]"})
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/jpeg",
                    "data":       b64,
                },
            })
        content.append({"type": "text", "text": _ANALYSIS_PROMPT})

        print(f"🎬 Sending {len(frames)} frames to Claude for highlight detection...")
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )

        raw_text = response.content[0].text
        logger.debug("Claude raw response: %s", raw_text)

        result = _parse_analysis(raw_text)
        print(f"✅ Claude detected sport='{result['sport']}', {len(result['events'])} highlight(s)")
        return result

    except json.JSONDecodeError as e:
        logger.error("❌ Claude returned non-parseable JSON: %s", e)
        print(f"⚠️ Claude returned non-parseable JSON, skipping video. Error: {e}")
        return {"sport": "unknown", "events": []}

    except anthropic.APIError as e:
        logger.error("❌ Claude API error: %s", e)
        print(f"❌ Claude API error: {e}")
        return {"sport": "unknown", "events": []}

    except Exception as e:
        logger.error("❌ Unexpected analysis error: %s", e)
        print(f"❌ Analysis failed: {e}")
        return {"sport": "unknown", "events": []}
