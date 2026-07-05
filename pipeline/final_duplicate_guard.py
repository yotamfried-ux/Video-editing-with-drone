"""Final ordered-event duplicate guard for real-output duplicate prevention."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_final_duplicate_guard_installed"
_EDITOR_WRAPPED = "_sportreel_final_duplicate_guard_wrapped_editor"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _event_id(event: dict[str, Any], fallback: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{fallback:03d}")


def _src(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "")


def _fingerprint(event: dict[str, Any]) -> str:
    for key in ("event_fingerprint", "fingerprint", "visual_hash", "clip_hash"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    start = max(_num(a.get("start")), _num(b.get("start")))
    end = min(_num(a.get("end")), _num(b.get("end")))
    overlap = max(0.0, end - start)
    if overlap <= 0:
        return 0.0
    dur = min(max(0.01, _num(a.get("end")) - _num(a.get("start"))), max(0.01, _num(b.get("end")) - _num(b.get("start"))))
    return overlap / dur


def _duplicate_reason(candidate: dict[str, Any], kept: dict[str, Any]) -> str | None:
    if candidate.get("_teaser") or kept.get("_teaser"):
        return None
    if _fingerprint(candidate) and _fingerprint(candidate) == _fingerprint(kept):
        return "same_fingerprint"
    cid = candidate.get("event_id") or candidate.get("id")
    kid = kept.get("event_id") or kept.get("id")
    if cid and kid and str(cid) == str(kid):
        return "same_event_id"
    if _src(candidate) and _src(candidate) == _src(kept) and _overlap_ratio(candidate, kept) >= 0.55:
        return "same_source_time_overlap"
    c_track = candidate.get("track_id")
    k_track = kept.get("track_id")
    if c_track is not None and str(c_track) == str(k_track) and _overlap_ratio(candidate, kept) >= 0.70:
        return "same_track_time_overlap"
    return None


def _quality(event: dict[str, Any]) -> float:
    visible = max(0.0, min(1.0, _num(event.get("visible_ratio"), 1.0)))
    confidence = max(0.0, min(1.0, _num(event.get("perception_confidence"), _num(event.get("confidence"), 1.0))))
    return _num(event.get("score")) * 0.75 + visible * 1.5 + confidence


def _drop_detail(event: dict[str, Any], reason: str, kept: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "reason": reason,
        "event_id": _event_id(event, index),
        "source": _src(event),
        "start": event.get("start"),
        "end": event.get("end"),
        "kept_event_id": kept.get("event_id") or kept.get("id"),
        "kept_source": _src(kept),
        "kept_start": kept.get("start"),
        "kept_end": kept.get("end"),
        "defect_type": "DUPLICATE_MOMENT",
        "blocking": True,
    }


def remove_duplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        matched_index = None
        matched_reason = None
        for kidx, kept_event in enumerate(kept):
            reason = _duplicate_reason(event, kept_event)
            if reason:
                matched_index = kidx
                matched_reason = reason
                break
        if matched_index is None:
            kept.append(event)
            continue
        kept_event = kept[matched_index]
        if _quality(event) > _quality(kept_event):
            detail = _drop_detail(kept_event, matched_reason or "duplicate_moment", event, matched_index)
            replacement = {**event, "dedup_dropped_duplicates": [*(event.get("dedup_dropped_duplicates", []) or []), detail]}
            kept[matched_index] = replacement
        else:
            detail = _drop_detail(event, matched_reason or "duplicate_moment", kept_event, idx)
            kept[matched_index] = {**kept_event, "dedup_dropped_duplicates": [*(kept_event.get("dedup_dropped_duplicates", []) or []), detail]}
    return kept


def _patch_editor(editor: Any) -> None:
    if getattr(editor, _INSTALLED_FLAG, False):
        return
    original_partition = editor._partition_events
    original_narrative = editor._narrative_order

    def partition_without_duplicates(events, slowmo_capable, target_max=editor.TARGET_REEL_MAX):
        return original_partition(remove_duplicate_events(events), slowmo_capable, target_max)

    def narrative_without_duplicates(events):
        ordered = original_narrative(remove_duplicate_events(events))
        return remove_duplicate_events(ordered)

    editor._partition_events = partition_without_duplicates
    editor._narrative_order = narrative_without_duplicates
    setattr(editor, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.stages.editor")
    if module is not None:
        _patch_editor(module)
        return
    import pipeline.stages.editor as editor
    _patch_editor(editor)
