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


def _event_window(event: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    original_start = event.get("start")
    original_end = event.get("end")
    start = _window_value(event, "final_cut_start", "start")
    end = _window_value(event, "final_cut_end", "end")
    return {
        "source_video": event.get("_src") or event.get("source_video") or event.get("source") or default_source,
        "event_type": event.get("type", ""),
        "start": start,
        "end": end,
        "duration": (float(end) - float(start)) if isinstance(start, (int, float)) and isinstance(end, (int, float)) else None,
        "original_start": original_start,
        "original_end": original_end,
        "final_cut_start": event.get("final_cut_start"),
        "final_cut_end": event.get("final_cut_end"),
        "score": event.get("score"),
        "description": event.get("description", ""),
        "edit": event.get("edit", {}),
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
    # A first-class final decision outranks the raw LLM verdict. In particular,
    # failed_nonblocking remains visible in telemetry but must not be converted
    # back into review_required merely because final_verdict is FAIL.
    if decision in _NONBLOCKING_FINAL_DECISIONS:
        return "not_required", []

    reasons = _blocking_defect_codes(qa_gate)
    name_requires_review = "QA-FLAGGED" in draft_name or "QA-BLOCKED" in draft_name
    metadata_requires_review = meta.get("review_required") is True or meta.get("qa_review_required") is True
    decision_requires_review = decision in _BLOCKING_FINAL_DECISIONS
    qa_requires_review = bool(
        qa_gate
        and (
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


def _draft_trace(draft_name: str, meta: dict[str, Any], default_source: str | None) -> dict[str, Any]:
    events = [e for e in meta.get("events", []) if isinstance(e, dict)]
    windows = [_event_window(event, default_source) for event in events]
    starts = [w["start"] for w in windows if isinstance(w.get("start"), (int, float))]
    ends = [w["end"] for w in windows if isinstance(w.get("end"), (int, float))]
    source_window = {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
        "source_video": next((w.get("source_video") for w in windows if w.get("source_video")), default_source),
    }
    qa_gate = _qa_gate(meta)
    qa_status, review_required_reasons = _qa_status(draft_name, meta, qa_gate)
    return {
        "draft_id": draft_name,
        "draft_name": draft_name,
        "title": draft_name,
        "sport": meta.get("sport"),
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
        "drafts": drafts,
    }


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_draft_decision_trace.py REELS_METADATA_JSON RUN_LOG OUTPUT_JSON", file=sys.stderr)
        return 2
    report = build_trace(Path(sys.argv[1]), Path(sys.argv[2]))
    _write_json(Path(sys.argv[3]), report)
    print(f"draft decision trace drafts={report['draft_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
