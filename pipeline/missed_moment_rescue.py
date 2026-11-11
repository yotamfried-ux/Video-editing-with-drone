"""Second look at people who moved through a clip but got no event from the analyzer.

The session analyzer builds every event around one target athlete performing a complete action, scored on how
well it is performed. A moment outside that frame gets no event even when it is the best thing in the clip.
Run 43013005072, 0094: a father and child riding one longboard together for 20 s (in the manual catalog) were
listed by the analyzer as two separate people, "light blue top" and "yellow top" on the same turquoise longboard,
each with `no_complete_action`. The ride-coverage report flagged the track (13.8-36.6 s, 38% inside kept rides),
but nothing acted on it.

Here each such window (a long, moving track mostly outside every kept ride) is cut from the source and shown to a
model asked one narrow question: is there a moment by someone OTHER than the athletes already covered that is
worth a reel, including unusual ones: tandem rides, children, pets, funny or touching moments, unusual craft. A
confirmed moment becomes an event of a new person, bound to that track, and goes through the normal identity,
cut and QA path. The analysis prompt and its cache are untouched; answers are cached per source and window.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RESCUE_PROMPT_VERSION = "missed-moment-v1"
# A window is worth a model call only when it is long, the person travels, and almost all of it is outside rides.
MIN_SPAN_SEC = 6.0
MIN_TRAVEL_FRAMES = 0.5
MAX_COVERED = 0.4
MIN_SCORE = 6
_PAD_SEC = 1.0
_calls_lock = threading.Lock()
_calls_made = 0

_PROMPT = """\
This clip is a window from drone/phone footage of a sports session ({activity}). The tracking system saw a person
moving through it, but the editor gave this window no highlight.

Athletes ALREADY COVERED in this clip (do NOT report them again, even if they appear here):
{covered}
People the editor noticed here without a highlight: {noticed}

Is there a moment in this clip, by someone NOT in the covered list, that is worth putting in a short personal
reel? Count unusual moments, not only skilled ones:
- two people riding one board together (a parent and child, a couple), a child riding, a pet on a board
- a funny, surprising or heartwarming moment (a wave that knocks someone over, a celebration, a long ride by a
  beginner)
- an unusual craft or style (bodyboard, SUP, foil, riding backwards)
A viewer must be able to see and follow the person or people; skill is NOT required. Do not report paddling,
waiting in the lineup, a failed take-off with nothing else, or a person too small to follow.

Return ONLY JSON, no markdown:
{{"moment": true|false, "kind": "ride|tandem_ride|notable_moment|none",
  "start": <seconds from the start of THIS clip>, "end": <seconds from the start of THIS clip>,
  "people": <number of people performing it>,
  "description": "<who: clothing, hair, board color; write 'tandem' when two people share one board>",
  "score": <1-10, how much a viewer would enjoy watching it>,
  "reason": "<one short sentence>"}}
"""


def _max_calls() -> int:
    try:
        return max(0, int(os.getenv("SPORTREEL_MISSED_MOMENT_MAX_CALLS", "8")))
    except ValueError:
        return 8


def _enabled() -> bool:
    return os.getenv("SPORTREEL_MISSED_MOMENT_RESCUE", "1").strip().lower() not in {"0", "false", "no", "off"}


def select_windows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Long, moving, mostly uncovered tracks; overlapping ones merged into the longest of them."""
    eligible = [c for c in candidates
                if c.get("span", 0) >= MIN_SPAN_SEC and c.get("travel_frames", 0) >= MIN_TRAVEL_FRAMES
                and c.get("covered", 1) <= MAX_COVERED]
    chosen: list[dict[str, Any]] = []
    for cand in sorted(eligible, key=lambda c: -c["span"]):
        if any(min(cand["end"], c["end"]) - max(cand["start"], c["start"]) > 0 for c in chosen):
            continue
        chosen.append(cand)
    return chosen


def _take_call_slot() -> bool:
    global _calls_made
    with _calls_lock:
        if _calls_made >= _max_calls():
            return False
        _calls_made += 1
        return True


