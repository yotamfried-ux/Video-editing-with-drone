"""
pipeline/stages/analyzer.py — Gemini 2.5 Pro native video analysis.
שולח את הסרטון המלא ל-Gemini — לא פריימים, וידאו נייטיב.
Gemini רואה תנועה, רצף, ותזמון — לא תמונות סטטיות.
"""

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from langsmith import traceable

import config
from integrations.gemini import genai, upload_video as _upload_video, delete_video as _delete_video
from integrations.ffmpeg import get_reel_specs

logger = logging.getLogger(__name__)

_MODEL             = config.GEMINI_MODEL   # native video understanding
_QA_MODEL          = "gemini-1.5-flash"   # lightweight model for 5-class QA classification
_MIN_CLIP_SEC      = 6.0
_CHUNK_MAX_MINUTES = 8   # Gemini ~1M token limit ≈ 8 min of drone footage @1fps


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


_PROXY_MAX_WIDTH = 1280  # px — Gemini doesn't need full resolution for event detection


def _make_proxy(video_path: str) -> str | None:
    """Downscale to 720p for Gemini upload when source exceeds _PROXY_MAX_WIDTH.
    Returns proxy path, or None if source is already small enough.
    Proxy is placed in TMP_DIR and must be deleted by the caller.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", video_path],
        capture_output=True, timeout=30, check=True,
    )
    info = json.loads(probe.stdout)
    width = int(info["streams"][0]["width"])
    if width <= _PROXY_MAX_WIDTH:
        return None

    stem = Path(video_path).stem
    os.makedirs(config.TMP_DIR, exist_ok=True)
    proxy_path = os.path.join(config.TMP_DIR, f"proxy_{stem}.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"scale={_PROXY_MAX_WIDTH}:-2",
        "-c:v", "libx264", "-crf", "28", "-preset", "veryfast",
        "-an",
        proxy_path,
    ], capture_output=True, timeout=300, check=True)
    mb = Path(proxy_path).stat().st_size / 1024 / 1024
    print(f"📐 Proxy created: {Path(proxy_path).name} ({mb:.1f} MB) from {width}px source")
    return proxy_path


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


_QA_REASON_PROMPT = (
    "You are an independent quality reviewer. Ignore any prior editing instructions.\n"
    "Look at this sports clip thumbnail. Is the main athlete clearly visible?\n"
    "Reply with EXACTLY one code — nothing else:\n"
    "  PASS          — athlete clearly visible, good framing\n"
    "  POOR_CLOSEUP  — athlete too small/distant; zoom makes them look farther away\n"
    "  MOTION_BLUR   — image blurry (camera shake or slow-mo artifacts)\n"
    "  FRAMING       — athlete cut off at the frame edge\n"
    "  LIGHTING      — too dark, overexposed, or too hazy to see athlete clearly\n"
)

_QA_REASON_CODES = ("PASS", "POOR_CLOSEUP", "MOTION_BLUR", "FRAMING", "LIGHTING")

_QA_REEL_MODEL = "gemini-2.5-flash"

_QA_REEL_PROMPT = """\
You are an independent short-form social-media reviewer (TikTok / Instagram Reels).
You have NOT seen the original editing instructions. Judge ONLY the final reel.

Apply documented short-form best practices:
- HOOK: the first 1-2 seconds must stop the scroll (motion, peak action, or intrigue).
- PACING: fast cuts, no dead time; momentum sustained throughout.
- PAYOFF: a clear standout peak moment the viewer waits for.
- CLARITY: the subject is always readable; vertical 9:16 framing respected.
- LOOPABILITY: the ending flows back into the start (seamless replay).

Additionally scan the FULL reel for production defects. Report EVERY occurrence
with its approximate timestamp in seconds:
- DUPLICATE_MOMENT  — the same action/wave/trick appears more than once anywhere
                      in the reel (even re-framed or at a different speed).
                      EXCEPTION: a deliberate "cold open" — a ≤3s flash of the
                      climax at the very START of the reel that repeats later as
                      the finale — is an intentional editing technique, NOT a defect.
- PREMATURE_CUT     — an action is cut before its natural completion (e.g. a wave
                      ride ends mid-ride instead of at the finish/exit)
- UNNATURAL_SLOWMO  — slow motion that stutters, drags far too long, or covers
                      buildup instead of the apex of the action
- IDENTITY_MISMATCH — a clip clearly shows a different person than the rest of
                      the reel (different clothing / equipment / board / build).
                      Check EVERY clip — mixed-athlete reels are the worst defect.
