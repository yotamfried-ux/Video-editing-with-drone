"""Make PREMATURE_CUT re-edits reach the actual editor source window.

Normal reels cap a single clip for pacing. A QA repair that asks for more
follow-through must override that cap for the affected event while preserving the
original selector window across every retry.
"""
from __future__ import annotations

from typing import Any

QA_REEDIT_MAX_WINDOW_SEC = 30.0
_INSTALL_FLAG = "_sportreel_qa_reedit_window_contract_installed"
_EDITOR_FLAG = "_sportreel_qa_reedit_editor_window_installed"
_WINDOW_FLAG = "_sportreel_qa_reedit_policy_window_installed"
_SUBJECT_FLAG = "_sportreel_qa_reedit_subject_window_installed"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def has_premature_cut(defects: list[dict[str, Any]] | None) -> bool:
    return any(
        str(item.get("type") or "").upper() in {"PREMATURE_CUT", "CUT_TOO_EARLY"}
        for item in defects or []
        if isinstance(item, dict)
    )


def _event_identity(event: dict[str, Any]) -> tuple[str, float, str]:
    return (
        str(event.get("type") or ""),
        round(_num(event.get("start")), 2),
        str(event.get("description") or "")[:120],
    )


def _selector_window(event: dict[str, Any]) -> tuple[float, float]:
    """Return the immutable source window selected before the first QA retry."""
    start = _num(
        event.get("_qa_reedit_selector_start"),
        _num(event.get("selector_original_start"), _num(event.get("original_start"), _num(event.get("start")))),
    )
    end = _num(
        event.get("_qa_reedit_selector_end"),
        _num(event.get("selector_original_end"), _num(event.get("original_end"), _num(event.get("end")))),
    )
    return start, end


def _requested_bounds(event: dict[str, Any]) -> tuple[float, float, float]:
    selector_start, _selector_end = _selector_window(event)
    requested_end = max(_num(event.get("end")), _num(event.get("_qa_reedit_requested_end")))
    max_window = min(
        QA_REEDIT_MAX_WINDOW_SEC,
        max(4.0, _num(event.get("_qa_reedit_max_window_sec"), QA_REEDIT_MAX_WINDOW_SEC)),
    )
    effective_start = max(selector_start, requested_end - max_window)
    return effective_start, requested_end, min(max_window, requested_end - effective_start)


