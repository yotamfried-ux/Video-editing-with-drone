"""Parser-level score guard for analyzer outputs."""
from __future__ import annotations

from typing import Any

MIN_SCORE = 6
_INSTALLED_FLAG = "_sportreel_analyzer_score_guard_installed"


def _event_score(event: dict[str, Any]) -> int:
    try:
        return int(event.get("score", 0))
    except (TypeError, ValueError):
        return 0


def filter_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only events allowed into a normal draft."""
    return sorted(
        [event for event in events if _event_score(event) >= MIN_SCORE],
        key=_event_score,
        reverse=True,
    )


def filter_session_result(result: dict[str, Any]) -> dict[str, Any]:
    """Filter analyzer session result and drop people with no qualifying events."""
    persons: list[dict[str, Any]] = []
    for person in result.get("persons", []) or []:
        events = filter_events(list(person.get("events", []) or []))
        if events:
            persons.append({**person, "events": events})
    return {**result, "persons": persons}


def filter_single_result(result: dict[str, Any]) -> dict[str, Any]:
    """Filter legacy single-analysis result."""
    return {**result, "events": filter_events(list(result.get("events", []) or []))}


def install() -> None:
    """Install before orchestrator imports analyzer symbols."""
    import pipeline.stages.analyzer as analyzer

    if getattr(analyzer, _INSTALLED_FLAG, False):
        return

    original_parse_session = analyzer._parse_session
    original_parse_analysis = analyzer._parse_analysis

    def parse_session_with_score_policy(raw_text: str) -> dict[str, Any]:
        return filter_session_result(original_parse_session(raw_text))

    def parse_analysis_with_score_policy(raw_text: str) -> dict[str, Any]:
        return filter_single_result(original_parse_analysis(raw_text))

    analyzer._parse_session = parse_session_with_score_policy
    analyzer._parse_analysis = parse_analysis_with_score_policy
    setattr(analyzer, _INSTALLED_FLAG, True)