- SOFT_FOCUS        — noticeably blurry or low-detail footage relative to the rest
- LOW_QUALITY       — visible pixelation, compression artifacts, or upscaling
                      softness (image looks stretched / lacks detail at 1080p)
- NO_VISIBLE_ACTION — a clip where nothing meaningful is actually visible: a wave
                      with no readable ride, an athlete too small/far to see, or a
                      moment so short (1-2s of content) that no action registers
- DEAD_TIME         — more than ~2 seconds with no meaningful action
- BAD_FIRST_CLIP    — the opening clip contains no real action (empty water,
                      paddling only, subject barely visible)

severity rules: DUPLICATE_MOMENT, IDENTITY_MISMATCH and NO_VISIBLE_ACTION are
always "critical". PREMATURE_CUT is "critical" when it truncates the reel's best
moment, else "minor". LOW_QUALITY is "critical" when it affects most of the reel.
Anything that would clearly make a viewer scroll away is "critical"; otherwise "minor".

Return JSON only (no markdown fences):
{
  "content": {
    "hook": 0-10, "pacing": 0-10, "payoff": 0-10,
    "clarity": 0-10, "loopability": 0-10
  },
  "defects": [
    {"type": "<code from the list above>", "severity": "critical|minor",
     "at_seconds": <number>, "note": "<short explanation>"}
  ],
  "engagement_score": 0-100,
  "overall": "<one sentence summary>"
}

