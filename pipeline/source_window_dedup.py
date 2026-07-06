"""Deterministic source-window deduplication for generated event candidates."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

MIN_OVERLAP_SECONDS = 2.0
MIN_OVERLAP_RATIO = 0.5


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _window(event: dict[str, Any]) -> tuple[float, float] | None:
    start = _float_value(event.get("start"))
    end = _float_value(event.get("end"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _source(event: dict[str, Any], default_source: str = "") -> str:
    return str(event.get("_src") or event.get("source_video") or event.get("video") or default_source or "")


def _score(event: dict[str, Any]) -> float:
    return _float_value(event.get("score")) or 0.0


def _duration(event: dict[str, Any]) -> float:
    w = _window(event)
    if not w:
        return 0.0
    return w[1] - w[0]


def _overlap(a: dict[str, Any], b: dict[str, Any], *, default_source: str = "") -> tuple[float, float]:
    if _source(a, default_source) != _source(b, default_source):
        return 0.0, 0.0
    aw = _window(a)
    bw = _window(b)
    if not aw or not bw:
        return 0.0, 0.0
    seconds = max(0.0, min(aw[1], bw[1]) - max(aw[0], bw[0]))
    shorter = min(aw[1] - aw[0], bw[1] - bw[0])
    return seconds, seconds / shorter if shorter > 0 else 0.0


def _beats(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    return (_score(candidate), _duration(candidate)) > (_score(incumbent), _duration(incumbent))


def dedupe_source_window_events(
    persons: list[dict[str, Any]],
    *,
    default_source: str = "",
    min_overlap_seconds: float = MIN_OVERLAP_SECONDS,
    min_overlap_ratio: float = MIN_OVERLAP_RATIO,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove lower-priority events that strongly overlap the same source window.

    This keeps the highest score / longest event and marks dropped events with a
    deterministic reason so recall remains measurable in diagnostics.
    """
    out = deepcopy(persons)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    indexed: list[tuple[int, int, dict[str, Any]]] = []
    for person_index, person in enumerate(out):
        for event_index, event in enumerate(person.get("events", []) or []):
            if isinstance(event, dict):
                indexed.append((person_index, event_index, event))

    selected_indexes: set[tuple[int, int]] = set()
    for person_index, event_index, event in sorted(indexed, key=lambda item: (_score(item[2]), _duration(item[2])), reverse=True):
        duplicate_of: dict[str, Any] | None = None
        for kept_event in kept:
            seconds, ratio = _overlap(event, kept_event, default_source=default_source)
            if seconds >= min_overlap_seconds and ratio >= min_overlap_ratio:
                duplicate_of = kept_event
                break
        if duplicate_of is not None:
            dropped_event = dict(event)
            dropped_event["selected"] = False
            dropped_event["discarded"] = True
            dropped_event["discard_cause"] = "source_window_overlap_lower_priority"
            dropped_event["duplicate_of_source_window"] = {
                "source_video": _source(duplicate_of, default_source),
                "start": duplicate_of.get("start"),
                "end": duplicate_of.get("end"),
                "score": duplicate_of.get("score"),
            }
            dropped.append(dropped_event)
            continue
        kept.append(event)
        selected_indexes.add((person_index, event_index))

    for person_index, person in enumerate(out):
        events = []
        for event_index, event in enumerate(person.get("events", []) or []):
            if not isinstance(event, dict):
                continue
            if (person_index, event_index) in selected_indexes:
                events.append(event)
        person["events"] = events
    return out, dropped


def dedupe_session(session: dict[str, Any], *, default_source: str = "") -> dict[str, Any]:
    copied = deepcopy(session)
    persons = copied.get("persons")
    if not isinstance(persons, list):
        return copied
    deduped, dropped = dedupe_source_window_events(persons, default_source=default_source)
    copied["persons"] = deduped
    diagnostics = copied.setdefault("diagnostics", {})
    if isinstance(diagnostics, dict):
        diagnostics["source_window_dedup_dropped_count"] = len(dropped)
        diagnostics["source_window_dedup_dropped_events"] = dropped
    return copied
