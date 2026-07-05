"""Candidate decision ledger and value feedback schema.

This module implements REAL-TRACE-001 and starts REAL-VALUE-001 without
changing selection behavior yet. It enriches per-draft diagnostics so every
rendered draft carries structured evidence for what was selected, what was
flagged/dropped, and which product-value labels apply.
"""
from __future__ import annotations

import sys
from collections import Counter
from typing import Any

_INSTALLED_FLAG = "_sportreel_candidate_ledger_installed"

VALUE_LABELS: dict[str, str] = {
    "FULL_RIDE": "Surf ride appears to include useful start, action, and outcome evidence.",
    "SOCIAL_MOMENT": "Human/social interaction that may be worth showing even if not the biggest sports action.",
    "HIGH_FIVE": "High-five, hand slap, fist bump, or equivalent interaction.",
    "BIG_TURN": "Strong turn, carve, cutback, snap, or similar peak action.",
    "FALL": "Fall, wipeout, or dramatic end to a ride.",
    "GOOD_STYLE": "Smooth, stylish, controlled movement.",
    "CLEAR_ATHLETE": "Athlete has stable track/bbox/visibility evidence.",
    "BAD_CROP": "Crop/framing evidence is missing or unsafe.",
    "WRONG_ATHLETE": "Identity evidence indicates the selected athlete may be wrong.",
    "DUPLICATE_ATHLETE": "Same athlete appears to be represented more than once.",
    "DUPLICATE_MOMENT": "Same source moment/window appears to be repeated.",
    "CUT_TOO_EARLY": "Ride/window boundary evidence suggests the moment may end too early.",
    "BORING": "Low-action or dead-time candidate.",
    "FALSE_NEGATIVE": "Operator later marks this as a missed good moment.",
}

OPERATOR_FEEDBACK_EVENTS: dict[str, str] = {
    "APPROVE": "Draft is valuable and ready to deliver.",
    "REJECT": "Draft should not be used.",
    "SEND_TO_REEDIT": "Draft has usable source value but needs a new edit.",
    "MISSING_GOOD_MOMENT": "Operator saw a valuable source moment that was not selected.",
    "WRONG_ATHLETE": "Draft contains or targets the wrong athlete.",
    "DUPLICATE_ATHLETE": "Same athlete appears in another standalone draft.",
    "MULTI_PERSON_CLIP": "Another visible athlete leaks into a single-athlete draft.",
    "CUT_TOO_EARLY": "Ride/wave was not shown through a satisfying natural finish.",
    "BAD_CROP": "Framing/crop is not acceptable.",
    "BORING": "Draft or candidate is not worth showing.",
    "FALSE_NEGATIVE": "Candidate should have been selected but was dropped or hidden.",
}

_SOCIAL_TERMS = ("high five", "high-five", "fist bump", "hand slap", "celebrat", "hug", "laugh", "smile", "cheer")
_BIG_ACTION_TERMS = ("cutback", "carve", "snap", "turn", "spray", "air", "jump", "barrel")
_STYLE_TERMS = ("style", "smooth", "flow", "controlled", "graceful")
_FALL_TERMS = ("fall", "wipeout", "crash", "bail")
_BORING_TERMS = ("dead time", "boring", "waiting", "paddle only", "no visible action")


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _source(event: dict[str, Any]) -> str:
    return str(event.get("_src") or event.get("source") or event.get("source_video") or event.get("video") or "unknown")


def _blocking_qa_defects(event: dict[str, Any]) -> list[dict[str, Any]]:
    gate = event.get("qa_gate")
    if not isinstance(gate, dict):
        return []
    out = []
    for defect in gate.get("defects", []) or []:
        if isinstance(defect, dict) and (defect.get("blocking") or str(defect.get("severity", "")).lower() == "critical"):
            out.append(defect)
    return out


