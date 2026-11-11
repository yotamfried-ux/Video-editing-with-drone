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
# A fall is where an athlete's track is expected to end: they go under the whitewater and the detector loses them.
# When the analyzer says the action ends in a fall, a track lost up to this long before that end is the fall
# itself, not a sign the window ran past the athlete. Run 43013005072, 0160: the analyzer ended the ride at 10.8 s
# "falls off the board into the water", the track was lost 2.1 s earlier, refinement cut to 9.7 s, and final QA
# rejected the reel: "the source shows the ride continuing and ending in a fall".
FALL_TRACK_LOSS_MAX_SEC = 2.5
_FALL_TERMS = (
    "falls", "fall ", "fell", "wipeout", "wipe out", "wipes out", "wiped out", "loses balance", "lost balance",
    "loses his balance", "loses her balance", "knocked off", "bails", "goes under",
)


def ends_in_fall(event: dict[str, Any]) -> bool:
    """True when the analyzer's own account of the action's end is a fall (wipeout), for any sport.

    Reads the part of `timing_evidence` that describes the end ("...; end 5.0s: athlete falls into the
    whitewater"); without timing evidence, the event description.
    """
    evidence = str(event.get("timing_evidence") or "").lower()
    if evidence:
        marker = evidence.rfind("end ")
        text = evidence[marker:] if marker >= 0 else evidence
    else:
        text = str(event.get("description") or "").lower()
    text = " " + text + " "
    return any(term in text for term in _FALL_TERMS)
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


def _largest_gap(times: list[float]) -> tuple[float, float | None]:
    """Longest stretch inside the track with no detection: (length, second it starts at)."""
    best, at = 0.0, None
    for a, b in zip(times, times[1:]):
        if b - a > best:
            best, at = b - a, a
    return round(best, 2), (round(at, 2) if at is not None else None)


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
    # Measured, not acted on: a track that vanishes for seconds and "returns" inside the window may be another
    # person picked up under the same id (run 42891165218, 0094: the window ran 9 s past the athlete's ride into
    # another surfer's). The trace prints this so the next run shows whether such gaps separate the two.
    gap, gap_at = _largest_gap(times)
    measured = {"max_track_gap_sec": gap, "max_track_gap_start_sec": gap_at}
    new_start, new_end = start, end
    reasons: list[str] = []
    if first - start > tolerance:
        new_start = max(start, first - pad_start)
        reasons.append("athlete_not_in_frame_at_start")
    fall_kept = False
    if end - last > tolerance:
        if end - last <= FALL_TRACK_LOSS_MAX_SEC and ends_in_fall(event):
            fall_kept = True  # the athlete went under: the fall is the end of the action, keep it
        else:
            new_end = min(end, last + pad_end)
            reasons.append("track_lost_before_end")
    if fall_kept:
        measured = {**measured, "track_lost_in_fall_kept": True}
    if not reasons:
        return {**event, "window_refinement": {"status": "unchanged", "first_track_sec": round(first, 2), "last_track_sec": round(last, 2), **measured}}
    if new_end - new_start < min_window:
        return {**event, "window_refinement": {"status": "skipped_too_short", "first_track_sec": round(first, 2), "last_track_sec": round(last, 2), **measured}}

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
        **measured,
    }
    return refined
