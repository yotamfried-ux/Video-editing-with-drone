"""Primary-athlete event selection policy for Gemini analysis.

Despite the historical filename, this policy is sport-agnostic. Personal reels do
not require an empty frame: football, basketball, surfing, cycling, and other
sports naturally contain teammates, opponents, officials, and background people.
The selected action is valid when the intended athlete remains the clear center
of the edit and is attributable from setup through outcome.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pipeline.primary_actor_policy import ambiguity_reasons, normalize_focused_subwindow_evidence

_INSTALLED_FLAG = "_sportreel_single_athlete_selection_policy_installed"
_PARSE_WRAPPED_FLAG = "_sportreel_single_athlete_parse_wrapped"

_SELECTION_POLICY_BLOCK = """

PRIMARY-ATHLETE CONTINUITY POLICY — REQUIRED FOR PERSONAL REELS:
- A personal reel is CENTERED ON ONE TARGET ATHLETE; it does not require only one
  visible or active person. People around the target athlete are NORMAL and are NOT
  a reason to omit an event. This applies to team sports, shared playing areas, surf
  lineups, two surfers on the same wave, races, and crowds.
- Select the complete action when the athlete performing it remains clearly identifiable
  from setup through execution and outcome, even while teammates, opponents, surfers,
  officials, or bystanders are visible or actively participating in the same play.
- Block or trim an event only when the primary athlete becomes ambiguous, identity switches,
  the camera starts following another athlete, the target is lost, or the target is
  materially obscured at the key moment.
- Classify the top-level source_profile as one of:
    raw_continuous_footage | edited_sports_compilation | single_athlete_session | multi_athlete_event
- For every event return:
    primary_actor_clear: true|false
    primary_actor_confidence: 0.0-1.0
    identity_continuity: "stable"|"uncertain"|"switched"
    background_people_present: true|false
    competing_active_subjects: true|false
    target_occluded_at_key_moment: true|false
    primary_actor_reason: one short evidence-based sentence
- `background_people_present:true` and `competing_active_subjects:true` are allowed when
  `primary_actor_clear:true`, `identity_continuity:"stable"`, and the target athlete's
  action remains readable and central.
- In football, attribute the event to the player executing the meaningful action. Other
  players in the play are expected context, not defects, unless attribution becomes uncertain.
- In surfing, another surfer may wait nearby, cross behind, or ride the same wave. Keep the
  full wave when the target surfer remains the central, continuous subject. Block only a
  genuine identity mix, target loss, critical obstruction, or camera/track switch.
- If only part of a wider event has reliable attribution, provide `primary_actor_start`
  and `primary_actor_end` for a complete focused sub-window of at least 6 seconds.
- Coverage requirement: every distinct athlete with at least one complete score>=6 action
  must retain at least one selected event. Do not create athlete entries for background-only
  people who never perform a meaningful action.
- When an athlete has no retained event, return person-level no_output_reason as one of:
    no_complete_action | quality_below_threshold | identity_uncertain | target_not_trackable
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
_EVENT_EVIDENCE_KEYS = (
    "primary_actor_clear",
    "primary_actor_confidence",
    "identity_continuity",
    "background_people_present",
    "competing_active_subjects",
    "target_occluded_at_key_moment",
    "primary_actor_reason",
    "primary_actor_start",
    "primary_actor_end",
    "primary_actor_evidence_scope",
    "broad_window_ambiguity_reasons",
    "target_track_id",
    "primary_track_id",
    "athlete_track_id",
    "track_id",
)
_SOURCE_PROFILES = {
    "raw_continuous_footage",
    "edited_sports_compilation",
    "single_athlete_session",
    "multi_athlete_event",
}


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
    rewritten = normalize_focused_subwindow_evidence(event)
    rewritten["start"] = start
    rewritten["end"] = end
    rewritten["primary_actor_reason"] = str(
        event.get("primary_actor_reason") or "Focused sub-window preserves one attributable action."
    )
    return rewritten


def _event_allowed(event: dict[str, Any]) -> dict[str, Any] | None:
    if ambiguity_reasons(event):
        return _rewrite_to_focused_subwindow(event)
    return event


def _load_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def rewrite_raw_selection_json(raw_text: str) -> str:
    """Remove only events with unresolved primary-athlete ambiguity."""
    data = _load_json(raw_text)
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


def _event_match(parsed_event: dict[str, Any], raw_event: dict[str, Any]) -> bool:
    p_start = _num(parsed_event.get("start"))
    p_end = _num(parsed_event.get("end"))
    r_start = _num(raw_event.get("start"))
    r_end = _num(raw_event.get("end"))
    if None in (p_start, p_end, r_start, r_end):
        return False
    same_type = str(parsed_event.get("type") or "") == str(raw_event.get("type") or "")
    return same_type and abs(p_start - r_start) <= 0.05 and abs(p_end - r_end) <= 0.05


def _enrich_parsed_session(parsed: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    raw_people = {
        str(person.get("id") or ""): person
        for person in raw.get("persons", []) or []
        if isinstance(person, dict)
    }
    for person in parsed.get("persons", []) or []:
        person_id = str(person.get("id") or "")
        raw_person = raw_people.get(person_id, {})
        person["no_output_reason"] = raw_person.get("no_output_reason")
        person["identity_confidence"] = raw_person.get("identity_confidence")
        raw_events = [event for event in raw_person.get("events", []) or [] if isinstance(event, dict)]
        for event in person.get("events", []) or []:
            event["person_id"] = person_id
            event["person_description"] = str(person.get("description") or "")
            match = next((candidate for candidate in raw_events if _event_match(event, candidate)), None)
            if match:
                for key in _EVENT_EVIDENCE_KEYS:
                    if key in match:
                        event[key] = match[key]
    profile = str(raw.get("source_profile") or "").strip().lower()
    parsed["source_profile"] = profile if profile in _SOURCE_PROFILES else "raw_continuous_footage"
    return parsed


def install() -> None:
    from pipeline.stages import analyzer

    if not getattr(analyzer, _INSTALLED_FLAG, False):
        marker = "\nEVENT COUNT:"
        prompt = analyzer._IDENTITY_PROMPT
        if "PRIMARY-ATHLETE CONTINUITY POLICY" not in prompt:
            if marker in prompt:
                prompt = prompt.replace(marker, _SELECTION_POLICY_BLOCK + marker, 1)
            else:
                prompt += _SELECTION_POLICY_BLOCK
            analyzer._IDENTITY_PROMPT = prompt
        setattr(analyzer, _INSTALLED_FLAG, True)

    if not getattr(analyzer, _PARSE_WRAPPED_FLAG, False):
        original_parse = analyzer._parse_session

        def parse_with_primary_actor_policy(raw_text: str) -> dict:
            rewritten = rewrite_raw_selection_json(raw_text)
            raw = _load_json(rewritten)
            return _enrich_parsed_session(original_parse(rewritten), raw)

        analyzer._parse_session = parse_with_primary_actor_policy
        setattr(analyzer, _PARSE_WRAPPED_FLAG, True)