def infer_value_labels(event: dict[str, Any]) -> list[str]:
    """Infer product-value labels from an event without changing behavior."""
    text = " ".join([
        str(event.get("type", "")),
        str(event.get("description", "")),
        str(event.get("note", "")),
    ]).lower()
    labels: set[str] = set()

    if event.get("ride_segment") and not event.get("ride_boundary_uncertain"):
        labels.add("FULL_RIDE")
    if any(term in text for term in _SOCIAL_TERMS):
        labels.add("SOCIAL_MOMENT")
    if "high five" in text or "high-five" in text or "hand slap" in text:
        labels.add("HIGH_FIVE")
    if any(term in text for term in _BIG_ACTION_TERMS):
        labels.add("BIG_TURN")
    if any(term in text for term in _STYLE_TERMS):
        labels.add("GOOD_STYLE")
    if any(term in text for term in _FALL_TERMS):
        labels.add("FALL")
    if any(term in text for term in _BORING_TERMS):
        labels.add("BORING")

    if event.get("track_id") or event.get("bbox_xyxy") or event.get("visible_ratio"):
        labels.add("CLEAR_ATHLETE")
    if event.get("crop_source") == "bbox" and event.get("perception_crop_usable") is False:
        labels.add("BAD_CROP")
    if event.get("identity_uncertain") or event.get("identity_mismatch"):
        labels.add("WRONG_ATHLETE")
    if event.get("ride_boundary_uncertain") or event.get("window_uncertain"):
        labels.add("CUT_TOO_EARLY")

    for duplicate in event.get("dedup_dropped_duplicates", []) or []:
        if not isinstance(duplicate, dict):
            continue
        dtype = str(duplicate.get("type") or duplicate.get("defect_type") or "").upper()
        if "DUPLICATE" in dtype:
            labels.add("DUPLICATE_MOMENT")
        if "ATHLETE" in dtype or "IDENTITY" in dtype:
            labels.add("DUPLICATE_ATHLETE")
        if dtype in {"RIDE_BOUNDARY_UNCERTAIN", "MID_RIDE_CUT", "RIDE_SPLIT"}:
            labels.add("CUT_TOO_EARLY")

    for defect in _blocking_qa_defects(event):
        dtype = str(defect.get("type") or defect.get("defect_type") or "").upper()
        if dtype in {"BAD_FRAMING", "CROP_OFF", "BAD_CROP"}:
            labels.add("BAD_CROP")
        if dtype in {"IDENTITY_MISMATCH", "IDENTITY_UNCERTAIN", "MULTI_PERSON_CLIP"}:
            labels.add("WRONG_ATHLETE")
        if dtype in {"DUPLICATE_MOMENT", "DUPLICATE_DRAFT"}:
            labels.add("DUPLICATE_MOMENT")
        if dtype in {"PREMATURE_CUT", "RIDE_BOUNDARY_UNCERTAIN", "MID_RIDE_CUT"}:
            labels.add("CUT_TOO_EARLY")

    return sorted(labels)


def _selected_decision(event: dict[str, Any]) -> tuple[str, str]:
    if event.get("_teaser"):
        return "selected_teaser", "intentional teaser/cold-open"
    if _blocking_qa_defects(event):
        return "selected_with_blocking_qa", "selected but QA metadata contains blocking defects"
    if event.get("ride_boundary_uncertain") or event.get("identity_uncertain"):
        return "selected_review_required", "selected with ride/identity uncertainty evidence"
    return "selected", "included in rendered draft"


