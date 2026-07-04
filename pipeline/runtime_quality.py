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

logger = logging.getLogger(__name__)

_MIN_KEEP_SCORE = 6
_IDENTITY_THUMB_SIZE = 640


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


def _harden_person(video_path: str, person: dict) -> dict | None:
    events = [ev for ev in person.get("events", []) if _score(ev) >= _MIN_KEEP_SCORE]
    if not events:
        return None

    hardened = {**person, "events": events}
    best = max(events, key=_score)
    try:
        mid = (float(best["start"]) + float(best["end"])) / 2.0
    except (KeyError, TypeError, ValueError):
        return hardened

    old_thumb = hardened.get("thumbnail") or ""
    focused_thumb = _extract_identity_thumbnail(video_path, best, mid)
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

    for person in original_people:
        before = len(person.get("events", []) or [])
        hardened = _harden_person(video_path, person)
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
            f"🧹 Quality filter: dropped {dropped_events} weak event(s) "
            f"and {dropped_people} athlete(s) with no score≥{_MIN_KEEP_SCORE} moments"
        )
        logger.info(
            "Pipeline quality filter dropped %d weak event(s), %d person(s)",
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
