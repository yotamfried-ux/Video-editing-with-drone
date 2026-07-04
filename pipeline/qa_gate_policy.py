"""QA gate diagnostics for PQ-009."""
from __future__ import annotations

import json
import os
from typing import Any

BLOCKING_DEFECT_TYPES = {"IDENTITY_MISMATCH", "NO_VISIBLE_ACTION", "BAD_FRAMING", "DUPLICATE_MOMENT"}
_INSTALLED_FLAG = "_sportreel_qa_gate_policy_installed"


def defect_type(defect: dict[str, Any]) -> str:
    return str(defect.get("type", "")).upper()


def is_critical_defect(defect: dict[str, Any]) -> bool:
    return str(defect.get("severity", "")).lower() == "critical" and defect_type(defect) in BLOCKING_DEFECT_TYPES


def critical_defects(qa: dict[str, Any]) -> list[dict[str, Any]]:
    return [defect for defect in qa.get("defects", []) or [] if is_critical_defect(defect)]


def build_qa_diagnostics(qa: dict[str, Any], *, retry_count: int, decision: str, reel_path: str = "") -> dict[str, Any]:
    defects = []
    for defect in qa.get("defects", []) or []:
        defects.append({
            "type": defect_type(defect),
            "severity": str(defect.get("severity", "")).lower(),
            "at_seconds": defect.get("at_seconds"),
            "event_id": defect.get("event_id") or defect.get("clip_id") or defect.get("source_event_id"),
            "source": defect.get("source") or defect.get("source_video") or defect.get("video"),
            "note": defect.get("note", ""),
            "blocking": is_critical_defect(defect),
        })
    return {
        "decision": decision,
        "final_verdict": qa.get("verdict", "UNKNOWN"),
        "retry_count": int(retry_count),
        "reel_path": os.path.basename(reel_path) if reel_path else "",
        "blocking_defect_types": sorted(BLOCKING_DEFECT_TYPES),
        "critical_defect_count": len([d for d in defects if d.get("blocking")]),
        "defects": defects,
        "overall": qa.get("overall", ""),
        "engagement_score": qa.get("engagement_score"),
    }


def attach_qa_diagnostics(events: list[dict[str, Any]], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**event, "qa_gate": diagnostics} for event in events]


def _extract_qa_gate(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events or []:
        qa_gate = event.get("qa_gate")
        if isinstance(qa_gate, dict):
            return qa_gate
    return None


def _augment_metadata_file(meta_file: str, draft_name: str, qa_gate: dict[str, Any]) -> None:
    try:
        with open(meta_file, encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {}
    entry = metadata.setdefault(draft_name, {})
    entry["qa_gate"] = qa_gate
    tmp = meta_file + ".qa.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_file)


def install() -> None:
    import config
    import pipeline.orchestrator as orchestrator

    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return

    original_qa_gate = orchestrator._qa_gate
    original_save_metadata = orchestrator._save_reel_metadata

    def qa_gate_with_diagnostics(reels, events_out, sport, athlete_label, recompile):
        from pipeline.stages import analyzer
        original_check = analyzer.qa_check_reel
        qa_by_reel: dict[str, dict[str, Any]] = {}
        call_count = 0

        def tracked_qa_check(reel, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            qa = original_check(reel, *args, **kwargs)
            qa_by_reel[reel] = qa
            return qa

        analyzer.qa_check_reel = tracked_qa_check
        try:
            final, events_by_reel, flagged = original_qa_gate(reels, events_out, sport, athlete_label, recompile)
        finally:
            analyzer.qa_check_reel = original_check

        retry_count = max(0, call_count - len([r for r in reels if "_music" not in os.path.basename(r)]))
        for reel in flagged:
            qa = qa_by_reel.get(reel, {"verdict": "FAIL", "defects": [], "overall": "QA flagged without captured details"})
            decision = "flagged_manual_review" if critical_defects(qa) else "flagged_nonblocking_review"
            diagnostics = build_qa_diagnostics(qa, retry_count=retry_count, decision=decision, reel_path=reel)
            events_by_reel[reel] = attach_qa_diagnostics(events_by_reel.get(reel, []), diagnostics)
        return final, events_by_reel, flagged

    def save_metadata_with_qa(draft_name, sport, events, source_quality):
        original_save_metadata(draft_name, sport, events, source_quality)
        qa_gate = _extract_qa_gate(events)
        if qa_gate:
            _augment_metadata_file(config.REEL_METADATA_FILE, draft_name, qa_gate)

    orchestrator._qa_gate = qa_gate_with_diagnostics
    orchestrator._save_reel_metadata = save_metadata_with_qa
    setattr(orchestrator, _INSTALLED_FLAG, True)
