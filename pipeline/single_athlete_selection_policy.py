"""Primary-actor event selection policy for Gemini analysis.

Despite the historical filename, this policy is sport-agnostic. Personal reels do
not require an empty frame: football, basketball, surfing, cycling, and other
sports naturally contain teammates, opponents, officials, and background people.
The selected action is valid when the intended athlete remains clearly attributable
from setup through outcome.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pipeline.primary_actor_policy import ambiguity_reasons

_INSTALLED_FLAG = "_sportreel_single_athlete_selection_policy_installed"
_PARSE_WRAPPED_FLAG = "_sportreel_single_athlete_parse_wrapped"

_SELECTION_POLICY_BLOCK = """

PRIMARY-ACTOR CONTINUITY POLICY — REQUIRED FOR PERSONAL REELS:
- People around the target athlete are NORMAL and are NOT a reason to omit an event.
  This applies to team sports, shared playing areas, surf lineups, races, and crowds.
- Select the complete action when the athlete performing it remains clearly identifiable
  from setup through execution and outcome, even while teammates, opponents, surfers,
  officials, or bystanders are visible.
- Block or trim an event only when the primary actor becomes ambiguous, identity switches,
  the camera starts following another athlete, the target is lost, or the target is
  materially obscured at the key moment.
- For every event return:
    primary_actor_clear: true|false
    primary_actor_confidence: 0.0-1.0
    identity_continuity: "stable"|"uncertain"|"switched"
    background_people_present: true|false
    competing_active_subjects: true|false
    target_occluded_at_key_moment: true|false
    primary_actor_reason: one short evidence-based sentence
- `background_people_present:true` is allowed when `primary_actor_clear:true`,
  `identity_continuity:"stable"`, and the target action remains readable.
- In football, attribute the event to the player executing the meaningful action. Other
  players in the play are context, not defects, unless attribution becomes uncertain.
- In surfing, another person in the lineup or background is context, not a defect. Block
  only a genuine identity mix, shared active focus, critical obstruction, or track switch.
- If only part of a wider event has reliable attribution, provide `primary_actor_start`
  and `primary_actor_end` for a complete focused sub-window of at least 6 seconds.
- Coverage requirement: every distinct athlete with at least one complete score>=6 action
  must retain at least one selected event. Do not create athlete entries for background-only
  people who never perform a meaningful action.
"""

_FOCUSED_START_KEYS = (
    "primary_actor_start",
    "focused_start",
    "clean_start",
    "clean_window_start",
    "single_athlete_start",
)
_FOCUSED_END_KEYS = (
    "primary_actor_end",
    "focused_end",
    "clean_end",
    "clean_window_end",
    "single_athlete_end",
)


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


def _rewrite_to_focused_subwindow(event: dict[str, Any]) -> dict[str, Any] | None:
    start = _first_number(event, _FOCUSED_START_KEYS)
    end = _first_number(event, _FOCUSED_END_KEYS)
    if start is None or end is None or end - start < 6.0:
        return None
    rewritten = dict(event)
    rewritten["start"] = start
    rewritten["end"] = end
    rewritten["primary_actor_clear"] = True
    rewritten["identity_continuity"] = "stable"
    rewritten["competing_active_subjects"] = False
    rewritten["target_occluded_at_key_moment"] = False
    rewritten["primary_actor_reason"] = str(
        event.get("primary_actor_reason") or "Focused sub-window preserves one attributable action."
    )
    return rewritten


def _event_allowed(event: dict[str, Any]) -> dict[str, Any] | None:
    if ambiguity_reasons(event):
        return _rewrite_to_focused_subwindow(event)
    return event


def rewrite_raw_selection_json(raw_text: str) -> str:
    """Remove only events with unresolved primary-actor ambiguity."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    for person in data.get("persons", []) or []:
        retained: list[dict[str, Any]] = []
        for event in person.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            allowed = _event_allowed(event)
            if allowed is not None:
                retained.append(allowed)
        person["events"] = retained
    return json.dumps(data, ensure_ascii=False)


def install() -> None:
    from pipeline.stages import analyzer

    if not getattr(analyzer, _INSTALLED_FLAG, False):
        marker = "\nEVENT COUNT:"
        prompt = analyzer._IDENTITY_PROMPT
        if "PRIMARY-ACTOR CONTINUITY POLICY" not in prompt:
            if marker in prompt:
                prompt = prompt.replace(marker, _SELECTION_POLICY_BLOCK + marker, 1)
            else:
                prompt += _SELECTION_POLICY_BLOCK
            analyzer._IDENTITY_PROMPT = prompt
        setattr(analyzer, _INSTALLED_FLAG, True)

    if not getattr(analyzer, _PARSE_WRAPPED_FLAG, False):
        original_parse = analyzer._parse_session

        def parse_with_primary_actor_policy(raw_text: str) -> dict:
            return original_parse(rewrite_raw_selection_json(raw_text))

        analyzer._parse_session = parse_with_primary_actor_policy
        setattr(analyzer, _PARSE_WRAPPED_FLAG, True)
