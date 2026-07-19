"""Pure helpers for mapping QA evidence to the actual rendered event timeline."""
from __future__ import annotations

from typing import Any


def event_identity(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def rendered_event_spans(events: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Return persisted rendered offsets, with a legacy source-duration fallback."""
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for event in events or []:
        start = event.get("rendered_timeline_start")
        end = event.get("rendered_timeline_end")
        try:
            start_f = float(start)
            end_f = float(end)
        except (TypeError, ValueError):
            start_f = cursor
            try:
                duration = max(0.0, float(event.get("end")) - float(event.get("start")))
            except (TypeError, ValueError):
                duration = 0.0
            end_f = start_f + duration
        if end_f < start_f:
            start_f, end_f = end_f, start_f
        spans.append((start_f, end_f))
        cursor = end_f
    return spans


def event_index_for_qa_defect(
    events: list[dict[str, Any]],
    defect: dict[str, Any],
) -> int | None:
    """Map QA evidence by immutable event ID, then actual rendered offsets."""
    requested_id = str(
        defect.get("event_id")
        or defect.get("clip_id")
        or defect.get("source_event_id")
        or ""
    ).strip()
    if requested_id:
        for index, event in enumerate(events or []):
            if event_identity(event, index) == requested_id:
                return index
    at = defect.get("at_seconds")
    if not isinstance(at, (int, float)):
        return None
    second = float(at)
    for index, (start, end) in enumerate(rendered_event_spans(events)):
        if start <= second <= end:
            return index
    return None
