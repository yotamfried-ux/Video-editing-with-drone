"""Coverage-first per-athlete performance reel policy.

Every usable wave for one surfer belongs in that surfer's performance reel.
Scores control ordering and emphasis, not whether a readable ride disappears.
Whole rides are packed below the 90-second platform ceiling and split only
between rides.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

MAX_PERFORMANCE_REEL_SEC = 89.0
_SURF_TERMS = {
    "surf", "surfing", "surfer", "wave", "longboard", "shortboard",
    "cutback", "bottom_turn", "carve", "snap", "barrel", "tube_ride",
    "wave_catch", "surf_ride",
}
_FAILED_TAKEOFF_TERMS = {
    "failed takeoff", "falls immediately", "fell immediately", "immediate fall",
    "wipeout at takeoff", "misses the wave", "never stands", "does not stand",
}
_HARD_REJECT_DEFECTS = {
    "DUPLICATE_MOMENT", "IDENTITY_MISMATCH", "NO_VISIBLE_ACTION",
}
_REPAIR_WITHOUT_DROP_DEFECTS = {
    "PREMATURE_CUT", "CUT_TOO_EARLY", "UNNATURAL_SLOWMO",
}
_INSTALLED_FLAG = "_sportreel_performance_reel_policy_installed"
_ORCHESTRATOR_FLAG = "_sportreel_performance_reel_post_installed"

_SURF_PROMPT_OVERRIDE = """

SURFING COVERAGE CONTRACT — THIS OVERRIDES THE GENERIC HIGHLIGHT COUNT AND
SCORE-CUTOFF RULES ABOVE WHEN THE FOOTAGE IS SURFING:
- Detect and return EVERY DISTINCT WAVE RIDE for each surfer, not only the best
  highlights and not an arbitrary 3-8 event sample.
- A lower score changes ordering and edit emphasis; it does NOT remove a completed
  readable ride from that surfer's performance reel.
- Exclude a wave only when there is explicit hard evidence that no usable ride was
  established, such as an immediate failed takeoff, no visible/readable surfing,
  a duplicate of the same physical wave, or a different athlete.
- Use one event for the complete ride: takeoff/setup through the natural finish,
  fall, kick-out, or loss of the wave. Do not split one wave into separate turns.
- Keep separate waves as separate events so the editor can pack all whole rides
  into consecutive reels of at most 90 seconds and split only between waves.
- In the JSON, set ride_completed=true for a completed readable ride. Set
  ride_completed=false only with hard_reject_reason explaining the explicit
  failed-takeoff/no-ride evidence.