def mark_reedit_extensions(
    before_events: list[dict[str, Any]],
    fixed_events: list[dict[str, Any]],
    defects: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Mark events extended by QA without moving their selector provenance."""
    if not has_premature_cut(defects):
        return [dict(event) for event in fixed_events]
    before = {
        _event_identity(event): event
        for event in before_events or []
        if isinstance(event, dict) and not event.get("_teaser")
    }
    out: list[dict[str, Any]] = []
    for event in fixed_events or []:
        current = dict(event)
        previous = before.get(_event_identity(current))
        if previous is None:
            out.append(current)
            continue
        previous_start = _num(previous.get("start"))
        previous_end = _num(previous.get("end"))
        requested_end = _num(current.get("end"))
        if requested_end <= previous_end + 0.001 or requested_end <= previous_start:
            out.append(current)
            continue

        selector_start, selector_end = _selector_window(previous)
        current.update({
            "_qa_reedit_allow_long_cut": True,
            "_qa_reedit_selector_start": round(selector_start, 2),
            "_qa_reedit_selector_end": round(selector_end, 2),
            # Backward-compatible aliases now always mean selector provenance,
            # never the immediately preceding retry.
            "_qa_reedit_original_start": round(selector_start, 2),
            "_qa_reedit_original_end": round(selector_end, 2),
            "_qa_reedit_previous_start": round(previous_start, 2),
            "_qa_reedit_previous_end": round(previous_end, 2),
            "_qa_reedit_requested_end": round(requested_end, 2),
            "_qa_reedit_max_window_sec": QA_REEDIT_MAX_WINDOW_SEC,
            "_is_climax": True,
            "cut_adjustment_reason": "qa_premature_cut_extension",
        })
        effective_start, effective_end, effective_duration = _requested_bounds(current)
        current.update({
            "_cap_dur": round(effective_duration, 2),
            "final_cut_start": round(effective_start, 2),
            "final_cut_end": round(effective_end, 2),
        })
        out.append(current)
    return out


def prepare_reedit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return an editor-ready event whose cap reflects the QA repair request."""
    if not event.get("_qa_reedit_allow_long_cut"):
        return event
    prepared = dict(event)
    effective_start, effective_end, effective_duration = _requested_bounds(prepared)
    prepared.update({
        "start": round(effective_start, 2),
        "end": round(effective_end, 2),
        "_is_climax": True,
        "_cap_dur": round(effective_duration, 2),
        "final_cut_start": round(effective_start, 2),
        "final_cut_end": round(effective_end, 2),
        "cut_adjustment_reason": "qa_premature_cut_extension",
    })
    return prepared


def reedit_effective_window(event: dict[str, Any]) -> tuple[float, float] | None:
    if not event.get("_qa_reedit_allow_long_cut"):
        return None
    prepared = prepare_reedit_event(event)
    start = _num(prepared.get("final_cut_start"), _num(prepared.get("start")))
    end = _num(prepared.get("final_cut_end"), _num(prepared.get("end")))
    if end <= start:
        return None
    return round(start, 3), round(end, 3)


def resolve_reedit_window(event: dict[str, Any], source_duration: float) -> dict[str, Any] | None:
    """Clamp the explicit QA repair window without reapplying normal pacing."""
    repaired = reedit_effective_window(event)
    if repaired is None:
        return None
    requested_start, requested_end = repaired
    total = max(0.0, float(source_duration))
    if total < 4.0 or requested_start >= total - 2.0:
        return None
    start = max(0.0, min(requested_start, total - 4.0))
    end = min(requested_end, total)
    if end - start < 4.0:
        return None
    prepared = prepare_reedit_event(event)
    selector_start, selector_end = _selector_window(event)
    prepared.update({
        "start": round(start, 2),
        "end": round(end, 2),
        "final_cut_start": round(start, 2),
        "final_cut_end": round(end, 2),
        "original_start": round(selector_start, 2),
        "original_end": round(selector_end, 2),
        "selector_original_start": round(selector_start, 2),
        "selector_original_end": round(selector_end, 2),
        "window_validation_status": "adjusted",
        "window_validation_reason": "qa_premature_cut_extension",
        "cut_adjustment_reason": "qa_premature_cut_extension",
    })
    return prepared


def install() -> None:
    import pipeline.orchestrator as orchestrator
    import pipeline.stages.editor as editor
    import pipeline.subject_gate_policy as subject_gate_policy
    import pipeline.window_policy as window_policy

    if not getattr(orchestrator, _INSTALL_FLAG, False):
        original_apply = orchestrator._apply_qa_fixes

        def apply_with_renderable_extension(ordered_events, defects):
            fixed, changed = original_apply(ordered_events, defects)
            if not changed:
                return fixed, changed
            return mark_reedit_extensions(ordered_events, fixed, defects), changed

        orchestrator._apply_qa_fixes = apply_with_renderable_extension
        setattr(orchestrator, _INSTALL_FLAG, True)

    if not getattr(editor, _EDITOR_FLAG, False):
        original_cut = editor.cut_clip

        def cut_with_reedit_window(video_path, event, index, slowmo=False, sport="", source_info=None, session_peak=10, target_fps=None):
            return original_cut(video_path, prepare_reedit_event(event), index, slowmo, sport, source_info, session_peak, target_fps)

        editor.cut_clip = cut_with_reedit_window
        setattr(editor, _EDITOR_FLAG, True)

    if not getattr(window_policy, _WINDOW_FLAG, False):
        original_resolve = window_policy.resolve_window

        def resolve_with_reedit_window(event, source_duration):
            if event.get("_qa_reedit_allow_long_cut"):
                return resolve_reedit_window(event, source_duration)
            return original_resolve(event, source_duration)

        window_policy.resolve_window = resolve_with_reedit_window
        setattr(window_policy, _WINDOW_FLAG, True)

    if not getattr(subject_gate_policy, _SUBJECT_FLAG, False):
        original_effective = subject_gate_policy.effective_cut_window

        def effective_with_reedit_window(event):
            repaired = reedit_effective_window(event)
            return repaired if repaired is not None else original_effective(event)

        subject_gate_policy.effective_cut_window = effective_with_reedit_window
        setattr(subject_gate_policy, _SUBJECT_FLAG, True)
