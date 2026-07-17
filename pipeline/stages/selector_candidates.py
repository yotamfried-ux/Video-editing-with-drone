from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sportreel.selector_candidate_events.v1"
DEFAULT_MIN_EVENT_SEC = 6.0
DEFAULT_SCORE_THRESHOLD = 6
DEFAULT_DEDUP_START_SECONDS = 2.0


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_window(event: dict[str, Any]) -> dict[str, float]:
    start = _float_value(event.get("start"), 0.0)
    end = _float_value(event.get("end"), start)
    return {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2)}


def _candidate(
    *,
    source_video: str,
    person: dict[str, Any],
    event: dict[str, Any],
    selected: bool,
    discarded: bool,
    selection_reason: str | None = None,
    discard_cause: str | None = None,
) -> dict[str, Any]:
    window = _event_window(event)
    return {
        "person_id": str(person.get("id", "person_?")),
        "person_description": str(person.get("description", "unknown")),
        "selected": selected,
        "discarded": discarded,
        "selection_reason": selection_reason if selected else None,
        "discard_cause": discard_cause if discarded else None,
        "event_type": str(event.get("type", "highlight")),
        "score": _int_value(event.get("score"), 0),
        "source_video": source_video,
        "source_window": window,
        "description": str(event.get("description", "")),
    }


def build_selector_candidate_events(
    persons: list[dict[str, Any]],
    *,
    source_video: str,
    min_event_sec: float = DEFAULT_MIN_EVENT_SEC,
    score_threshold: int = DEFAULT_SCORE_THRESHOLD,
    dedup_start_seconds: float = DEFAULT_DEDUP_START_SECONDS,
) -> dict[str, Any]:
    """Return selected and discarded selector candidates without changing selection behavior.

    This mirrors the current analyzer selection policy:
    - discard fragments shorter than ``min_event_sec``;
    - normally select score >= ``score_threshold``;
    - if a person has no score-6 events but has score >= 5, select their top two;
    - deduplicate selected events whose starts are too close, keeping the better one.
    """
    candidates: list[dict[str, Any]] = []
    for person in persons:
        raw_events = [event for event in person.get("events", []) if isinstance(event, dict)]
        eligible: list[dict[str, Any]] = []
        for event in raw_events:
            window = _event_window(event)
            if window["duration"] < min_event_sec:
                candidates.append(_candidate(
                    source_video=source_video,
                    person=person,
                    event=event,
                    selected=False,
                    discarded=True,
                    discard_cause="fragment_shorter_than_min_event_sec",
                ))
                continue
            eligible.append(event)

        good = [event for event in eligible if _int_value(event.get("score"), 0) >= score_threshold]
        selected_reason = "score_above_threshold"
        if not good and eligible:
            best_score = max(_int_value(event.get("score"), 0) for event in eligible)
            if best_score >= 5:
                good = sorted(eligible, key=lambda item: _int_value(item.get("score"), 0), reverse=True)[:2]
                selected_reason = "fallback_top_two_for_participant"

        selected_keys: set[tuple[float, str]] = set()
        selected_events: list[dict[str, Any]] = []
        for event in sorted(good, key=lambda item: _int_value(item.get("score"), 0), reverse=True):
            start = _event_window(event)["start"]
            duplicate = any(abs(start - _event_window(kept)["start"]) < dedup_start_seconds for kept in selected_events)
            if duplicate:
                candidates.append(_candidate(
                    source_video=source_video,
                    person=person,
                    event=event,
                    selected=False,
                    discarded=True,
                    discard_cause="dedup_overlap_lower_score",
                ))
                continue
            selected_events.append(event)
            selected_keys.add((start, str(event.get("type", "highlight"))))
            candidates.append(_candidate(
                source_video=source_video,
                person=person,
                event=event,
                selected=True,
                discarded=False,
                selection_reason=selected_reason,
            ))

        for event in eligible:
            key = (_event_window(event)["start"], str(event.get("type", "highlight")))
            if key in selected_keys:
                continue
            if event in good:
                continue
            candidates.append(_candidate(
                source_video=source_video,
                person=person,
                event=event,
                selected=False,
                discarded=True,
                discard_cause="score_below_selection_threshold",
            ))

    selected_count = sum(1 for item in candidates if item.get("selected"))
    discarded_count = sum(1 for item in candidates if item.get("discarded"))
    detected_athlete_registry = [
        {
            "person_id": str(person.get("id") or "person_?"),
            "source_person_id": str(person.get("id") or "person_?"),
            "person_description": str(person.get("description") or "unknown"),
            "source_video": source_video,
            "detected_event_count": len([
                event for event in person.get("events", []) or [] if isinstance(event, dict)
            ]),
            "no_output_reason": person.get("no_output_reason"),
        }
        for person in persons
        if isinstance(person, dict)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_video": source_video,
        "candidate_count": len(candidates),
        "selected_count": selected_count,
        "discarded_count": discarded_count,
        "discard_causes_available": discarded_count > 0 and all(item.get("discard_cause") for item in candidates if item.get("discarded")),
        "detected_athlete_registry": detected_athlete_registry,
        "candidates": candidates,
    }


def write_selector_candidate_events(path: str | Path, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
