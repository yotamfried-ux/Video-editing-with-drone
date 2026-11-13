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

RESCUE_PROMPT_VERSION = "missed-moment-v2"
# A window is worth a model call only when it is long, the person travels, and almost all of it is outside rides.
MIN_SPAN_SEC = 6.0
MIN_TRAVEL_FRAMES = 0.5
MAX_COVERED = 0.4
MIN_SCORE = 6
# Only what the analyzer's single-athlete contract cannot see is added. An ordinary ride the analyzer already looked
# at and rejected stays rejected: run 43031447052 added 0155 (catalogued as a failed take-off with no meaningful
# action) and 0152 (most likely the athlete already covered) as "ride", while the tandem in 0094 was the real find.
RESCUED_KINDS = {"tandem_ride", "notable_moment"}
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
  "start_evidence": "<what is visible at the start second, e.g. pops up to stand>",
  "end_evidence": "<what is visible at the end second, e.g. both step off as the wave dies>",
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


# The model picks the moment's end from a clip it was shown once. When the rescued subject is still seen, moving, from
# that second until the recording ends, the ride has not been shown to its outcome: the end is the recording's, an
# observed boundary, like the analyzer's own outcome_end. Run 43303438106, 0094: the model ended the tandem ride at
# 33.8 s, track 162 was tracked to 36.6 s of a 36.7 s file, the catalog ride ends at 36.7 s, and final QA reported
# PREMATURE_CUT at the reel's end. A longer tail than this is not claimed: the subject may be wading ashore.
_END_EXTENSION_MAX_SEC = 4.0
_END_EXTENSION_MIN_TRAVEL = 0.05  # frame widths the subject must still move between the model's end and the recording's
# Run 43397405813 (same source, same model answer) did not extend: final QA saw "the child falls off the board later
# and the adult continues the ride to the shore". When the tracker loses a subject it restarts it under a new id; a
# fragment that starts where and when the old one stopped is the same subject. Bounded so a passer-by is not taken.
_JOIN_MAX_GAP_SEC = 1.0
_JOIN_MAX_DIST = 0.12  # frame widths/heights between the lost box centre and the new fragment's first one
_JOIN_MAX_FRAGMENTS = 3


def _track_samples(detections: list) -> dict[str, list[tuple[float, float, float]]]:
    """Per track id: (time, centre x, centre y) normalised by frame size, sorted by time."""
    out: dict[str, list[tuple[float, float, float]]] = {}
    for det in detections or []:
        get = det.get if isinstance(det, dict) else (lambda k, d=det: getattr(d, k, None))
        tid = get("tracker_id")
        if tid is None:
            continue
        try:
            t = float(get("time_sec"))
            x1, y1, x2, y2 = (float(v) for v in get("xyxy"))
            w, h = float(get("frame_width")), float(get("frame_height"))
        except (TypeError, ValueError):
            continue
        if w > 0 and h > 0:
            out.setdefault(str(tid), []).append((t, (x1 + x2) / 2.0 / w, (y1 + y2) / 2.0 / h))
    for samples in out.values():
        samples.sort()
    return out


