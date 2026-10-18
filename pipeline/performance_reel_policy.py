"""Event-quality-first per-athlete performance reel policy.

Reel eligibility is earned by at least one complete, readable, worthwhile event
for the verified athlete. Accumulated duration is an editing/packing concern,
never an eligibility target and never a reason to weaken identity attribution.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

MAX_PERFORMANCE_REEL_SEC = 89.0
RENDERED_TIMELINE_RESERVED_SECONDS = 2.75
MIN_WATCHABLE_EVENT_SEC = 5.0
_SURF_TERMS = {"surf", "surfing", "surfer", "wave", "longboard", "shortboard", "cutback", "bottom_turn", "carve", "snap", "barrel", "tube_ride", "wave_catch", "surf_ride"}
_FAILED_TAKEOFF_TERMS = {"failed takeoff", "falls immediately", "fell immediately", "immediate fall", "wipeout at takeoff", "misses the wave", "never stands", "does not stand"}
_HARD_REJECT_DEFECTS = {"DUPLICATE_MOMENT", "IDENTITY_MISMATCH", "NO_VISIBLE_ACTION"}
_REPAIR_WITHOUT_DROP_DEFECTS = {"PREMATURE_CUT", "CUT_TOO_EARLY", "UNNATURAL_SLOWMO"}
_INSTALLED_FLAG = "_sportreel_performance_reel_policy_installed"
_ORCHESTRATOR_FLAG = "_sportreel_performance_reel_post_installed"

_SURF_PROMPT_OVERRIDE = """

