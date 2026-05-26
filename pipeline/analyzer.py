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

_MODEL             = config.GEMINI_MODEL   # native video understanding
_MIN_CLIP_SEC      = 6.0
_CHUNK_MAX_MINUTES = 8   # Gemini ~1M token limit ≈ 8 min of drone footage @1fps


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


def _chunk_video(video_path: str, max_minutes: int = _CHUNK_MAX_MINUTES) -> list[str]:
    """Split video into ≤max_minutes segments using FFmpeg stream copy.
    Returns [video_path] unchanged when duration fits in one chunk.
    """
    import math
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True, timeout=30, check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    seg_secs = max_minutes * 60
    n_chunks = math.ceil(duration / seg_secs)
    if n_chunks <= 1:
        return [video_path]

    stem = Path(video_path).stem
    os.makedirs(config.TMP_DIR, exist_ok=True)
    chunks: list[str] = []
    print(f"✂️  Splitting '{stem}' into {n_chunks} chunks ({max_minutes}min each)...")
    for i in range(n_chunks):
        out = os.path.join(config.TMP_DIR, f"{stem}_chunk{i:02d}.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(i * seg_secs),
            "-i", video_path,
            "-t", str(seg_secs),
            "-c", "copy",
            out,
        ], capture_output=True, timeout=120, check=True)
        chunks.append(out)
    logger.info("Chunked '%s' → %d segments", stem, n_chunks)
    return chunks


def _merge_session_results(chunk_results: list[dict], seg_secs: float) -> dict:
    """Merge per-chunk analysis dicts: shift timestamps, pick dominant activity,
    merge persons by description, de-duplicate events within ±5 s."""
    from collections import Counter

    acts = [r.get("activity", "unknown") for r in chunk_results
            if r.get("activity") not in ("unknown", "other", "")]
    activity = Counter(acts).most_common(1)[0][0] if acts else "sport"

    raw_persons: list[dict] = []
    for chunk_i, result in enumerate(chunk_results):
        offset = chunk_i * seg_secs
        for person in result.get("persons", []):
            shifted_events = [
                {**ev, "start": round(ev["start"] + offset, 2),
                        "end":   round(ev["end"]   + offset, 2)}
                for ev in person.get("events", [])
            ]
            raw_persons.append({**person, "events": shifted_events})

    # Merge by description key (first 40 chars, lowercase)
    merged: dict[str, dict] = {}
    for p in raw_persons:
        key = p["description"].lower()[:40]
        if key not in merged:
            merged[key] = {**p}
        else:
            existing_starts = {ev["start"] for ev in merged[key]["events"]}
            for ev in p["events"]:
                if not any(abs(ev["start"] - es) < 5.0 for es in existing_starts):
                    merged[key]["events"].append(ev)
                    existing_starts.add(ev["start"])
            if not merged[key].get("thumbnail") and p.get("thumbnail"):
                merged[key]["thumbnail"] = p["thumbnail"]

    # Collect style/session_peak from chunks
    styles = [r.get("style") for r in chunk_results if r.get("style")]
    session_peak = max((r.get("session_peak", 0) for r in chunk_results), default=0)
    merged_style = styles[0] if styles else {}

    return {
        "activity":     activity,
        "persons":      list(merged.values()),
        "style":        merged_style,
        "session_peak": session_peak,
    }


_QA_PROMPT = (
    "Is the main athlete clearly visible and in-frame in this thumbnail? "
    "Answer only: PASS or FAIL. "
    "FAIL only if the athlete is mostly cut off at the frame edge, completely out of frame, "
    "or too blurry to recognize."
)


def _qa_check_clip(clip_path: str, event: dict) -> bool:
    """Return True if QA passes (athlete in frame), False on FAIL.
    Always returns True on error so a network blip never drops a clip.
    """
    duration = event.get("end", 0) - event.get("start", 0)
    thumb = _extract_thumbnail(clip_path, max(0.5, duration / 2))
    if not thumb:
        return True
    try:
        img_file = genai.upload_file(path=thumb, mime_type="image/jpeg")
        model    = genai.GenerativeModel(model_name=_MODEL)
        resp     = _with_retry(lambda: model.generate_content(
            [img_file, _QA_PROMPT],
            request_options={"timeout": 30},
        ))
        try:
            genai.delete_file(img_file.name)
        except Exception:
            pass
        return "FAIL" not in resp.text.upper()
    except Exception as _e:
        logger.debug("QA check error (assuming pass): %s", _e)
        return True
    finally:
        try:
            os.remove(thumb)
        except OSError:
            pass


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