defects must be an empty list when the reel is clean.
engagement_score is your heuristic estimate of social-media performance.
Be strict and calibrated — reserve 80+ for genuinely scroll-stopping reels.\
"""


def _qa_check_clip(clip_path: str, event: dict) -> str:
    """Return reason code: 'PASS' | 'POOR_CLOSEUP' | 'MOTION_BLUR' | 'FRAMING' | 'LIGHTING'.
    Returns 'PASS' on any error so a network blip never drops a clip.
    """
    # Use actual processed clip duration (slowmo expands output beyond source event window)
    try:
        _out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", clip_path],
            text=True, timeout=10,
        )
        duration = float(_out.strip())
    except Exception:
        duration = event.get("end", 0) - event.get("start", 0)
    # Sample at 25%, 50%, 75% of clip and pick the most representative (largest file = most detail)
    candidates = [
        _extract_thumbnail(clip_path, max(0.3, duration * frac))
        for frac in (0.25, 0.50, 0.75)
    ]
    # Deduplicate (mocks may return the same path repeatedly) and remove None
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    if not unique:
        return "PASS"

    def _fsize(p: str) -> int:
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    thumb = max(unique, key=_fsize)
    for c in unique:
        if c != thumb:
            try:
                os.remove(c)
            except OSError:
                pass
    try:
        img_file = genai.upload_file(path=thumb, mime_type="image/jpeg")
        model    = genai.GenerativeModel(model_name=_QA_MODEL)
        resp     = _with_retry(lambda: model.generate_content(
            [img_file, _QA_REASON_PROMPT],
            request_options={"timeout": 30},
        ))
        try:
            genai.delete_file(img_file.name)
        except Exception:
            pass
        code = resp.text.strip().upper().split()[0] if resp.text.strip() else "PASS"
        return code if code in _QA_REASON_CODES else "PASS"
    except Exception as _e:
        logger.debug("QA check error (assuming pass): %s", _e)
        return "PASS"
    finally:
        try:
            os.remove(thumb)
        except OSError:
            pass


_QA_PASS_CONTENT = {"hook": 10, "pacing": 10, "payoff": 10, "clarity": 10, "loopability": 10}


def _check_technical_compliance(reel_path: str) -> tuple[dict, bool, list[str]]:
    """Deterministic social-media spec check via ffprobe. Returns (specs, pass, issues)."""
    specs = get_reel_specs(reel_path)
    issues: list[str] = []
    if specs["aspect"] and abs(specs["aspect"] - 9 / 16) > 0.02:
        issues.append(f"aspect {specs['width']}x{specs['height']} not 9:16")
    if specs["duration"] is not None and not (
        config.QA_DUR_OK_MIN <= specs["duration"] <= config.QA_DUR_OK_MAX
    ):
        issues.append(
            f"duration {specs['duration']}s outside "
            f"{config.QA_DUR_OK_MIN}-{config.QA_DUR_OK_MAX}s"
        )
    if specs["height"] and specs["height"] < 1920:
        issues.append(f"resolution {specs['width']}x{specs['height']} below 1080x1920")
    if not specs["has_audio"]:
        issues.append("no audio track")
    return specs, not issues, issues


def _persist_qa_result(result: dict, reel_path: str, sport: str) -> None:
    """Append QA result to qa_results.jsonl — forward-compatible with future
    real engagement ingestion (actual_performance starts null, joinable by 'reel')."""
    try:
        record = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "reel":           Path(reel_path).name,
            "sport":          sport,
            "engagement_score": result.get("engagement_score"),
            "verdict":        result.get("verdict"),
            "content":        result.get("content"),
            "defects":        result.get("defects", []),
            "technical_pass": result.get("technical", {}).get("pass"),
            "overall":        result.get("overall", ""),
            "actual_performance": None,
        }
        with open(config.QA_RESULTS_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("Failed to persist QA result: %s", exc)


def qa_check_reel(reel_path: str, sport: str = "", athlete_label: str = "") -> dict:
    """Independent social-media QA on a compiled reel — two layers:

      A. Technical compliance (deterministic, ffprobe): 9:16, duration, resolution, audio.
      B. Content + engagement (LLM rubric, grounded in TikTok/IG best practices).

    verdict (advisory only — never blocks): PASS iff technical_pass AND
    engagement_score >= config.QA_ENGAGEMENT_THRESHOLD.

    Always returns a full PASS dict on any error — never drops a reel due to QA failure.
    Result is persisted to qa_results.jsonl for future calibration.
    """
    specs, technical_pass, tech_issues = _check_technical_compliance(reel_path)

    _PASS = {
        "verdict": "PASS",
        "technical": {"pass": technical_pass, "issues": tech_issues, **specs},
        "content": dict(_QA_PASS_CONTENT),
        "defects": [],
        "engagement_score": 100,
        "overall": "QA skipped",
    }
    try:
        vf = _upload_video(reel_path)
        try:
            prompt = _QA_REEL_PROMPT
            if sport:
                prompt += f"\nSport context: {sport}"
            if athlete_label:
                prompt += f"\nAthlete: {athlete_label}"
            # Calibration context: aggregate operator-approval signal (not per-reel
            # editing instructions — independence preserved).
            try:
                from pipeline.stages.feedback import get_qa_calibration_hint
                hint = get_qa_calibration_hint(sport)
                if hint:
                    prompt += "\n" + hint
            except Exception as exc:
                logger.debug("QA calibration hint unavailable: %s", exc)

            model = genai.GenerativeModel(model_name=_QA_REEL_MODEL)
            resp = _with_retry(lambda: model.generate_content(
                [vf, prompt], request_options={"timeout": 120}
            ))
            text = resp.text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text).rstrip("`").strip()
            parsed = json.loads(text)

            engagement = int(parsed.get("engagement_score", 0))
            engagement_ok = engagement >= config.QA_ENGAGEMENT_THRESHOLD
            defects = [d for d in (parsed.get("defects") or []) if isinstance(d, dict)]
            critical = [d for d in defects
                        if str(d.get("severity", "")).lower() == "critical"]
            result = {
                "verdict": "PASS" if (technical_pass and engagement_ok and not critical)
                           else "FAIL",
                "technical": {"pass": technical_pass, "issues": tech_issues, **specs},
                "content": parsed.get("content", {}),
                "defects": defects,
                "engagement_score": engagement,
                "overall": parsed.get("overall", ""),
            }
            _persist_qa_result(result, reel_path, sport)
            return result
        finally:
            _delete_video(vf)
    except Exception as exc:
        logger.warning("qa_check_reel failed for %s: %s", Path(reel_path).name, exc)
        return _PASS


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


@traceable(run_type="llm", name="gemini-analyze-chunk")
def _gemini_call_session(vf, prompt: str, model_name: str, video_name: str) -> str:
    """Traced Gemini call for session analysis — inputs/output logged to LangSmith."""
    model = genai.GenerativeModel(model_name=model_name)
    resp = _with_retry(lambda: model.generate_content(
        [vf, prompt], request_options={"timeout": 300}
    ))
    return resp.text


_IDENTITY_PROMPT = """
You are a video editor building personal highlight reels for athletes from drone footage.
You are watching the FULL video — not frames. Use motion, timing, and action sequences.