"""


class PerformanceReelPackingError(RuntimeError):
    """Raised when a complete ride cannot fit inside one platform-valid reel."""


def _text(event: dict[str, Any], activity: str = "") -> str:
    return " ".join(
        [
            activity,
            str(event.get("sport", "")),
            str(event.get("type", "")),
            str(event.get("description", "")),
            str(event.get("hard_reject_reason", "")),
        ]
    ).lower()


def is_surf_event(event: dict[str, Any], activity: str = "") -> bool:
    """Return whether an event belongs to the surfing coverage contract."""
    if event.get("ride_segment"):
        return True
    return any(term in _text(event, activity) for term in _SURF_TERMS)


def is_explicit_failed_takeoff(event: dict[str, Any], activity: str = "") -> bool:
    """Reject explicit no-ride evidence regardless of score."""
    reason = str(event.get("hard_reject_reason") or "").strip().lower()
    if reason in {"failed_takeoff", "no_ride_established", "immediate_fall"}:
        return True
    return any(term in _text(event, activity) for term in _FAILED_TAKEOFF_TERMS)


def keep_event_for_performance_reel(event: dict[str, Any], activity: str = "") -> bool:
    """Apply coverage-first admission while preserving non-surf score policy."""
    surf_event = is_surf_event(event, activity)
    if surf_event and is_explicit_failed_takeoff(event, activity):
        return False
    try:
        score = int(event.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    return score >= 6 or surf_event


def _source(event: dict[str, Any]) -> str:
    return str(
        event.get("_src")
        or event.get("source")
        or event.get("source_video")
        or event.get("video")
        or ""
    )


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_duration(event: dict[str, Any]) -> float:
    return max(0.0, _number(event.get("end")) - _number(event.get("start")))


def _slowmo_eligible(event: dict[str, Any]) -> bool:
    edit = event.get("edit") if isinstance(event.get("edit"), dict) else {}
    return bool(edit.get("slowmo")) and _number(event.get("score")) >= 8


def _group_duration(events: list[dict[str, Any]], slowmo_capable: bool, xfade_dur: float) -> float:
    if not events:
        return 0.0
    base = sum(_event_duration(event) for event in events)
    base -= xfade_dur * max(0, len(events) - 1)
    eligible = [event for event in events if slowmo_capable and _slowmo_eligible(event)]
    if eligible:
        climax = max(eligible, key=lambda event: _number(event.get("score"), 0.0))
        raw = _event_duration(climax)
        score = int(_number(climax.get("score"), 8.0))
        if score >= 9:
            slow_fraction, slow_factor = 0.50, 2.5
        else:
            slow_fraction, slow_factor = 0.40, 2.0
        base += raw * (slow_fraction * slow_factor - slow_fraction)
    return max(0.0, base)


def partition_complete_performance_reels(
    events: list[dict[str, Any]],
    slowmo_capable: bool,
    target_max: float = MAX_PERFORMANCE_REEL_SEC,
    *,
    xfade_dur: float = 0.25,
) -> list[list[dict[str, Any]]]:
    """Pack every whole ride and split only between rides before 90 seconds."""
    if not events:
        return []

    budget = min(
        MAX_PERFORMANCE_REEL_SEC,
        max(4.0, _number(target_max, MAX_PERFORMANCE_REEL_SEC)),
    )
    source_order: dict[str, int] = {}
    indexed: list[tuple[int, dict[str, Any]]] = []
    for index, event in enumerate(events):
        source = _source(event)
        source_order.setdefault(source, len(source_order))
        indexed.append((index, event))

    ordered = [
        event
        for _, event in sorted(
            indexed,
            key=lambda pair: (
                source_order[_source(pair[1])],
                _number(pair[1].get("start")),
                pair[0],
            ),
        )
    ]

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for event in ordered:
        standalone_duration = _group_duration([event], slowmo_capable, xfade_dur)
        if standalone_duration > budget:
            event_id = event.get("event_id") or event.get("id") or "unknown"
            raise PerformanceReelPackingError(
                "performance_reel_packing_blocked: complete ride "
                f"{event_id} requires {standalone_duration:.2f}s, exceeding "
                f"the {budget:.2f}s whole-wave reel budget"
            )
        proposed = [*current, event]
        if current and _group_duration(proposed, slowmo_capable, xfade_dur) > budget:
            groups.append(current)
            current = [event]
        else:
            current = proposed
    if current:
        groups.append(current)

    part_count = len(groups)
    total_wave_count = len(ordered)
    annotated: list[list[dict[str, Any]]] = []
    running_wave_index = 0
    for part_index, group in enumerate(groups, start=1):
        estimated_duration = round(_group_duration(group, slowmo_capable, xfade_dur), 3)
        part: list[dict[str, Any]] = []
        for event in group:
            running_wave_index += 1
            part.append(
                {
                    **event,
                    "performance_reel_contract": "all_usable_waves_per_athlete_v1",
                    "performance_reel_part": part_index,
                    "performance_reel_part_count": part_count,
                    "performance_reel_wave_index": running_wave_index,
                    "performance_reel_wave_count": len(group),
                    "performance_reel_total_wave_count": total_wave_count,
                    "performance_reel_estimated_part_duration": estimated_duration,
                }
            )
        annotated.append(part)
    return annotated


def _surf_events(events: list[dict[str, Any]]) -> bool:
    return any(is_surf_event(event, str(event.get("sport", ""))) for event in events)


def _filter_surf_qa_defects(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for defect in defects:
        defect_type = str(defect.get("type", "")).upper()
        if defect_type in _HARD_REJECT_DEFECTS | _REPAIR_WITHOUT_DROP_DEFECTS:
            kept.append(defect)
    return kept


def _patch_prompt_and_filters() -> None:
    from pipeline import analyzer_score_guard
    from pipeline import runtime_quality
    from pipeline.stages import analyzer, feedback

    if _SURF_PROMPT_OVERRIDE not in str(getattr(analyzer, "_IDENTITY_PROMPT", "")):
        analyzer._IDENTITY_PROMPT = str(analyzer._IDENTITY_PROMPT) + _SURF_PROMPT_OVERRIDE

    def filter_events(events: list[dict[str, Any]], activity: str = "") -> list[dict[str, Any]]:
        return [event for event in events if keep_event_for_performance_reel(event, activity)]

    def filter_session_result(result: dict[str, Any]) -> dict[str, Any]:
        activity = str(result.get("activity", ""))
        persons: list[dict[str, Any]] = []
        for person in result.get("persons", []) or []:
            events = filter_events(list(person.get("events", []) or []), activity)
            if events:
                persons.append({**person, "events": events})
        return {**result, "persons": persons}

    def filter_single_result(result: dict[str, Any]) -> dict[str, Any]:
        activity = str(result.get("activity", ""))
        return {
            **result,
            "events": filter_events(list(result.get("events", []) or []), activity),
        }

    analyzer_score_guard.filter_events = filter_events
    analyzer_score_guard.filter_session_result = filter_session_result
    analyzer_score_guard.filter_single_result = filter_single_result

    def harden_session_result(video_path: str, result: dict[str, Any]) -> dict[str, Any]:
        activity = str(result.get("activity", ""))
        hardened_people: list[dict[str, Any]] = []
        dropped_events = 0
        dropped_people = 0
        for person in result.get("persons", []) or []:
            events: list[dict[str, Any]] = []
            for event in list(person.get("events", []) or []):
                if not keep_event_for_performance_reel(event, activity):
                    dropped_events += 1
                    continue
                normalized = runtime_quality._normalize_event_crop(event)
                if normalized is None:
                    dropped_events += 1
                    continue
                events.append(normalized)
            if not events:
                dropped_people += 1
                runtime_quality._safe_remove(person.get("thumbnail"))
                continue
            hardened = {**person, "events": events}
            best = max(events, key=runtime_quality._score)
            midpoint = (_number(best.get("start")) + _number(best.get("end"))) / 2.0
            if midpoint >= 0:
                old_thumb = hardened.get("thumbnail") or ""
                focused = runtime_quality._extract_identity_thumbnail(video_path, best, midpoint)
                if focused:
                    if old_thumb and old_thumb != focused:
                        runtime_quality._safe_remove(old_thumb)
                    hardened["thumbnail"] = focused
            hardened_people.append(hardened)
        if dropped_events or dropped_people:
            print(
                "🧹 Performance coverage guard: dropped "
                f"{dropped_events} explicit no-ride/framing-risk event(s) and "
                f"{dropped_people} athlete(s) with no usable events"
            )
        return {**result, "persons": hardened_people}

    runtime_quality._harden_session_result = harden_session_result
    feedback.get_negative_feedback_hint = lambda: ""
    if hasattr(analyzer, "get_negative_feedback_hint"):
        analyzer.get_negative_feedback_hint = lambda: ""


def _patch_editor() -> None:
    from pipeline.final_duplicate_guard import remove_duplicate_events
    from pipeline.stages import editor

    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_partition = editor._partition_events

    def partition(events, slowmo_capable, target_max=MAX_PERFORMANCE_REEL_SEC):
        event_list = list(events or [])
        if not _surf_events(event_list):
            return original_partition(event_list, slowmo_capable, target_max)
        deduplicated = remove_duplicate_events(event_list)
        return partition_complete_performance_reels(
            deduplicated,
            bool(slowmo_capable),
            target_max=target_max,
            xfade_dur=float(getattr(editor, "XFADE_DUR", 0.25)),
        )

    editor._partition_events = partition
    setattr(editor, _INSTALLED_FLAG, True)


def _patch_qa_policy() -> None:
    import pipeline.qa_gate_policy as qa_policy

    if getattr(qa_policy, _INSTALLED_FLAG, False):
        return
    original_final = qa_policy.build_final_qa_diagnostics

    def final_diagnostics(qa, *, retry_count, reel_path="", was_flagged=False):
        diagnostics, blocked = original_final(
            qa,
            retry_count=retry_count,
            reel_path=reel_path,
            was_flagged=was_flagged,
        )
        if qa.get("verdict") != "PASS":
            blocked = True
            diagnostics = {
                **diagnostics,
                "decision": "blocked_review_required",
                "qa_review_required": True,
            }
            reasons = list(diagnostics.get("approval_blocked_reasons") or [])
            if not reasons:
                reasons.append("QA_FAIL: Reel did not pass final quality review.")
            diagnostics["approval_blocked_reasons"] = reasons
            review_reasons = list(diagnostics.get("review_required_reasons") or [])
            if "QA_FAIL" not in review_reasons:
                review_reasons.append("QA_FAIL")
            diagnostics["review_required_reasons"] = review_reasons
        return diagnostics, blocked

    qa_policy.build_final_qa_diagnostics = final_diagnostics
    original_patch_orchestrator = qa_policy._patch_orchestrator

    def patch_orchestrator(orchestrator: Any) -> None:
        original_patch_orchestrator(orchestrator)
        if getattr(orchestrator, _ORCHESTRATOR_FLAG, False):
            return
        original_apply = orchestrator._apply_qa_fixes

        def preserve_complete_rides(ordered_events, defects):
            events = list(ordered_events or [])
            defect_rows = list(defects or [])
            if not _surf_events(events):
                return original_apply(events, defect_rows)
            allowed = _filter_surf_qa_defects(defect_rows)
            if not allowed:
                logger.info(
                    "Preserving %d surf ride(s): QA defects require trim/review, not deletion",
                    len([event for event in events if not event.get("_teaser")]),
                )
                return events, False
            return original_apply(events, allowed)

        orchestrator._apply_qa_fixes = preserve_complete_rides
        setattr(orchestrator, _ORCHESTRATOR_FLAG, True)

    qa_policy._patch_orchestrator = patch_orchestrator
    existing = sys.modules.get("pipeline.orchestrator")
    if existing is not None:
        patch_orchestrator(existing)
    setattr(qa_policy, _INSTALLED_FLAG, True)


def install() -> None:
    """Install the coverage, packing, QA, prompt, and feedback policy."""
    _patch_prompt_and_filters()
    _patch_editor()
    _patch_qa_policy()
