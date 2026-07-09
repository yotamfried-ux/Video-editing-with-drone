"""Single-athlete event selection policy for Gemini analysis.

The QA loop now correctly rejects multi-person / shared-wave drafts, but real
runs showed the analyzer can still choose shared-wave windows as highlight
events. This module shifts the rule upstream: ask Gemini for clean
single-athlete source windows and defensively rewrite/drop responses that still
report shared, obstructed, or multi-person windows.
"""
from __future__ import annotations

import json
import re
from typing import Any

_INSTALLED_FLAG = "_sportreel_single_athlete_selection_policy_installed"
_PARSE_WRAPPED_FLAG = "_sportreel_single_athlete_parse_wrapped"

_SELECTION_POLICY_BLOCK = """

SINGLE-ATHLETE SELECTION POLICY — REQUIRED FOR PERSONAL REELS:
- A highlight event for a person must be a CLEAN SINGLE-ATHLETE WINDOW.
- Do NOT select shared-wave, party-wave, same-window multi-person, crowded, or obstructed moments for a single-athlete reel.
- If another surfer/rider is visibly riding the same wave, crossing through the same action window, or partially obstructing the target athlete, that full window is NOT a valid event.
- If the ride contains a clean sub-window where the target athlete is the only clear active subject for at least 6 continuous seconds, return ONLY that clean sub-window using start/end. Do not return the wider shared-wave window.
- If no clean single-athlete sub-window of at least 6 seconds exists, do not return the event at all, even if the move is stylish.
- Descriptions must explicitly describe the target athlete only. Avoid phrases such as "shared wave", "another rider", "partially obstructed", "group", or "crowded" in selected event descriptions; those indicate the candidate should be omitted.
- For each returned event, add subject_isolation: "clean". If the best moment is shared/obstructed/crowded, omit it instead of returning subject_isolation:"shared".
"""

_BAD_DESCRIPTION_PATTERNS = (
    "shared wave",
    "shares a wave",
    "party wave",
    "same wave",
    "another rider",
    "another surfer",
    "other rider",
    "other surfer",
    "partially obstructed",
    "obstructed by",
    "crowded",
    "multiple surfers",
    "multiple riders",
    "group of surfers",
    "group of riders",
)

_BAD_ISOLATION_VALUES = {
    "shared",
    "shared_wave",
    "party_wave",
    "same_window_multi_person",
    "multi_person",
    "crowded",
    "obstructed",
    "blocked",
    "false",
    "no",
}

_CLEAN_START_KEYS = ("clean_start", "clean_window_start", "single_athlete_start")
_CLEAN_END_KEYS = ("clean_end", "clean_window_end", "single_athlete_end")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(event: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _num(event.get(key))
        if value is not None:
            return value
    return None


def _description_is_shared(event: dict[str, Any]) -> bool:
    text = f"{event.get('description', '')} {event.get('notes', '')}".lower()
    return any(pattern in text for pattern in _BAD_DESCRIPTION_PATTERNS)


def _is_bad_isolation(event: dict[str, Any]) -> bool:
    for key in ("subject_isolation", "single_athlete_window", "multi_person_window", "visibility_status"):
        value = event.get(key)
        if isinstance(value, bool):
            if key in ("single_athlete_window",) and value is False:
                return True
            if key in ("multi_person_window",) and value is True:
                return True
        if isinstance(value, str) and value.strip().lower() in _BAD_ISOLATION_VALUES:
            return True
    if event.get("single_athlete_visible") is False:
        return True
    return False


def _rewrite_to_clean_subwindow(event: dict[str, Any]) -> dict[str, Any] | None:
    """Use an explicit clean sub-window if Gemini supplied one.

    This preserves otherwise good rides where only the full ride is shared, while
    still rejecting windows that cannot provide 6 continuous clean seconds.
    """
    clean_start = _first_number(event, _CLEAN_START_KEYS)
    clean_end = _first_number(event, _CLEAN_END_KEYS)
    if clean_start is None or clean_end is None:
        return None
    if clean_end - clean_start < 6.0:
        return None
    rewritten = dict(event)
    rewritten["start"] = clean_start
    rewritten["end"] = clean_end
    rewritten["subject_isolation"] = "clean"
    rewritten["description"] = str(event.get("description", "")).replace("shared wave", "clean solo section")
    return rewritten


def _event_allowed(event: dict[str, Any]) -> dict[str, Any] | None:
    if _is_bad_isolation(event) or _description_is_shared(event):
        return _rewrite_to_clean_subwindow(event)
    return event


def rewrite_raw_selection_json(raw_text: str) -> str:
    """Remove/trim shared-wave events before the existing analyzer parser runs."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    for person in data.get("persons", []) or []:
        clean_events: list[dict[str, Any]] = []
        for event in person.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            allowed = _event_allowed(event)
            if allowed is not None:
                clean_events.append(allowed)
        person["events"] = clean_events
    return json.dumps(data, ensure_ascii=False)


def install() -> None:
    from pipeline.stages import analyzer

    if not getattr(analyzer, _INSTALLED_FLAG, False):
        marker = "\nEVENT COUNT:"
        prompt = analyzer._IDENTITY_PROMPT
        if "SINGLE-ATHLETE SELECTION POLICY" not in prompt:
            if marker in prompt:
                prompt = prompt.replace(marker, _SELECTION_POLICY_BLOCK + marker, 1)
            else:
                prompt += _SELECTION_POLICY_BLOCK
            analyzer._IDENTITY_PROMPT = prompt
        setattr(analyzer, _INSTALLED_FLAG, True)

    if not getattr(analyzer, _PARSE_WRAPPED_FLAG, False):
        original_parse = analyzer._parse_session

        def parse_with_single_athlete_policy(raw_text: str) -> dict:
            return original_parse(rewrite_raw_selection_json(raw_text))

        analyzer._parse_session = parse_with_single_athlete_policy
        setattr(analyzer, _PARSE_WRAPPED_FLAG, True)