GLOBAL RANKING CONTEXT:
- Use the FULL 1-10 scale. Do not cluster all scores near 7.
- At least one event in the video MUST receive 9 or 10 if any standout action occurred.
- session_peak: report the highest score you assigned to any single event in this session.
  This helps the editor treat a score-8 in a peak-8 session as top-tier (not middle-tier).

SESSION STYLE — observe the overall footage character and report at the top level:
  visual:  "bright" (high exposure, vibrant colors) | "dark" (low light, muted) | "mixed"
  pace:    "fast" (new action every 2-5s) | "moderate" (moves every 5-12s) | "slow" (long sustained action)
  density: "high" (mostly action, few quiet moments) | "low" (long gaps between highlights)
These guide the editor's music tempo, cut rhythm, and color treatment.

SELECTION RULES:
- Include ALL moments with score >= 6 (they improve the athlete's image)
- Always include at least the top 2 moments per person, even if scores are low
  (every athlete deserves some highlights from their session)
- Do NOT include score < 6 unless no other moments exist
- Prefer variety: avoid 3+ nearly identical consecutive moves

EVENT COUNT: Aim for 3-8 events per person. Prefer quality over quantity — a 4-event reel
with scores 8,9,8,7 is better than a 10-event reel with four score-6 moments padded in.
Fewer than 2 events per person is only acceptable when the session is very short.

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
- type: choose the closest value from this list (do NOT invent new labels):
    Aerial/trick:  aerial, trick, flip, gap_jump, kicker
    Wave/water:    tube_ride, barrel, wave_catch, cutback, bottom_turn, carve, snap, paddle
    Ball sports:   goal, tackle, assist, interception, save, dribble, header, shot, clearance
    Bike/skate:    jump, landing, grind, manual, crash
    General:       sprint, approach, wipeout, near_miss, highlight
    (use "highlight" only when nothing else fits)
- start: exact start in seconds — include 1-2s buildup before the action peak
- end: exact end in seconds — include followthrough; minimum 6s after start
- score: 1-10 relative to this video
- description: one sentence — what specifically happens
- crop_x: horizontal position of athlete's center in frame (0.0=far left, 0.5=center, 1.0=far right)
    Observe where the athlete actually is — do not default to 0.5 unless they are truly centered.
- crop_y: vertical position of athlete's center of mass (0.0=top of frame, 0.5=center, 1.0=bottom)
    Drone/aerial footage: the athlete is rarely vertically centered. Observe carefully.
    Ground-level sports (surfing, skating, football): athlete typically 0.60–0.85 (lower third)
    Jump or aerial apex (athlete is rising/falling through air): typically 0.30–0.55
    Default when genuinely uncertain: 0.65
- edit: per-event editing instructions based on what you OBSERVE in the frame:
    zoom: 1.0–2.0 — observe the athlete's actual size in the frame:
      Athlete fills < 30% of frame height (drone is high, athlete looks tiny) → zoom 1.5–2.0
      Athlete fills 30–60% of frame height (typical drone distance) → zoom 1.2–1.5
      Athlete fills > 60% of frame height (drone is close) → zoom 1.0–1.2
      Judge from what you actually see — NOT from event type alone.
    slowmo: true/false — observe the action rhythm:
      Does this moment have a clear PEAK with distinct before and after?
        Yes (jump apex, trick peak, ball contact, wave launch off lip) → true
        No (fluid paddling, continuous running, wide group play) → false
      Ask: does slowing this down 2× make it more dramatic, or just make it drag?
    focus: "peak" | "entry" | "full" — when to apply zoom during the clip:
      "peak"  — zoom ramps in at the action peak (default). Use when the clip opens with
                wide context and only the apex needs tight framing (most tricks, aerials).
      "entry" — zoom from the very first frame. Use when the action is already in progress
                at clip start (no wide buildup needed — e.g. drone already tight on surfer,
                skater already mid-trick when clip begins).
      "full"  — zoom throughout. Use for continuous movement where the athlete is always
                the clear subject with no context needed (lone cyclist on trail, solo
                surfing carve with no other athletes nearby).
    transition_out: how to cut away from this clip to the next (default "slide"):
      "cut"   — near-instant cut; use after high-impact peak moments (trick landing,
                goal, tackle) where abruptness adds punch
      "fade"  — soft cross-fade; use after calm or flowing moments (wide paddle,
                gliding, establishing shots) where a hard cut would feel jarring
      "slide" — slide transition; general purpose, works for most moments
      "zoom"  — zoom-in transition; use before the reel's climax clip to build intensity

Return ONLY valid JSON, no markdown:
{
  "activity": "surfing",
  "session_peak": 9,
  "style": {"visual": "bright", "pace": "moderate", "density": "high"},
  "persons": [
    {
      "id": "person_A",
      "description": "surfer with red board and black wetsuit",
      "events": [
        {"type": "aerial", "start": 12.0, "end": 21.5, "score": 9,
         "description": "Launches off the lip into a full rotation above the wave.",
         "crop_x": 0.4, "crop_y": 0.35,
         "edit": {"zoom": 1.4, "slowmo": true, "focus": "peak", "transition_out": "fade"}},
        {"type": "wave_catch", "start": 35.0, "end": 44.0, "score": 7,
         "description": "Catches a shoulder-high wave and paddles into position.",
         "crop_x": 0.55, "crop_y": 0.72,
         "edit": {"zoom": 1.1, "slowmo": false, "focus": "full", "transition_out": "slide"}}
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

    # Extract session-level style and peak score
    raw_style = data.get("style") or {}
    if not isinstance(raw_style, dict):
        raw_style = {}
    visual  = raw_style.get("visual", "mixed")
    pace    = raw_style.get("pace", "moderate")
    density = raw_style.get("density", "high")
    style = {
        "visual":  visual  if visual  in ("bright", "dark", "mixed")       else "mixed",
        "pace":    pace    if pace    in ("fast", "moderate", "slow")       else "moderate",
        "density": density if density in ("high", "low")                   else "high",
    }
    try:
        session_peak = max(0, int(data.get("session_peak", 0)))
    except (TypeError, ValueError):
        session_peak = 0

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
            crop_y = float(ev.get("crop_y", 0.65))
            crop_y = max(0.0, min(1.0, crop_y))
            raw_edit = ev.get("edit") or {}
            transition_out = str(raw_edit.get("transition_out", "slide")).lower()
            if transition_out not in ("cut", "fade", "slide", "zoom"):
                transition_out = "slide"
            edit = {
                "zoom":           max(1.0, min(2.0, float(raw_edit.get("zoom", 1.0)))),
                "slowmo":         bool(raw_edit.get("slowmo", False)),
                "focus":          str(raw_edit.get("focus", "peak")),
                "transition_out": transition_out,
            }
            all_events.append({
                "type":        str(ev.get("type", "highlight")),
                "start":       round(start, 2),
                "end":         round(end, 2),
                "score":       int(ev.get("score", 5)),
                "description": str(ev.get("description", "")),
                "crop_x":      round(crop_x, 3),
                "crop_y":      round(crop_y, 3),
                "edit":        edit,
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

    return {"activity": activity, "persons": persons, "style": style, "session_peak": session_peak}


def analyze_session(video_path: str) -> dict:
    """
    Identifies distinct persons and their highlight moments via Gemini.
    Long videos (> _CHUNK_MAX_MINUTES) are split into chunks first to stay
    within Gemini's 1M-token context window. Results are merged automatically.

    Returns:
        {"activity": str, "persons": [...], "style": {...}, "session_peak": int}
    """
    print(f"🔍 Analyzing '{Path(video_path).name}' — multi-person session mode...")

    # Build prompt once — prepend feedback so JSON example stays as format anchor at end
    from pipeline.feedback import get_all_label_injections
    feedback_block = get_all_label_injections()
    prompt = feedback_block + _IDENTITY_PROMPT if feedback_block else _IDENTITY_PROMPT
    if feedback_block:
        sport_count = feedback_block.count("\n  ")
        logger.info("Injecting editing feedback for %d sport(s) into prompt", sport_count)
        print(f"🏷️  Injecting editing history ({sport_count} sport(s)) into analysis prompt")

    # Split long videos into chunks
    try:
        chunks = _chunk_video(video_path)
    except Exception as _ce:
        logger.warning("Chunking failed (%s) — analyzing full video", _ce)
        chunks = [video_path]
    is_chunked = len(chunks) > 1

    def _analyze_one(chunk_path: str) -> dict:
        """Upload one file, analyze with Gemini, delete. JSON errors → empty result."""
        vf = None
        try:
            vf = _with_retry(lambda: _upload_video(chunk_path))
            model = genai.GenerativeModel(model_name=_MODEL)
            resp  = _with_retry(lambda: model.generate_content(
                [vf, prompt],
                request_options={"timeout": 300},
            ))
            return _parse_session(resp.text)
        except json.JSONDecodeError as e:
            logger.error("Gemini JSON parse error: %s", e)
            print(f"⚠️ JSON parse error from Gemini: {e}")
            return {"activity": "unknown", "persons": [], "style": {}, "session_peak": 0}
        finally:
            if vf:
                _delete_video(vf)

    try:
        if not is_chunked:
            result = _analyze_one(video_path)
            n = len(result["persons"])
            print(f"✅ Activity: '{result['activity']}' | {n} person(s) identified")
        else:
            chunk_results = []
            for i, chunk_path in enumerate(chunks):
                print(f"🔍 Analyzing chunk {i + 1}/{len(chunks)}...")
                chunk_results.append(_analyze_one(chunk_path))
            result = _merge_session_results(chunk_results, _CHUNK_MAX_MINUTES * 60)
            n = len(result["persons"])
            print(f"✅ Activity: '{result['activity']}' | {n} person(s) from {len(chunks)} chunks")

        # Reference thumbnail per person's best event (always from original video)
        for person in result.get("persons", []):
            events = person.get("events", [])
            if events:
                best = events[0]  # sorted by score desc in _parse_session
                mid  = (best["start"] + best["end"]) / 2
                thumb = _extract_thumbnail(video_path, mid)
                if thumb:
                    person["thumbnail"] = thumb

        return result

    except Exception as e:
        logger.error("Gemini session analysis failed: %s", e)
        print(f"❌ Session analysis failed: {e}")
        raise

    finally:
        if is_chunked:
            for chunk_path in chunks:
                if chunk_path != video_path:
                    try:
                        os.remove(chunk_path)
                    except OSError:
                        pass


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
        crop_y = max(0.0, min(1.0, float(ev.get("crop_y", 0.65))))
        raw_edit = ev.get("edit") or {}
        transition_out = str(raw_edit.get("transition_out", "slide")).lower()
        if transition_out not in ("cut", "fade", "slide", "zoom"):
            transition_out = "slide"
        all_events.append({
            "type":        str(ev.get("type", "highlight")),
            "start":       round(start, 2),
            "end":         round(end, 2),
            "score":       int(ev.get("score", 5)),
            "description": str(ev.get("description", "")),
            "crop_x":      round(crop_x, 3),
            "crop_y":      round(crop_y, 3),
            "edit": {
                "zoom":           max(1.0, min(2.0, float(raw_edit.get("zoom", 1.0)))),
                "slowmo":         bool(raw_edit.get("slowmo", False)),
                "focus":          str(raw_edit.get("focus", "full")),
                "transition_out": transition_out,
            },
        })

    # Keep only score >= 6; safety net: top 2 if none qualify.
    good = [ev for ev in all_events if ev["score"] >= 6]
    if not good and all_events:
        good = sorted(all_events, key=lambda x: x["score"], reverse=True)[:2]
    good.sort(key=lambda x: x["score"], reverse=True)
    return {"activity": activity, "events": good}