def build_candidate_entry(event: dict[str, Any], index: int, *, draft_name: str, decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
    final_decision, final_reason = _selected_decision(event)
    if decision:
        final_decision = decision
    if reason:
        final_reason = reason
    source = _source(event)
    return {
        "candidate_id": f"{draft_name}:{_event_id(event, index)}:{index}",
        "event_id": _event_id(event, index),
        "source": source,
        "start": event.get("start"),
        "end": event.get("end"),
        "original_start": event.get("original_start"),
        "original_end": event.get("original_end"),
        "type": event.get("type", ""),
        "description": event.get("description", ""),
        "score": event.get("score"),
        "track_id": event.get("track_id"),
        "athlete_id": event.get("athlete_id") or event.get("person_id"),
        "ride_segment": bool(event.get("ride_segment")),
        "ride_fragment_count": event.get("ride_fragment_count"),
        "ride_boundary_uncertain": bool(event.get("ride_boundary_uncertain")),
        "identity_uncertain": bool(event.get("identity_uncertain")),
        "decision": final_decision,
        "decision_reason": final_reason,
        "value_labels": infer_value_labels(event),
        "qa_defects": _clean(_blocking_qa_defects(event)),
        "duplicate_evidence": _clean(event.get("dedup_dropped_duplicates", []) or []),
    }


def build_candidate_decision_ledger(draft_name: str, sport: str, events: list[dict[str, Any]], dropped_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entries = [build_candidate_entry(event, idx, draft_name=draft_name) for idx, event in enumerate(events)]
    for idx, dropped in enumerate(dropped_events or []):
        if not isinstance(dropped, dict):
            continue
        event_id = str(dropped.get("event_id") or f"dropped_{idx:03d}")
        detail = dropped.get("detail") if isinstance(dropped.get("detail"), dict) else {}
        synthetic = dict(detail) if isinstance(detail, dict) else {}
        synthetic.setdefault("event_id", event_id)
        entries.append(build_candidate_entry(
            synthetic,
            len(entries),
            draft_name=draft_name,
            decision="dropped_or_blocked",
            reason=str(dropped.get("reason") or "unknown"),
        ))

    label_counts = Counter(label for entry in entries for label in entry.get("value_labels", []))
    decision_counts = Counter(str(entry.get("decision", "unknown")) for entry in entries)
    return {
        "schema_version": "1.0",
        "draft_name": draft_name,
        "sport": sport,
        "entries": entries,
        "summary": {
            "candidate_count": len(entries),
            "decision_counts": dict(sorted(decision_counts.items())),
            "value_label_counts": dict(sorted(label_counts.items())),
        },
    }


def value_feedback_schema() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "value_labels": VALUE_LABELS,
        "operator_feedback_events": OPERATOR_FEEDBACK_EVENTS,
        "required_feedback_fields": ["draft_name", "feedback_event", "value_labels", "note", "ts"],
    }


def augment_diagnostic_artifact(artifact: dict[str, Any], events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    original_events = events if isinstance(events, list) else artifact.get("ordered_events") or []
    if not isinstance(original_events, list):
        original_events = []
    draft_name = str(artifact.get("draft_name") or "unknown_draft")
    sport = str(artifact.get("sport") or "sport")
    artifact["candidate_decision_ledger"] = build_candidate_decision_ledger(
        draft_name,
        sport,
        [event for event in original_events if isinstance(event, dict)],
        [event for event in artifact.get("dropped_events", []) or [] if isinstance(event, dict)],
    )
    artifact["value_feedback_schema"] = value_feedback_schema()
    return artifact


def _events_arg(args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[dict[str, Any]] | None:
    value = kwargs.get("events")
    if value is None and len(args) >= 3:
        value = args[2]
    if isinstance(value, list):
        return [event for event in value if isinstance(event, dict)]
    return None


def _patch_diagnostics(diagnostics: Any) -> None:
    if getattr(diagnostics, _INSTALLED_FLAG, False):
        return
    original = diagnostics.build_diagnostic_artifact

    def build_with_candidate_ledger(*args, **kwargs):
        artifact = original(*args, **kwargs)
        return augment_diagnostic_artifact(artifact, _events_arg(args, kwargs))

    diagnostics.build_diagnostic_artifact = build_with_candidate_ledger
    setattr(diagnostics, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.draft_diagnostics")
    if module is None:
        import pipeline.draft_diagnostics as module  # type: ignore[no-redef]
    _patch_diagnostics(module)