def _track_center(detections: list, track_id: str, start: float, end: float) -> tuple[float, float] | None:
    xs, ys = [], []
    for det in detections or []:
        get = det.get if isinstance(det, dict) else (lambda k, d=det: getattr(d, k, None))
        if str(get("tracker_id")) != str(track_id):
            continue
        try:
            t = float(get("time_sec"))
            x1, y1, x2, y2 = (float(v) for v in get("xyxy"))
            w, h = float(get("frame_width")), float(get("frame_height"))
        except (TypeError, ValueError):
            continue
        if start <= t <= end and w > 0 and h > 0:
            xs.append((x1 + x2) / 2.0 / w)
            ys.append((y1 + y2) / 2.0 / h)
    if not xs:
        return None
    xs.sort(); ys.sort()
    return round(xs[len(xs) // 2], 4), round(ys[len(ys) // 2], 4)


def _cut_window(video_path: str, start: float, end: float) -> str | None:
    out = tempfile.NamedTemporaryFile(prefix="missed_moment_", suffix=".mp4", delete=False).name
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(video_path),
           "-vf", "scale=-2:720", "-r", "10", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", out]
    try:
        subprocess.run(cmd, check=True, timeout=180)
        return out if os.path.getsize(out) > 0 else None
    except Exception as exc:
        logger.debug("missed-moment clip cut failed: %s", exc)
        try:
            os.remove(out)
        except OSError:
            pass
        return None


def _ask_model(clip: str, prompt: str) -> str:
    from integrations.gemini import delete_video, genai, upload_video

    model_name = os.getenv("SPORTREEL_MISSED_MOMENT_MODEL", "gemini-2.5-flash")
    vf = upload_video(clip)
    try:
        model = genai.GenerativeModel(model_name=model_name)
        return model.generate_content([vf, prompt], request_options={"timeout": 120}).text.strip()
    finally:
        try:
            delete_video(vf)
        except Exception:
            pass


def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```[a-z]*\n?", "", str(text or "").strip()).rstrip("`").strip()
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def _is_covered_athlete(description: str, covered: list[dict[str, Any]]) -> bool:
    """The model was told not to report covered athletes; this is the check that it did not."""
    from pipeline.stages.identity import extract_structured_attributes, structured_attributes_compatible

    found = extract_structured_attributes(description)
    for person in covered:
        ok, score = structured_attributes_compatible(found, extract_structured_attributes(str(person.get("description") or "")))
        if ok and score >= 0.7:
            return True
    return False


def rescue_missed_moments(video_path: str, people: list[dict[str, Any]], candidates: list[dict[str, Any]],
                          detections: list, activity: str = "") -> list[dict[str, Any]]:
    """Return new person entries (one event each) for confirmed moments in uncovered windows."""
    if not _enabled() or not candidates:
        return []
    windows = select_windows(candidates)
    if not windows:
        return []
    try:
        from integrations.ffmpeg import get_duration
        duration = float(get_duration(str(video_path)))
    except Exception:
        duration = None
    covered = [p for p in people if p.get("events")]
    covered_text = "\n".join(
        f"- {p.get('description')} (highlight {', '.join(f'{float(e['start']):.1f}-{float(e['end']):.1f}s' for e in p['events'] if 'start' in e and 'end' in e)})"
        for p in covered) or "- none"
    noticed = "; ".join(str(p.get("description")) for p in people if not p.get("events")) or "none"
    name = Path(str(video_path)).name
    rescued: list[dict[str, Any]] = []
    for win in windows:
        lo = max(0.0, float(win["start"]) - _PAD_SEC)
        hi = float(win["end"]) + _PAD_SEC
        if duration:
            hi = min(hi, duration)
        prompt = _PROMPT.format(activity=activity or "sports", covered=covered_text, noticed=noticed)
        text = None
        cache_key = None
        try:
            from integrations import llm_cache

            cache_key = llm_cache.make_key("missed-moment", media_sha256=llm_cache.file_sha256(str(video_path)),
                                           prompt=prompt, model=os.getenv("SPORTREEL_MISSED_MOMENT_MODEL", "gemini-2.5-flash"),
                                           version=RESCUE_PROMPT_VERSION, extra=f"{lo:.2f}-{hi:.2f}")
            text = llm_cache.get(cache_key)
        except Exception as exc:
            logger.debug("missed-moment cache unavailable: %s", exc)
        if not text:
            if not _take_call_slot():
                print(f"   ⏭️  missed-moment check skipped (call budget used): {name} {lo:.1f}-{hi:.1f}s")
                continue
            clip = _cut_window(str(video_path), lo, hi)
            if not clip:
                continue
            try:
                text = _ask_model(clip, prompt)
            except Exception as exc:
                logger.warning("missed-moment check failed for %s: %s", name, exc)
                continue
            finally:
                try:
                    os.remove(clip)
                except OSError:
                    pass
            if cache_key:
                try:
                    from integrations import llm_cache
                    llm_cache.put(cache_key, text, kind="missed-moment", source=name)
                except Exception:
                    pass
        try:
            answer = _parse(text)
        except Exception:
            continue
        description = str(answer.get("description") or "").strip()
        try:
            score = int(float(answer.get("score", 0)))
            start = lo + float(answer.get("start"))
            end = lo + float(answer.get("end"))
        except (TypeError, ValueError):
            score, start, end = 0, 0.0, 0.0
        found = bool(answer.get("moment")) and score >= MIN_SCORE and end - start >= 2.0 and description
        if found and _is_covered_athlete(description, covered):
            found = False
            answer["reason"] = f"same athlete as an existing highlight: {answer.get('reason', '')}"
        verdict = "ADDED" if found else "not added"
        print(f"   🛟 missed-moment check ({verdict}): {name} {lo:.1f}-{hi:.1f}s kind={answer.get('kind')} "
              f"score={answer.get('score')} \"{description[:70]}\" — {str(answer.get('reason', ''))[:100]}")
        if not found:
            continue
        end = min(end, duration) if duration else end
        center = _track_center(detections, str(win["track_id"]), start, end) or (0.5, 0.5)
        kind = str(answer.get("kind") or "notable_moment")
        surf = any(term in (activity or "").lower() for term in ("surf", "wave"))
        event = {
            "type": "wave_catch" if surf and kind in {"ride", "tandem_ride"} else "notable_moment",
            "description": description, "start": round(start, 2), "end": round(end, 2), "score": score,
            "target_track_id": str(win["track_id"]), "crop_x": center[0], "crop_y": center[1],
            "timing_evidence": f"start {start:.1f}s; end {end:.1f}s: {answer.get('reason', '')}",
            "ride_completed": True, "moment_kind": kind, "rescued_by": RESCUE_PROMPT_VERSION,
            "primary_actor_clear": True, "primary_actor_confidence": 0.8, "identity_continuity": "stable",
            "background_people_present": True, "competing_active_subjects": False,
            "target_occluded_at_key_moment": False,
            "primary_actor_reason": "second-look check: the moment's people are the tracked subject",
        }
        if surf and "surf" not in description.lower() and kind in {"ride", "tandem_ride"}:
            event["sport"] = "surfing"
        rescued.append({"id": f"rescued_track_{win['track_id']}", "description": description, "events": [event],
                        "rescued_by": RESCUE_PROMPT_VERSION})
    return rescued