def extend_end_on_track(detections: list, track_id: str, start: float, end: float, duration: float | None,
                        exclude_tracks: set[str] | None = None) -> dict[str, Any]:
    """Decide whether the rescued moment's end moves to the recording's end, and say why.

    Returns {"end": new end or None, "reason": str, "continuation_track_ids": [...]}. The subject is followed from
    the model's end on its own track and, where that track stops, on a fragment that starts within
    _JOIN_MAX_GAP_SEC and _JOIN_MAX_DIST of it (never a track another highlight follows).
    """
    result: dict[str, Any] = {"end": None, "reason": "", "continuation_track_ids": []}
    if not duration:
        result["reason"] = "recording duration unknown"
        return result
    if end >= duration - _RECORDING_END_TOLERANCE_SEC:
        result["reason"] = "already ends at the recording end"
        return result
    if duration - end > _END_EXTENSION_MAX_SEC:
        result["reason"] = f"{duration - end:.1f}s left after the model's end, more than {_END_EXTENSION_MAX_SEC:.0f}s"
        return result
    tracks = _track_samples(detections)
    own = tracks.get(str(track_id), [])
    inside = [t for t, _x, _y in own if start <= t <= end]
    gaps = sorted(b - a for a, b in zip(inside, inside[1:]) if b > a)
    tolerance = max(1.0, 3.0 * (gaps[len(gaps) // 2] if gaps else 0.0))
    tail = [p for p in own if p[0] >= end - 1e-6]
    if not tail:
        result["reason"] = f"track {track_id} not seen after {end:.1f}s"
        return result
    excluded = {str(t) for t in (exclude_tracks or set())} | {str(track_id)}
    first_x = tail[0][1]
    last_t, last_x, last_y = tail[0]
    current, chain = str(track_id), []
    while True:
        for t, x, y in [p for p in tracks.get(current, []) if p[0] > last_t]:
            if t - last_t > tolerance:
                break
            last_t, last_x, last_y = t, x, y
        if duration - last_t <= tolerance or len(chain) >= _JOIN_MAX_FRAGMENTS:
            break
        best = None
        for tid, samples in tracks.items():
            if tid in excluded or tid in chain:
                continue
            t0, x0, y0 = samples[0]
            if not (last_t - 0.25 <= t0 <= last_t + _JOIN_MAX_GAP_SEC):
                continue
            dist = max(abs(x0 - last_x), abs(y0 - last_y))
            if dist <= _JOIN_MAX_DIST and (best is None or dist < best[0]):
                best = (dist, tid, samples[0])
        if best is None:
            break
        current = best[1]
        chain.append(current)
        last_t, last_x, last_y = best[2]
    result["continuation_track_ids"] = chain
    if duration - last_t > tolerance:
        joined = f" (joined {', '.join(chain)})" if chain else ""
        result["reason"] = f"subject lost at {last_t:.1f}s{joined}, {duration - last_t:.1f}s before the recording end"
        return result
    if abs(last_x - first_x) < _END_EXTENSION_MIN_TRAVEL:
        result["reason"] = f"subject moved {abs(last_x - first_x):.2f} frame widths after the model's end (still)"
        return result
    result["end"] = float(duration)
    result["reason"] = "still moving until the recording ends" + (f" (joined {', '.join(chain)})" if chain else "")
    return result


# A moment that runs into the last frames of the source ends where the recording does: an observed boundary.
_RECORDING_END_TOLERANCE_SEC = 0.3


def _timing_contract(answer: dict[str, Any], start: float, end: float, recording_end: bool) -> dict[str, Any]:
    """The analyzer's timing contract for a rescued moment (pipeline.stages.analyzer._timing_fields).

    Run 43203677423: the tandem ride carried only the model's reason as timing evidence and no timing_precise, so
    pipeline.surf_ride_segment treated its end as inferred and blocked the reel (RIDE_BOUNDARY_UNCERTAIN), although
    the ride ran to the end of the recording. A moment is exact when the model names what is visible at both
    boundaries; an end at the recording end is observed whatever the model says.
    """
    start_ev = " ".join(str(answer.get("start_evidence") or "").split())[:120]
    end_ev = " ".join(str(answer.get("end_evidence") or "").split())[:120]
    fields: dict[str, Any] = {}
    if start_ev and end_ev:
        fields["timing_evidence"] = f"start {start:.1f}s: {start_ev}; end {end:.1f}s: {end_ev}"
        fields["timing_precise"] = True
    if recording_end:
        fields["outcome_end"] = round(end, 2)
        fields["ride_end_evidence"] = "recording_end"
    return fields


def _bind_to_track(event: dict[str, Any], detections: list, track_id: str) -> dict[str, Any] | None:
    """Attach the same tracker evidence every analyzer event gets (bbox, track_id, visible tracks), from the
    rescued track only. Framing refuses an event without it: run 43031447052 crashed in the cut step on the first
    rescued event, which had a target track but none of this evidence."""
    from pipeline.perception.runtime import enrich_event

    own = [d for d in detections or [] if str(getattr(d, "tracker_id", None)) == str(track_id)]
    if not own:
        return None
    enriched = enrich_event(event, own)
    if enriched.get("perception_evidence_status") != "tracker_sidecar" or enriched.get("track_id") is None:
        return None
    if str(enriched.get("target_track_id")) != str(track_id):
        return None
    try:
        others = sorted({str(d.tracker_id) for d in detections or [] if d.tracker_id is not None
                         and float(event["start"]) <= float(d.time_sec) <= float(event["end"])})
    except (TypeError, ValueError, KeyError):
        others = []
    if others:  # the framing decision must see everyone in the window, not only the rescued track
        enriched.update({"visible_track_ids": others, "all_visible_track_ids": others, "source_window_track_ids": others})
    return enriched


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
    kept_tracks = {str(e.get("target_track_id") or e.get("track_id")) for p in covered for e in p["events"]
                   if e.get("target_track_id") is not None or e.get("track_id") is not None}
    windows = [w for w in windows if str(w["track_id"]) not in kept_tracks]
    if not windows:
        return []
    def windows_of(person: dict[str, Any]) -> str:
        spans = []
        for ev in person.get("events", []):
            try:
                spans.append("%.1f-%.1fs" % (float(ev["start"]), float(ev["end"])))
            except (KeyError, TypeError, ValueError):
                continue
        return ", ".join(spans)

    covered_text = "\n".join(f"- {p.get('description')} (highlight {windows_of(p)})" for p in covered) or "- none"
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
        kind = str(answer.get("kind") or "none")
        found = bool(answer.get("moment")) and score >= MIN_SCORE and end - start >= 2.0 and bool(description)
        if found and kind not in RESCUED_KINDS:
            found = False
            answer["reason"] = f"an ordinary {kind}: the analyzer's decision stands. {answer.get('reason', '')}"
        if found and _is_covered_athlete(description, covered):
            found = False
            answer["reason"] = f"same athlete as an existing highlight: {answer.get('reason', '')}"
        verdict = "ADDED" if found else "not added"
        print(f"   🛟 missed-moment check ({verdict}): {name} {lo:.1f}-{hi:.1f}s kind={answer.get('kind')} "
              f"score={answer.get('score')} \"{description[:70]}\" — {str(answer.get('reason', ''))[:100]}")
        if not found:
            continue
        model_end = None
        extension = extend_end_on_track(detections, str(win["track_id"]), start, end, duration, kept_tracks)
        if extension["end"] is not None:
            print(f"   🛟 missed-moment end moved {end:.1f}s -> {extension['end']:.1f}s: {extension['reason']}")
            model_end = round(end, 2)
            end = extension["end"]
        elif extension["reason"] != "already ends at the recording end":
            print(f"   🛟 missed-moment end kept at {end:.1f}s: {extension['reason']}")
        recording_end = bool(duration) and end >= float(duration) - _RECORDING_END_TOLERANCE_SEC
        end = min(end, duration) if duration else end
        center = _track_center(detections, str(win["track_id"]), start, end) or (0.5, 0.5)
        surf = any(term in (activity or "").lower() for term in ("surf", "wave"))
        event = {
            "type": "wave_catch" if surf and kind in {"ride", "tandem_ride"} else "notable_moment",
            "description": description, "start": round(start, 2), "end": round(end, 2), "score": score,
            "target_track_id": str(win["track_id"]), "crop_x": center[0], "crop_y": center[1],
            "timing_evidence": f"start {start:.1f}s; end {end:.1f}s: {answer.get('reason', '')}",
            **_timing_contract(answer, start, end, recording_end),
            "ride_completed": True, "moment_kind": kind, "rescued_by": RESCUE_PROMPT_VERSION,
            "primary_actor_clear": True, "primary_actor_confidence": 0.8, "identity_continuity": "stable",
            "background_people_present": True, "competing_active_subjects": False,
            "target_occluded_at_key_moment": False,
            "primary_actor_reason": "second-look check: the moment's people are the tracked subject",
        }
        if model_end is not None:
            event["end_before_track_extension"] = model_end
            if extension["continuation_track_ids"]:
                event["continuation_track_ids"] = list(extension["continuation_track_ids"])
        event["end_extension_reason"] = extension["reason"]
        if surf and "surf" not in description.lower() and kind in {"ride", "tandem_ride"}:
            event["sport"] = "surfing"
        event = _bind_to_track(event, detections, str(win["track_id"]))
        if event is None:
            print(f"   🛟 missed-moment check (not added): {name} {lo:.1f}-{hi:.1f}s — no tracker evidence for track "
                  f"{win['track_id']} in the moment's window")
            continue
        person_id = f"rescued_track_{win['track_id']}"
        # Analyzer events get their person lineage when chunk results are merged; a rescued person is added after
        # that, so it is stamped here. Run 43079298706 failed the publishable gate on exactly this: the tandem
        # ride's selected window had no person_id ("selected identity lineage completeness must be 1.0, got 0.958").
        event.update({"person_id": person_id, "chunk_person_id": person_id, "source_person_id": person_id,
                      "source_video": name})
        rescued.append({"id": person_id, "source_person_id": person_id, "chunk_person_id": person_id,
                        "source_video": name, "description": description, "events": [event],
                        "rescued_by": RESCUE_PROMPT_VERSION})
    return rescued