TASK:
1. Identify the sport/activity.
2. Identify each DISTINCT person (surfer, player, athlete) visible in the video.
3. For each person, select their highlight moments using the scoring guide below.

SCORING — rate each person relative to THEIR OWN moments only (not world-class standards,
and NOT compared to other people in the same footage):
A beginner's best ride is a 9 for them, even if an advanced athlete in the same session
would score a 10. Score each person against their own range of moments in this footage.

  10 : Once-in-a-session moment — peak trick/wave/play, athlete at absolute best, no hesitation
  9  : Clear highlight — clean execution, impressive for this athlete today
  8  : Strong moment — good skill with minor imperfection or brief camera wobble
  7  : Solid positive — usable, athlete performs well, nothing remarkable
  6  : Acceptable minimum — include only if it genuinely fills a gap in the reel
  5  : Weak or routine — walking, flat paddling, repositioning → EXCLUDE
  1-4: Mistake, wipeout, athlete out of frame, back to camera, or heavily obscured → EXCLUDE

Visual quality modifiers (apply BEFORE assigning final score):
  - Athlete occupies < 10% of frame height (drone very high, athlete tiny) → subtract 1
  - Motion blur makes athlete unrecognizable → subtract 2
  - Athlete partially cut off by frame edge → subtract 1

GLOBAL RANKING CONTEXT:
- Use the FULL 1-10 scale. Do not cluster all scores near 7.
- At least one event SHOULD receive 9 or 10 if a genuinely standout moment exists.
  If all moments are mediocre (no clear peak), the top score may be 7 or 8 — do not inflate.
- session_peak: report the highest score you assigned to any single event in this session.
  This helps the editor treat a score-8 in a peak-8 session as top-tier (not middle-tier).

SESSION STYLE — observe the overall footage character and report at the top level:
  visual:  "bright" (high exposure, vibrant colors) | "dark" (low light, muted) | "mixed"
  pace:    "fast" (new action every 2-5s) | "moderate" (moves every 5-12s) | "slow" (long sustained action)
  density: "high" (mostly action, few quiet moments) | "low" (long gaps between highlights)
These guide the editor's music tempo, cut rhythm, and color treatment.

SELECTION RULES:
- Include ALL moments with score >= 6 (they improve the athlete's image)
- If a person has NO moments reaching score 6, return an EMPTY events list for them.
  Not every person in frame has usable highlights — omitting is better than forcing bad clips.
- Do NOT include score < 6 under any circumstances.
- Every event must contain a COMPLETE, VISIBLE action: setup → execution → outcome.
  Do NOT report fragments where nothing clearly happens (a 2-second ripple, a half-visible
  turn, an action that starts after the camera looks away). If the real content is shorter
  than 5 seconds, it is not an event — skip it rather than stretching its timestamps.
- THE ACTION MUST BE READABLE ON A PHONE SCREEN: if a viewer watching this segment
  could not tell you what the athlete actually did (wave too small, athlete a distant
  dot, spray hides everything), it is NOT an event regardless of duration. Never pad
  timestamps around a 1-2s moment to satisfy the minimum — skip it entirely.
- Avoid overlapping timestamps: if two moments for the same person start within 3 seconds
  of each other, include ONLY the higher-scored one.
- Prefer variety: avoid 3+ nearly identical consecutive moves

EVENT COUNT: Aim for 3-8 events per person. Prefer quality over quantity — a 4-event reel
with scores 8,9,8,7 is better than a 10-event reel with four score-6 moments padded in.
It is acceptable (and preferred) to return 0 events for a person with no genuine highlights.

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
  IMPORTANT: Do NOT infer or state gender (man/woman/boy/girl) — drone footage typically
  shows people from above where gender is not reliably readable. Describe only visible
  clothing, equipment, and distinctive physical features. Example: "surfer in black one-piece
  swimsuit on turquoise longboard" NOT "young woman surfer on turquoise longboard".

For each EVENT:
- type: choose the closest value from this list (do NOT invent new labels):
    Aerial/trick:  aerial   = full rotation off wave lip or into the air (surfer, wakeboarder)
                   trick    = skateboard or bike trick (kickflip, tailwhip, barspin)
                   flip     = backflip or frontflip through the air (any sport)
                   gap_jump = rider clears a gap between two surfaces
                   kicker   = jump off a kicker/ramp feature
    Wave/water:    tube_ride, barrel, wave_catch, cutback, bottom_turn, carve, snap, paddle
    Ball sports:   goal, tackle, assist, interception, save, dribble, header, shot, clearance
    Bike/skate:    jump, landing, grind, manual, crash
    General:       sprint, approach, wipeout, near_miss, highlight
    (use "highlight" only when nothing else fits)
- start: exact start in seconds — include 1-2s buildup before the action peak
- end: exact end in seconds — include followthrough; minimum 6s after start
- setup_start: OPTIONAL — seconds where the athlete visibly begins setting up for the
    action (stance change, takeoff run-up, paddle into position). Omit if there is no
    distinct setup phase or you are not confident of the exact second.
- peak_time: OPTIONAL — seconds at the single moment the action peaks (trick apex, ball
    contact, wave lip hit, jump apex). Omit if you are not confident of the exact second.
- outcome_end: OPTIONAL — seconds where the outcome fully resolves (landing complete,
    play dead, wave ridden out or athlete falls). Omit if there is no clear resolution
    moment distinct from "end".
    Only report these three fields when you can point to the actual second with
    confidence — a wrong guess is worse than omitting the field, since editing logic
    treats a missing field as "use start/end as-is" and a present field as a firm claim.
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
         "setup_start": 13.0, "peak_time": 16.5, "outcome_end": 20.0,
         "crop_x": 0.4, "crop_y": 0.35,
         "edit": {"zoom": 1.4, "slowmo": true, "focus": "peak", "transition_out": "fade"}},
        {"type": "wave_catch", "start": 35.0, "end": 44.0, "score": 7,
         "description": "Catches a shoulder-high wave and paddles into position.",
         "crop_x": 0.55, "crop_y": 0.72,
         "edit": {"zoom": 1.1, "slowmo": false, "focus": "full", "transition_out": "slide"}}
      ]
    },
    {
      "id": "person_B",
      "description": "surfer with blue board and white rash guard",
      "events": [
        {"type": "snap", "start": 58.0, "end": 66.0, "score": 8,
         "description": "Sharp snap off the top, spray flies off the lip.",
         "crop_x": 0.6, "crop_y": 0.55,
         "edit": {"zoom": 1.3, "slowmo": true, "focus": "peak", "transition_out": "cut"}}
      ]
    }
  ]
}

