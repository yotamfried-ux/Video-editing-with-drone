#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

LONG_VIDEO_RE = re.compile(r"Long video:\s*(?P<name>.+)$")
_NONBLOCKING_FINAL_DECISIONS = {"passed", "passed_after_reedit", "failed_nonblocking"}
_BLOCKING_FINAL_DECISIONS = {"blocked_review_required", "flagged_nonblocking_review"}


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _source_from_log(log_path: Path) -> str | None:
    if not log_path.exists():
        return None
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = LONG_VIDEO_RE.search(line)
        if match:
            return match.group("name").strip()
    return None


def _window_value(event: dict[str, Any], final_key: str, source_key: str) -> Any:
    value = event.get(final_key)
    return value if isinstance(value, (int, float)) else event.get(source_key)


def _first_numeric(event: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = event.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def _event_source(event: dict[str, Any], default_source: str | None) -> tuple[str | None, str | None]:
    raw = event.get("source_path") or event.get("_src") or event.get("source_video") or event.get("source") or default_source
    if not raw:
        return None, None
    return Path(str(raw)).name, str(raw)


def _event_window(event: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    selector_start = _first_numeric(event, (
        "selector_original_start", "_qa_reedit_selector_start",
        "_qa_reedit_original_start", "original_start", "start",
    ))
    selector_end = _first_numeric(event, (
        "selector_original_end", "_qa_reedit_selector_end",
        "_qa_reedit_original_end", "original_end", "end",
    ))
    start = _window_value(event, "final_cut_start", "start")
    end = _window_value(event, "final_cut_end", "end")
    source_video, source_path = _event_source(event, default_source)
    return {
        "source_video": source_video,
        "source_path": source_path,
        "event_type": event.get("type", ""),
        "start": start,
        "end": end,
        "duration": (float(end) - float(start)) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else None,
        "original_start": selector_start,
        "original_end": selector_end,
        "selector_original_start": selector_start,
        "selector_original_end": selector_end,
        "final_cut_start": event.get("final_cut_start"),
        "final_cut_end": event.get("final_cut_end"),
        "score": event.get("score"),
        "description": event.get("description", ""),
        "edit": event.get("edit", {}),
        "person_id": event.get("person_id"),
        "source_person_id": event.get("source_person_id"),
        "chunk_person_id": event.get("chunk_person_id"),
        "athlete_id": event.get("athlete_id"),
        "athlete_canonical_key": event.get("athlete_canonical_key"),
        "athlete_canonical_evidence_status": event.get("athlete_canonical_evidence_status"),
        "athlete_duplicate_group": event.get("athlete_duplicate_group"),
        "track_id": event.get("track_id") or event.get("target_track_id") or event.get("primary_track_id"),
        "chunk_index": event.get("chunk_index"),
        "chunk_source_start": event.get("chunk_source_start"),
        "chunk_source_end": event.get("chunk_source_end"),
        "chunk_local_start": event.get("chunk_local_start"),
        "chunk_local_end": event.get("chunk_local_end"),
        "timestamp_encoding": event.get("timestamp_encoding"),
        "timestamp_basis": event.get("timestamp_basis"),
        "timestamp_recovered": event.get("timestamp_recovered"),
        "timestamp_clamped": event.get("timestamp_clamped"),
        "raw_chunk_start": event.get("raw_chunk_start"),
        "raw_chunk_end": event.get("raw_chunk_end"),
        "interpreted_chunk_start": event.get("interpreted_chunk_start"),
        "interpreted_chunk_end": event.get("interpreted_chunk_end"),
        "cut_adjustment_reason": event.get("cut_adjustment_reason"),
        "window_validation_status": event.get("window_validation_status"),
        "window_validation_reason": event.get("window_validation_reason"),
        "selection_rescue": event.get("selection_rescue"),
        "qa_reedit_allow_long_cut": bool(event.get("_qa_reedit_allow_long_cut")),
        "qa_reedit_selector_start": event.get("_qa_reedit_selector_start"),
        "qa_reedit_selector_end": event.get("_qa_reedit_selector_end"),
        "qa_reedit_previous_start": event.get("_qa_reedit_previous_start"),
        "qa_reedit_previous_end": event.get("_qa_reedit_previous_end"),
        "qa_reedit_requested_end": event.get("_qa_reedit_requested_end"),
        "qa_reedit_max_window_sec": event.get("_qa_reedit_max_window_sec"),
        "subject_isolation_gate": event.get("subject_isolation_gate"),
        "multi_person_clip_gate": event.get("multi_person_clip_gate"),
    }


def _qa_gate(meta: dict[str, Any]) -> dict[str, Any] | None:
    qa_gate = meta.get("qa_gate") if isinstance(meta.get("qa_gate"), dict) else None
    artifact = meta.get("diagnostic_artifact") if isinstance(meta.get("diagnostic_artifact"), dict) else None
    artifact_qa = artifact.get("qa") if isinstance(artifact, dict) and isinstance(artifact.get("qa"), dict) else None
    return qa_gate or artifact_qa


def _blocking_defect_codes(qa_gate: dict[str, Any] | None) -> list[str]:
    if not qa_gate:
        return []
    reasons = qa_gate.get("review_required_reasons")
    if isinstance(reasons, list) and reasons:
        return [str(item) for item in reasons if str(item).strip()]
    codes: list[str] = []
    for defect in qa_gate.get("defects", []) or []:
        if not isinstance(defect, dict):
            continue
        if defect.get("blocking") is True or str(defect.get("severity", "")).lower() == "critical":
            code = str(defect.get("type") or "QA_REVIEW_REQUIRED").upper()
            if code not in codes:
                codes.append(code)
    if qa_gate.get("qa_review_required") and "QA_REVIEW_REQUIRED" not in codes:
        codes.append("QA_REVIEW_REQUIRED")
    return codes


def _qa_status(draft_name: str, meta: dict[str, Any], qa_gate: dict[str, Any] | None) -> tuple[str, list[str]]:
    decision = str((qa_gate or {}).get("decision") or "")
    if decision in _NONBLOCKING_FINAL_DECISIONS:
        return "not_required", []
    reasons = _blocking_defect_codes(qa_gate)
    name_requires_review = "QA-FLAGGED" in draft_name or "QA-BLOCKED" in draft_name
    metadata_requires_review = meta.get("review_required") is True or meta.get("qa_review_required") is True
    decision_requires_review = decision in _BLOCKING_FINAL_DECISIONS
    qa_requires_review = bool(
        qa_gate and (
            decision_requires_review
            or qa_gate.get("qa_review_required")
            or (not decision and str(qa_gate.get("final_verdict", "")).upper() == "FAIL")
            or reasons
        )
    )
    if name_requires_review and not reasons:
        reasons = ["QA-FLAGGED"]
    if metadata_requires_review or qa_requires_review or name_requires_review:
        return "review_required", reasons or ["QA_REVIEW_REQUIRED"]
    return "unknown", []


def _unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value is None or not str(value).strip():
            continue
        text = str(value).strip()
        if text not in out:
            out.append(text)
    return out


def _draft_trace(draft_name: str, meta: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    events = [event for event in meta.get("events", []) if isinstance(event, dict)]
    windows = [_event_window(event, default_source) for event in events]
    starts = [window["start"] for window in windows if isinstance(window.get("start"), (int, float))]
    ends = [window["end"] for window in windows if isinstance(window.get("end"), (int, float))]
    source_videos = _unique([window.get("source_video") for window in windows] + list(meta.get("source_videos") or []))
    person_ids = _unique([window.get("person_id") for window in windows] + list(meta.get("person_ids") or []))
    athlete_ids = _unique([window.get("athlete_id") for window in windows] + list(meta.get("athlete_ids") or []))
    chunk_person_ids = _unique([window.get("chunk_person_id") for window in windows] + list(meta.get("chunk_person_ids") or []))
    source_window = {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
        "source_video": source_videos[0] if len(source_videos) == 1 else None,
    }
    qa_gate = _qa_gate(meta)
    qa_status, review_required_reasons = _qa_status(draft_name, meta, qa_gate)
    lineage_complete = bool(windows) and all(
        window.get("person_id") and window.get("athlete_id") and window.get("source_video")
        for window in windows
    )
    return {
        "draft_id": draft_name,
        "draft_name": draft_name,
        "title": draft_name,
        "sport": meta.get("sport"),
        "person_id": person_ids[0] if len(person_ids) == 1 else None,
        "person_ids": person_ids,
        "athlete_id": athlete_ids[0] if len(athlete_ids) == 1 else None,
        "athlete_ids": athlete_ids,
        "chunk_person_ids": chunk_person_ids,
        "source_videos": source_videos,
        "identity_lineage_status": "complete" if lineage_complete else "incomplete",
        "qa_status": qa_status,
        "review_required_reasons": review_required_reasons,
        "approval_blocked_reasons": meta.get("approval_blocked_reasons") or (qa_gate.get("approval_blocked_reasons") if qa_gate else []),
        "qa_gate": qa_gate,
        "source_window": source_window,
        "source_windows": windows,
        "events": events,
        "source_quality": meta.get("source_quality", {}),
    }


def build_trace(metadata_path: Path, log_path: Path) -> dict[str, Any]:
    metadata = _read_json(metadata_path) if metadata_path.exists() else {}
    if not isinstance(metadata, dict):
        metadata = {}
    default_source = _source_from_log(log_path)
    drafts = [
        _draft_trace(str(draft_name), meta, default_source)
        for draft_name, meta in sorted(metadata.items())
        if isinstance(meta, dict)
    ]
    return {
        "schema_version": "sportreel.draft_decision_trace.v1",
        "source": {
            "metadata_path": str(metadata_path),
            "log_path": str(log_path),
            "default_source_video": default_source,
        },
        "draft_count": len(drafts),
        "identity_lineage_complete_draft_count": sum(1 for draft in drafts if draft.get("identity_lineage_status") == "complete"),
        "identity_lineage_incomplete_draft_count": sum(1 for draft in drafts if draft.get("identity_lineage_status") != "complete"),
        "drafts": drafts,
    }


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_draft_decision_trace.py REELS_METADATA_JSON RUN_LOG OUTPUT_JSON", file=sys.stderr)
        return 2
    report = build_trace(Path(sys.argv[1]), Path(sys.argv[2]))
    _write_json(Path(sys.argv[3]), report)
    print(f"draft decision trace drafts={report['draft_count']} lineage_complete={report['identity_lineage_complete_draft_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