EVENT-QUALITY / SURFING CONTRACT — THIS OVERRIDES GENERIC EVENT-COUNT OR REEL-DURATION TARGETS:
- Reel eligibility is event-first: ONE complete, readable, worthwhile ride is enough to make a surfer eligible. Never require an accumulated reel duration or multiple events.
- Detect every distinct usable wave ride. A beginner's clean, controlled ride can be worthwhile even without advanced maneuvers; an advanced surfer's worthwhile ride may be defined by execution of stronger maneuvers. Judge quality relative to the athlete/session while still requiring visible action.
- Evaluate the ride itself: useful ride time, control/execution, meaningful action/outcome, visual readability and composition. Duration is only a watchability floor, not the quality score.
- A lower score changes ordering/emphasis; it must not make the system borrow another athlete's action to fill time.
- Identity is a hard gate. Never include an action attributable to another athlete merely to reach a target duration. Ambiguous identity must stay out/review-required.
- Another surfer may be visible or active on the same wave only when the target remains the clear continuous primary actor and the selected actions are attributable to that target.
- Use one event for the complete ride: setup/takeoff through natural finish, fall, kick-out, or loss of wave. Do not pad a tiny fragment to satisfy duration.
- A real event shorter than 5 seconds is below the absolute watchability floor and must not be stretched into eligibility.
- Set action_complete=true and action_readable=true when those facts are supported. Set ride_completed=true for a completed readable ride. Use explicit hard_reject_reason for failed takeoff/no ride/identity evidence.
"""

class PerformanceReelPackingError(RuntimeError):
    pass

def _number(value: Any, default: float = 0.0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return default

def _text(event: dict[str, Any], activity: str = "") -> str:
    return " ".join([activity, str(event.get("sport", "")), str(event.get("type", "")), str(event.get("description", "")), str(event.get("hard_reject_reason", ""))]).lower()

def is_surf_event(event: dict[str, Any], activity: str = "") -> bool:
    return bool(event.get("ride_segment")) or any(term in _text(event, activity) for term in _SURF_TERMS)

def is_explicit_failed_takeoff(event: dict[str, Any], activity: str = "") -> bool:
    reason = str(event.get("hard_reject_reason") or "").strip().lower()
    return reason in {"failed_takeoff", "no_ride_established", "immediate_fall"} or any(term in _text(event, activity) for term in _FAILED_TAKEOFF_TERMS)

def _identity_verified(event: dict[str, Any]) -> bool:
    # Explicit negative/ambiguous evidence always wins. Legacy events without the
    # newer evidence fields remain admissible so this policy does not silently
    # delete historical detections; upstream primary-actor policy still applies.
    if event.get("primary_actor_clear") is False: return False
    if str(event.get("identity_continuity") or "").lower() in {"unstable", "ambiguous", "switched", "mismatch"}: return False
    if "primary_actor_confidence" in event and _number(event.get("primary_actor_confidence")) < 0.75: return False
    if str(event.get("hard_reject_reason") or "").lower() in {"identity_mismatch", "identity_switch", "target_lost"}: return False
    return True

def evaluate_event_quality(event: dict[str, Any], activity: str = "") -> dict[str, Any]:
    """Return a sport-aware, duration-independent eligibility verdict for one event."""
    reasons: list[str] = []
    duration = max(0.0, _number(event.get("end")) - _number(event.get("start")))
    if not _identity_verified(event): reasons.append("identity_not_verified")
    if duration < MIN_WATCHABLE_EVENT_SEC: reasons.append("too_short")
    if event.get("action_complete") is False or (is_surf_event(event, activity) and is_explicit_failed_takeoff(event, activity)):
        reasons.append("incomplete_action")
    if event.get("action_readable") is False: reasons.append("unreadable_action")
    try: score = int(event.get("score", 0))
    except (TypeError, ValueError): score = 0
    surf = is_surf_event(event, activity)
    # Surf coverage preserves a complete readable established ride even when the
    # athlete-relative score is modest. Other sports require the quality gate.
    quality_ok = (surf and not is_explicit_failed_takeoff(event, activity)) or score >= 6
    if not quality_ok: reasons.append("quality_below_threshold")
    return {"clip_worthy": not reasons, "reasons": reasons, "duration": duration, "score": score, "sport": "surfing" if surf else (activity or "unknown")}

def keep_event_for_performance_reel(event: dict[str, Any], activity: str = "") -> bool:
    return bool(evaluate_event_quality(event, activity)["clip_worthy"])

def _no_output_reason_for_person(person: dict[str, Any], activity: str) -> str:
    existing = str(person.get("no_output_reason") or "").strip()
    if existing: return existing
    events = [e for e in person.get("events", []) or [] if isinstance(e, dict)]
    if not events: return "no_complete_action"
    verdicts = [evaluate_event_quality(e, activity) for e in events]
    if any("identity_not_verified" in v["reasons"] for v in verdicts): return "identity_not_verified"
    if all(any(r in v["reasons"] for r in ("too_short", "incomplete_action", "unreadable_action")) for v in verdicts): return "no_complete_action"
    return "quality_below_threshold"

def filter_session_result_for_performance_reel(result: dict[str, Any]) -> dict[str, Any]:
    activity = str(result.get("activity", ""))
    people, registry = [], []
    for index, raw_person in enumerate(result.get("persons", []) or []):
        if not isinstance(raw_person, dict): continue
        person = dict(raw_person)
        original = [e for e in person.get("events", []) or [] if isinstance(e, dict)]
        events = [e for e in original if keep_event_for_performance_reel(e, activity)]
        person_id = str(person.get("id") or f"detected_person_{index:03d}")
        person["id"], person["events"] = person_id, events
        reason = None if events else _no_output_reason_for_person(person, activity)
        if reason: person["no_output_reason"] = reason
        people.append(person)
        registry.append({"person_id": person_id, "description": str(person.get("description") or "unknown athlete"), "detected_action_count": len(original), "retained_action_count": len(events), "no_output_reason": reason})
    return {**result, "persons": people, "detected_athlete_registry": registry}

def should_prepend_teaser(events: list[dict[str, Any]]) -> bool:
    return not any(str(e.get("performance_reel_contract") or "") == "all_usable_waves_per_athlete_v1" for e in events or [] if isinstance(e, dict))

def _source(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")
def _event_duration(event: dict[str, Any]) -> float:
    return max(0.0, _number(event.get("end")) - _number(event.get("start")))
def _slowmo_eligible(event: dict[str, Any]) -> bool:
    edit = event.get("edit") if isinstance(event.get("edit"), dict) else {}
    return bool(edit.get("slowmo")) and _number(event.get("score")) >= 8
def _group_duration(events: list[dict[str, Any]], slowmo_capable: bool, xfade_dur: float) -> float:
    if not events: return 0.0
    base = sum(_event_duration(e) for e in events) - xfade_dur * max(0, len(events)-1)
    eligible = [e for e in events if slowmo_capable and _slowmo_eligible(e)]
    if eligible:
        climax = max(eligible, key=lambda e: _number(e.get("score")))
        raw, score = _event_duration(climax), int(_number(climax.get("score"), 8))
        frac, factor = (0.50, 2.5) if score >= 9 else (0.40, 2.0)
        base += raw * (frac * factor - frac)
    return max(0.0, base)
def partition_complete_performance_reels(events: list[dict[str, Any]], slowmo_capable: bool, target_max: float = MAX_PERFORMANCE_REEL_SEC, *, xfade_dur: float = 0.25) -> list[list[dict[str, Any]]]:
    if not events: return []
    requested = min(MAX_PERFORMANCE_REEL_SEC, max(4.0, _number(target_max, MAX_PERFORMANCE_REEL_SEC)))
    budget = max(4.0, requested - RENDERED_TIMELINE_RESERVED_SECONDS)
    source_order, indexed = {}, []
    for i, e in enumerate(events):
        source_order.setdefault(_source(e), len(source_order)); indexed.append((i,e))
    ordered = [e for _,e in sorted(indexed, key=lambda p:(source_order[_source(p[1])], _number(p[1].get("start")), p[0]))]
    groups, current = [], []
    for e in ordered:
        standalone = _group_duration([e], slowmo_capable, xfade_dur)
        if standalone > budget: raise PerformanceReelPackingError(f"performance_reel_packing_blocked: complete event requires {standalone:.2f}s, exceeding {budget:.2f}s budget")
        proposed = [*current,e]
        if current and _group_duration(proposed, slowmo_capable, xfade_dur) > budget: groups.append(current); current=[e]
        else: current=proposed
    if current: groups.append(current)
    return groups

# Preserve runtime monkey-patch integration expected by the existing pipeline.
def install_performance_reel_policy() -> None:
    """Install prompt/filter/packing overrides into loaded pipeline modules."""
    analyzer = sys.modules.get("pipeline.stages.analyzer")
    if analyzer is not None and not getattr(analyzer, _INSTALLED_FLAG, False):
        if hasattr(analyzer, "_IDENTITY_PROMPT") and _SURF_PROMPT_OVERRIDE not in analyzer._IDENTITY_PROMPT:
            analyzer._IDENTITY_PROMPT += _SURF_PROMPT_OVERRIDE
        original_parse = getattr(analyzer, "_parse_session", None)
        if callable(original_parse):
            def parse_with_policy(raw_text: str): return filter_session_result_for_performance_reel(original_parse(raw_text))
            analyzer._parse_session = parse_with_policy
        setattr(analyzer, _INSTALLED_FLAG, True)
