"""Runtime quality hardening for the production pipeline entrypoint.

This module intentionally runs before pipeline.orchestrator imports analyzer symbols.
It normalizes Gemini analysis output so the editor receives only usable events and
identity clustering gets per-athlete thumbnails instead of full-frame session grabs.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import config
from pipeline import identity_trace
from pipeline.perception.crop_math import event_has_bbox_metadata, resolve_event_crop

logger = logging.getLogger(__name__)

_MIN_KEEP_SCORE = 6
_MIN_VISIBLE_RATIO = 0.35
_IDENTITY_THUMB_SIZE = 640
# Identity evidence: a contact sheet of several full-resolution crops of the person's own tracked box, spread over
# the person's events, instead of one 640px crop around a single point. One crop from one moment is often a back
# view, a wipe-out or a far shot; several views of the same track carry clothing, board and build together.
_SHEET_TILE = 320
_SHEET_MIN_VISIBLE = 0.6


def _sheet_crops() -> int:
    try:
        return max(0, min(6, int(os.getenv("SPORTREEL_IDENTITY_CROPS", "4"))))
    except ValueError:
        return 4


def _clamp01(value: Any, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _score(event: dict) -> int:
    try:
        return int(event.get("score", 0))
    except (TypeError, ValueError):
        return 0


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _normalize_event_crop(event: dict) -> dict | None:
    """Prefer measured bbox crop when perception metadata is attached.

    Current Gemini-only events intentionally keep their existing crop contract.
    Future perception events with invalid/missing bbox metadata fail safe by
    being dropped instead of silently falling back to an unreliable LLM crop.
    """
    crop = resolve_event_crop(event, min_visible_ratio=_MIN_VISIBLE_RATIO)
    has_bbox = event_has_bbox_metadata(event)
    if has_bbox and not crop["perception_crop_usable"]:
        logger.info(
            "Dropping event '%s' — unusable perception crop: %s",
            event.get("type", "?"),
            crop["perception_crop_status"],
        )
        return None
    if not has_bbox:
        return event
    return {
        **event,
        "crop_x": round(float(crop["crop_x"]), 4),
        "crop_y": round(float(crop["crop_y"]), 4),
        "visible_ratio": round(float(crop["visible_ratio"]), 4),
        "crop_source": crop["crop_source"],
        "perception_crop_status": crop["perception_crop_status"],
        "perception_crop_usable": crop["perception_crop_usable"],
    }


def _extract_identity_thumbnail(video_path: str, event: dict, timestamp: float) -> str | None:
    """Extract a focused square thumbnail around the athlete's reported crop point.

    The identity matcher compares these images across clips. Full-frame drone
    thumbnails often show tiny surfers plus unrelated people, which makes Re-ID
    brittle; a crop centered on crop_x/crop_y gives the matcher the actual athlete.
    """
    crop_x = _clamp01(event.get("crop_x", 0.5), 0.5)
    crop_y = _clamp01(event.get("crop_y", 0.65), 0.65)
    half = _IDENTITY_THUMB_SIZE // 2
    stem = Path(video_path).stem
    out_path = os.path.join(
        config.TMP_DIR,
        f"identity_thumb_{stem}_{timestamp:.3f}_{crop_x:.3f}_{crop_y:.3f}.jpg",
    )
    os.makedirs(config.TMP_DIR, exist_ok=True)

    vf = (
        "scale='if(gte(iw,ih),1280,-2)':'if(gte(iw,ih),-2,1280)',"
        f"crop={_IDENTITY_THUMB_SIZE}:{_IDENTITY_THUMB_SIZE}:"
        f"'max(0,min(iw-{_IDENTITY_THUMB_SIZE},iw*{crop_x:.4f}-{half}))':"
        f"'max(0,min(ih-{_IDENTITY_THUMB_SIZE},ih*{crop_y:.4f}-{half}))'"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(max(0.0, timestamp)),
        "-i", video_path,
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", "3",
        out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return out_path if os.path.exists(out_path) else None
    except Exception as exc:
        logger.debug("Identity thumbnail extraction failed at %.1fs: %s", timestamp, exc)
        _safe_remove(out_path)
        return None


def _track_samples(events: list[dict], detections: list, k: int) -> list:
    """Up to k detections of each event's bound track, spread in time, preferring larger, fully visible boxes."""
    pool = []
    for ev in events:
        tid = ev.get("target_track_id")
        if tid is None:
            continue
        try:
            start, end = float(ev.get("start")), float(ev.get("end"))
        except (TypeError, ValueError):
            continue
        pool.extend(d for d in detections
                    if d.tracker_id is not None and str(d.tracker_id) == str(tid) and start <= d.time_sec <= end)
    if not pool or k <= 0:
        return []
    good = [d for d in pool if d.visible_ratio >= _SHEET_MIN_VISIBLE] or pool
    good.sort(key=lambda d: d.time_sec)
    area = lambda d: (d.xyxy[2] - d.xyxy[0]) * (d.xyxy[3] - d.xyxy[1])
    picks = []
    for i in range(min(k, len(good))):
        bucket = good[i * len(good) // min(k, len(good)):(i + 1) * len(good) // min(k, len(good))]
        if bucket:
            picks.append(max(bucket, key=area))
    return picks


def _crop_box(det) -> tuple[float, float, float, float]:
    """Square crop around the box with context (board, wake), as fractions of the frame: (x, y, w, h)."""
    x1, y1, x2, y2 = det.xyxy
    fw, fh = float(det.frame_width), float(det.frame_height)
    side = max(max(x2 - x1, y2 - y1) * 2.0, 0.08 * min(fw, fh))
    side = min(side, fw, fh)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    left = min(max(0.0, cx - side / 2.0), fw - side)
    top = min(max(0.0, cy - side / 2.0), fh - side)
    return left / fw, top / fh, side / fw, side / fh


def _extract_track_crop(video_path: str, det, out_path: str) -> bool:
    x, y, w, h = _crop_box(det)
    vf = (f"crop=iw*{w:.5f}:ih*{h:.5f}:iw*{x:.5f}:ih*{y:.5f},"
          f"scale={_SHEET_TILE}:{_SHEET_TILE}:force_original_aspect_ratio=decrease,"
          f"pad={_SHEET_TILE}:{_SHEET_TILE}:(ow-iw)/2:(oh-ih)/2")
    cmd = ["ffmpeg", "-y", "-ss", f"{max(0.0, det.time_sec):.3f}", "-i", video_path,
           "-frames:v", "1", "-vf", vf, "-q:v", "3", out_path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return os.path.exists(out_path)
    except Exception as exc:
        logger.debug("track crop failed at %.2fs: %s", det.time_sec, exc)
        _safe_remove(out_path)
        return False


def _tile(paths: list[str], out_path: str) -> bool:
    from PIL import Image
    n = len(paths)
    cols = 1 if n == 1 else 2
    rows = (n + cols - 1) // cols
    gap = 8
    sheet = Image.new("RGB", (cols * _SHEET_TILE + (cols - 1) * gap, rows * _SHEET_TILE + (rows - 1) * gap), (24, 24, 24))
    for i, path in enumerate(paths):
        with Image.open(path) as im:
            sheet.paste(im.convert("RGB").resize((_SHEET_TILE, _SHEET_TILE)),
                        ((i % cols) * (_SHEET_TILE + gap), (i // cols) * (_SHEET_TILE + gap)))
    sheet.save(out_path, "JPEG", quality=88)
    return os.path.exists(out_path)


def _identity_sheet(video_path: str, person: dict, events: list[dict], detections: list) -> tuple[str | None, dict]:
    """Contact sheet of the person's tracked box at several moments; (path, evidence) or (None, reason)."""
    k = _sheet_crops()
    if k <= 0:
        return None, {"kind": "disabled"}
    picks = _track_samples(events, detections, k)
    if not picks:
        return None, {"kind": "no_track_detections"}
    stem = Path(video_path).stem
    pid = str(person.get("id", "p")).replace("/", "_")
    os.makedirs(config.TMP_DIR, exist_ok=True)
    crops = []
    for i, det in enumerate(picks):
        out = os.path.join(config.TMP_DIR, f"identity_crop_{stem}_{pid}_{i}.jpg")
        if _extract_track_crop(video_path, det, out):
            crops.append(out)
    sheet = os.path.join(config.TMP_DIR, f"identity_sheet_{stem}_{pid}.jpg")
    try:
        ok = bool(crops) and _tile(crops, sheet)
    except Exception as exc:
        logger.debug("identity sheet tiling failed: %s", exc)
        ok = False
    finally:
        for c in crops:
            _safe_remove(c)
    if not ok:
        _safe_remove(sheet)
        return None, {"kind": "sheet_failed"}
    return sheet, {"kind": "track_bbox_sheet", "crops": len(crops),
                   "track_ids": sorted({str(d.tracker_id) for d in picks}),
                   "times": [round(d.time_sec, 2) for d in picks]}


def _load_detections(video_path: str) -> list:
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        return load_sidecar_detections(video_path) or []
    except Exception as exc:
        logger.debug("no perception detections for identity sheet: %s", exc)
        return []


def _harden_person(video_path: str, person: dict, detections: list | None = None) -> dict | None:
    person = identity_trace.stamp_person(person, video_path)
    events = []
    for ev in person.get("events", []):
        if _score(ev) >= _MIN_KEEP_SCORE:
            normalized = _normalize_event_crop(ev)
            if normalized is not None:
                events.append(normalized)
    if not events:
        return None

    hardened = {**person, "events": events}
    best = max(events, key=_score)
    try:
        mid = (float(best["start"]) + float(best["end"])) / 2.0
    except (KeyError, TypeError, ValueError):
        return hardened

    old_thumb = hardened.get("thumbnail") or ""
    sheet, evidence = _identity_sheet(video_path, hardened, events, detections or [])
    if sheet:
        if old_thumb and old_thumb != sheet:
            _safe_remove(old_thumb)
        hardened["thumbnail"] = sheet
        hardened["identity_evidence"] = evidence
        return hardened
    focused_thumb = _extract_identity_thumbnail(video_path, best, mid)
    hardened["identity_evidence"] = {"kind": "crop_point_thumbnail" if focused_thumb else "none",
                                     "sheet_unavailable": evidence.get("kind")}
    if focused_thumb:
        if old_thumb and old_thumb != focused_thumb:
            _safe_remove(old_thumb)
        hardened["thumbnail"] = focused_thumb
    return hardened


def _harden_session_result(video_path: str, result: dict) -> dict:
    original_people = result.get("persons", []) or []
    hardened_people = []
    dropped_events = 0
    dropped_people = 0

    detections = _load_detections(video_path) if original_people else []
    for person in original_people:
        before = len(person.get("events", []) or [])
        hardened = _harden_person(video_path, person, detections)
        if hardened is None:
            dropped_people += 1
            dropped_events += before
            _safe_remove(person.get("thumbnail"))
            continue
        after = len(hardened.get("events", []) or [])
        dropped_events += max(0, before - after)
        hardened_people.append(hardened)

    if dropped_events or dropped_people:
        print(
            f"🧹 Quality filter: dropped {dropped_events} weak/framing-risk event(s) "
            f"and {dropped_people} athlete(s) with no usable score≥{_MIN_KEEP_SCORE} moments"
        )
        logger.info(
            "Pipeline quality filter dropped %d weak/framing-risk event(s), %d person(s)",
            dropped_events,
            dropped_people,
        )

    return {**result, "persons": hardened_people}


def install() -> None:
    """Patch analyzer.analyze_session for the production Actions entrypoint."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, "_sportreel_quality_runtime_installed", False):
        return

    original = analyzer.analyze_session

    def hardened_analyze_session(video_path: str) -> dict:
        return _harden_session_result(video_path, original(video_path))

    analyzer.analyze_session = hardened_analyze_session
    analyzer._sportreel_quality_runtime_installed = True
