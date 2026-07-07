from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

MIN_DETECTIONS = 4
MIN_VISIBLE_TRACKS = 2
MAX_PRIMARY_DOMINANCE = 0.70


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _track_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def event_window(event: dict[str, Any]) -> tuple[float, float]:
    start = event.get("final_cut_start")
    end = event.get("final_cut_end")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
        return float(start), float(end)
    start = _num(event.get("start"))
    end = _num(event.get("end"), start)
    if end < start:
        start, end = end, start
    if end - start > 11.0:
        start = round(end - 11.0, 2)
    return start, end


@lru_cache(maxsize=32)
def _sidecar_detections(source: str) -> tuple[Any, ...]:
    if not source:
        return ()
    try:
        from pipeline.perception.runtime import load_sidecar_detections
        return tuple(load_sidecar_detections(source))
    except Exception:
        return ()


def track_counts_for_event(event: dict[str, Any]) -> Counter[str]:
    source = _source(event)
    start, end = event_window(event)
    counts: Counter[str] = Counter()
    for detection in _sidecar_detections(source):
        time_sec = getattr(detection, "time_sec", None)
        track_id = _track_id(getattr(detection, "tracker_id", None))
        if track_id is None or time_sec is None:
            continue
        if start <= float(time_sec) <= end:
            counts[track_id] += 1
    return counts


def dominance_summary(event: dict[str, Any]) -> dict[str, Any] | None:
    counts = track_counts_for_event(event)
    total = sum(counts.values())
    if total < MIN_DETECTIONS or len(counts) < MIN_VISIBLE_TRACKS:
        return None
    primary, primary_count = counts.most_common(1)[0]
    dominance = primary_count / total if total else 0.0
    source = _source(event)
    start, end = event_window(event)
    return {
        "detection_count": total,
        "visible_track_count": len(counts),
        "visible_track_ids": sorted(counts.keys()),
        "track_detection_counts": dict(sorted(counts.items())),
        "primary_track_id": primary,
        "primary_track_detections": primary_count,
        "primary_track_dominance_ratio": round(dominance, 3),
        "review_required": dominance <= MAX_PRIMARY_DOMINANCE,
        "threshold": MAX_PRIMARY_DOMINANCE,
        "window": {"start": start, "end": end, "source_video": Path(source).name or source},
    }


def annotate_event(event: dict[str, Any]) -> dict[str, Any]:
    summary = dominance_summary(event)
    if not summary:
        return event
    next_event = {
        **event,
        "source_window_track_ids": summary["visible_track_ids"],
        "visible_track_ids": summary["visible_track_ids"],
        "all_visible_track_ids": summary["visible_track_ids"],
        "primary_track_id": summary["primary_track_id"],
        "primary_track_dominance_ratio": summary["primary_track_dominance_ratio"],
        "track_detection_counts": summary["track_detection_counts"],
        "perception_detection_count": summary["detection_count"],
        "review_window_policy": summary,
    }
    if next_event.get("track_id") in (None, ""):
        next_event["track_id"] = summary["primary_track_id"]
    return next_event


def annotate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [annotate_event(event) if isinstance(event, dict) else event for event in events]
