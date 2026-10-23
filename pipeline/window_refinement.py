"""Trim an event window to the footage where its tracked athlete is actually in frame.

The LLM names an event's start/end seconds; the perception sidecar knows, frame by frame, when the
athlete's track exists. Where the two disagree by more than the sampling gap — the athlete is not yet
in frame at `start`, or the track is gone well before `end` — the window is cut back to the tracked
span. It only ever shrinks a window, so a wrong or sparse sidecar can cost footage but never invents
any, and an event is left untouched when the trimmed result would be too short to publish.
"""
from __future__ import annotations

import os
from statistics import median
from typing import Any, Iterable

DEFAULT_LOST_TOLERANCE_SEC = 1.5
DEFAULT_PAD_START_SEC = 0.5
DEFAULT_PAD_END_SEC = 1.0
DEFAULT_MIN_WINDOW_SEC = 5.0
MIN_TRACK_DETECTIONS = 3


def enabled() -> bool:
    return os.getenv("WINDOW_REFINE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _track_times(detections: Iterable[Any], track_id: str, lo: float, hi: float) -> list[float]:
    times = sorted(
        float(d.time_sec)
        for d in detections
        if d.tracker_id is not None and str(d.tracker_id) == track_id and lo <= float(d.time_sec) <= hi
    )
    return times


def _sampling_gap(times: list[float]) -> float:
    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    return median(gaps) if gaps else 0.0


def refine_event_window(
    event: dict[str, Any],
    detections: list[Any],
    *,
    lost_tolerance: float = DEFAULT_LOST_TOLERANCE_SEC,
    pad_start: float = DEFAULT_PAD_START_SEC,
    pad_end: float = DEFAULT_PAD_END_SEC,
    min_window: float = DEFAULT_MIN_WINDOW_SEC,
) -> dict[str, Any]:
    """Return a copy of `event` with start/end cut to its target track's visible span."""
    track_id = event.get("target_track_id")
    start, end = _num(event.get("start")), _num(event.get("end"))
    if track_id is None or start is None or end is None or end <= start:
        return event
    # Look a little beyond the window so a track that is present right at an edge is not mistaken
    # for a missing one.
    times = _track_times(detections, str(track_id), start - 1.0, end + 1.0)
    if len(times) < MIN_TRACK_DETECTIONS:
        return event

    tolerance = max(lost_tolerance, 3.0 * _sampling_gap(times))
    first, last = times[0], times[-1]
    new_start, new_end = start, end
    reasons: list[str] = []
    if first - start > tolerance:
        new_start = max(start, first - pad_start)
        reasons.append("athlete_not_in_frame_at_start")
    if end - last > tolerance:
        new_end = min(end, last + pad_end)
        reasons.append("track_lost_before_end")
    if not reasons:
        return {**event, "window_refinement": {"status": "unchanged", "first_track_sec": round(first, 2), "last_track_sec": round(last, 2)}}
    if new_end - new_start < min_window:
        return {**event, "window_refinement": {"status": "skipped_too_short", "first_track_sec": round(first, 2), "last_track_sec": round(last, 2)}}

    refined = {
        **event,
        "start": round(new_start, 2),
        "end": round(new_end, 2),
        "llm_start": round(start, 2),
        "llm_end": round(end, 2),
        "window_refined": True,
    }
    # Phase times that point into the part just removed would make window_policy.resolve_window
    # stretch the window straight back out to them.
    clamped: dict[str, float] = {}
    setup = _num(event.get("setup_start"))
    if setup is not None and setup < new_start:
        refined["setup_start"] = None
        clamped["setup_start"] = setup
    outcome = _num(event.get("outcome_end"))
    if outcome is not None and outcome > new_end:
        refined["outcome_end"] = round(new_end, 2)
        clamped["outcome_end"] = outcome
    refined["window_refinement"] = {
        "status": "trimmed",
        "reasons": reasons,
        "first_track_sec": round(first, 2),
        "last_track_sec": round(last, 2),
        "start_shift": round(new_start - start, 2),
        "end_shift": round(new_end - end, 2),
        "clamped_phase_times": clamped,
    }
    return refined