If only one person is visible, use the persons array with one entry.
If no action moments exist at all: {"activity": "unknown", "persons": []}
"""


def _optional_phase_time(value) -> float | None:
    """Parse an optional setup_start/peak_time/outcome_end field.

    Gemini is told to omit these rather than guess, so a missing/invalid value
    must stay None (meaning "no phase evidence") rather than default to 0 —
    pipeline.window_policy.resolve_window() treats None as "not provided" and
    None is a materially different signal from a real timestamp of 0.0.
    """
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


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
            # Drop fragments below MIN_EVENT_SEC instead of padding them out:
            # a 2s ripple padded to 6s is 4s of nothing — it kills the hook.
            if end - start < config.MIN_EVENT_SEC:
                logger.info("Dropping %.1fs fragment '%s' @%.1fs (< %.0fs min)",
                            end - start, ev.get("type", "?"), start, config.MIN_EVENT_SEC)
                continue
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
                "setup_start": _optional_phase_time(ev.get("setup_start")),
                "peak_time":   _optional_phase_time(ev.get("peak_time")),
                "outcome_end": _optional_phase_time(ev.get("outcome_end")),
            })

        # Keep only score >= 6. Safety net for beginner/mixed-ability sessions:
        # if no score-6 events but the person had genuine action (score >= 5),
        # include their top 2 so every participant gets a personal clip.
        # If best score < 5 (title card, bystander, not actively performing) → skip.
        good = [ev for ev in all_events if ev["score"] >= 6]
        if not good and all_events:
            best_score = max(ev["score"] for ev in all_events)
            if best_score >= 5:
                good = sorted(all_events, key=lambda x: x["score"], reverse=True)[:2]

        good.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate: if two events start within 2s of each other, keep only the better one.
        _kept: list[dict] = []
        for ev in good:
            if not any(abs(ev["start"] - k["start"]) < 2.0 for k in _kept):
                _kept.append(ev)
        good = _kept

        persons.append({
            "id":          str(p.get("id", "person_?")),
            "description": str(p.get("description", "unknown")),
            "events":      good,
        })

    return {"activity": activity, "persons": persons, "style": style, "session_peak": session_peak}


@traceable(name="analyze-session")
def analyze_session(video_path: str) -> dict:
    """
    Identifies distinct persons and their highlight moments via Gemini.
    Long videos (> _CHUNK_MAX_MINUTES) are split into chunks first to stay
    within Gemini's 1M-token context window. Results are merged automatically.

    Returns:
        {"activity": str, "persons": [...], "style": {...}, "session_peak": int}
    """
    print(f"🔍 Analyzing '{Path(video_path).name}' — multi-person session mode...")

    # Build prompt — inject feedback + operator notes AFTER SELECTION RULES so
    # Gemini sees them just before the detailed field instructions.
    from pipeline.stages.feedback import get_all_label_injections, get_negative_feedback_hint, get_operator_notes
    feedback_block = get_all_label_injections()
    notes_block    = get_operator_notes()   # all pending notes (global context)
    negative_block = get_negative_feedback_hint()  # structured operator complaints (draft_feedback)
    injection      = (feedback_block or "") + (notes_block or "") + (negative_block or "")
    if feedback_block:
        sport_count = feedback_block.count("\n  ")
        logger.info("Injecting editing feedback for %d sport(s) into prompt", sport_count)
        print(f"🏷️  Injecting editing history ({sport_count} sport(s)) into analysis prompt")
    if notes_block:
        logger.info("Injecting operator notes into prompt")
        print(f"📝 Injecting operator editing notes into analysis prompt")
    if negative_block:
        logger.info("Injecting structured operator feedback into prompt")
        print(f"🚩 Injecting recent operator problem-feedback into analysis prompt")
    if injection:
        _split_marker = "\nEVENT COUNT:"
        if _split_marker in _IDENTITY_PROMPT:
            _pre, _post = _IDENTITY_PROMPT.split(_split_marker, 1)
            prompt = _pre + injection + _split_marker + _post
        else:
            prompt = _IDENTITY_PROMPT + injection
    else:
        prompt = _IDENTITY_PROMPT

    # Split long videos into chunks
    try:
        chunks = _chunk_video(video_path)
    except Exception as _ce:
        logger.warning("Chunking failed (%s) — analyzing full video", _ce)
        chunks = [video_path]
    is_chunked = len(chunks) > 1

    def _analyze_one(chunk_path: str) -> dict:
        """Upload one file, analyze with Gemini, delete. JSON errors → empty result."""
        proxy_path = None
        vf = None
        try:
            proxy_path = _make_proxy(chunk_path)
            upload_path = proxy_path if proxy_path else chunk_path
            vf = _with_retry(lambda: _upload_video(upload_path))
            response_text = _gemini_call_session(
                vf=vf,
                prompt=prompt,
                model_name=_MODEL,
                video_name=Path(upload_path).name,
            )
            return _parse_session(response_text)
        except json.JSONDecodeError as e:
            logger.error("Gemini JSON parse error: %s", e)
            print(f"⚠️ JSON parse error from Gemini: {e}")
            return {"activity": "unknown", "persons": [], "style": {}, "session_peak": 0}
        finally:
            if vf:
                _delete_video(vf)
            if proxy_path and os.path.exists(proxy_path):
                os.remove(proxy_path)

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
        # Drop fragments below MIN_EVENT_SEC instead of padding them out (see _parse_session)
        if end - start < config.MIN_EVENT_SEC:
            logger.info("Dropping %.1fs fragment '%s' @%.1fs (< %.0fs min)",
                        end - start, ev.get("type", "?"), start, config.MIN_EVENT_SEC)
            continue
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
            "setup_start": _optional_phase_time(ev.get("setup_start")),
            "peak_time":   _optional_phase_time(ev.get("peak_time")),
            "outcome_end": _optional_phase_time(ev.get("outcome_end")),
        })

    # Keep only score >= 6. Safety net for beginner/mixed-ability sessions:
    # if no score-6 events but genuine action exists (score >= 5), include top 2.
    # If best score < 5 (bystander, title card, not actively performing) → skip.
    good = [ev for ev in all_events if ev["score"] >= 6]
    if not good and all_events:
        best_score = max(ev["score"] for ev in all_events)
        if best_score >= 5:
            good = sorted(all_events, key=lambda x: x["score"], reverse=True)[:2]

    good.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate: if two events start within 2s of each other, keep only the better one.
    _kept: list[dict] = []
    for ev in good:
        if not any(abs(ev["start"] - k["start"]) < 2.0 for k in _kept):
            _kept.append(ev)
    good = _kept

    return {"activity": activity, "events": good}
