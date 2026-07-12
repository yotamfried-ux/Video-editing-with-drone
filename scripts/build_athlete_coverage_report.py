#!/usr/bin/env python3
"""Build athlete-level coverage and source-utilization telemetry.

A detected background person is not automatically an athlete cluster. This report
starts from selector candidates, so every included cluster has at least one action
candidate. Each such cluster must either be represented in a draft or carry an
explicit no-output reason.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sportreel.athlete_coverage_report.v1"

_EXPLICIT_REASON_MAP = {
    "fragment_shorter_than_min_event_sec": "no_complete_action",
    "score_below_selection_threshold": "quality_below_threshold",
    "dedup_overlap_lower_score": "duplicate_action_window",
    "duplicate_source_window_before_render": "duplicate_action_window",
    "subject_gated_by_pre_qa_prefilter": "target_not_trackable",
    "subject_gated_by_pre_qa_prefilter_log_fallback": "target_not_trackable",
    "no_clean_subwindow_found": "target_not_trackable",
    "shared_or_obstructed_window": "primary_actor_uncertain",
    "identity_fragmentation": "duplicate_identity_cluster",
    "timestamp_outside_chunk_bounds": "invalid_source_timestamp",
    "insufficient_time_inside_chunk": "no_complete_action",
    "invalid_numeric_window": "invalid_source_timestamp",
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _cluster_key(candidate: dict[str, Any]) -> str:
    person_id = str(candidate.get("person_id") or candidate.get("chunk_person_id") or "").strip()
    source_video = str(candidate.get("source_video") or "").strip()
    description = str(candidate.get("person_description") or "").strip()
    if person_id and source_video:
        return f"{source_video}::{person_id}"
    return person_id or _norm(description) or "unknown_cluster"


def _window_from_field(candidate: dict[str, Any], field: str) -> dict[str, float | None]:
    raw = candidate.get(field) if isinstance(candidate.get(field), dict) else {}

    def num(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    start = num(raw.get("start"))
    end = num(raw.get("end"))
    duration = num(raw.get("duration"))
    if duration is None and start is not None and end is not None:
        duration = max(0.0, end - start)
    return {"start": start, "end": end, "duration": duration}


def _candidate_window(candidate: dict[str, Any]) -> dict[str, float | None]:
    return _window_from_field(candidate, "source_window")


def _selected_window(candidate: dict[str, Any]) -> dict[str, float | None]:
    if isinstance(candidate.get("final_source_window"), dict):
        return _window_from_field(candidate, "final_source_window")
    return _candidate_window(candidate)


def _detailed_reason(candidate: dict[str, Any]) -> str:
    return str(candidate.get("discard_cause_detailed") or candidate.get("discard_cause") or "")


def _no_output_reason(candidates: list[dict[str, Any]]) -> tuple[str | None, bool]:
    reasons = [_detailed_reason(candidate) for candidate in candidates if candidate.get("discarded")]
    mapped = [_EXPLICIT_REASON_MAP.get(reason) for reason in reasons]
    mapped = [reason for reason in mapped if reason]
    if reasons and len(mapped) == len(reasons):
        return Counter(mapped).most_common(1)[0][0], True
    if reasons:
        return "unresolved_selection_path", False
    return None, False


def build_report(ledger_path: Path, selection_audit_path: Path | None = None) -> dict[str, Any]:
    ledger = _read(ledger_path)
    audit = _read(selection_audit_path) if selection_audit_path else {}
    audit_rows = {
        str(row.get("candidate_id")): row
        for row in audit.get("candidates", []) or []
        if isinstance(row, dict) and row.get("candidate_id")
    }

    candidates: list[dict[str, Any]] = []
    for raw in ledger.get("candidates", []) or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        enriched = audit_rows.get(str(row.get("candidate_id")))
        if enriched:
            row.update({
                "discard_stage": enriched.get("discard_stage"),
                "discard_cause_detailed": enriched.get("discard_cause_detailed"),
                "decision_path": enriched.get("decision_path"),
            })
        candidates.append(row)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        grouped[_cluster_key(candidate)].append(candidate)

    athletes: list[dict[str, Any]] = []
    for cluster_id, rows in sorted(grouped.items()):
        selected = [row for row in rows if row.get("selected")]
        discarded = [row for row in rows if row.get("discarded")]
        no_output_reason, explicit = _no_output_reason(rows)
        descriptions = [str(row.get("person_description") or "").strip() for row in rows]
        descriptions = [description for description in descriptions if description]
        person_ids = sorted({str(row.get("person_id")) for row in rows if row.get("person_id")})
        athlete_ids = sorted({str(row.get("athlete_id")) for row in rows if row.get("athlete_id")})
        source_videos = sorted({str(row.get("source_video")) for row in rows if row.get("source_video")})
        candidate_seconds = sum((_candidate_window(row).get("duration") or 0.0) for row in rows)
        selected_seconds = sum((_selected_window(row).get("duration") or 0.0) for row in selected)
        outcome = "draft_created" if selected else (no_output_reason or "coverage_gap")
        coverage_met = bool(selected) or explicit
        selected_lineage_complete = all(
            row.get("person_id") and row.get("athlete_id") and row.get("source_video")
            for row in selected
        ) if selected else True
        athletes.append({
            "athlete_cluster_id": cluster_id,
            "person_ids": person_ids,
            "athlete_ids": athlete_ids,
            "source_videos": source_videos,
            "descriptions": sorted(set(descriptions)),
            "candidate_action_count": len(rows),
            "selected_action_count": len(selected),
            "discarded_action_count": len(discarded),
            "candidate_seconds": round(candidate_seconds, 2),
            "selected_seconds": round(selected_seconds, 2),
            "action_utilization_rate": round(selected_seconds / candidate_seconds, 3) if candidate_seconds else 0.0,
            "score_max": max((int(row.get("score") or 0) for row in rows), default=0),
            "discard_reason_counts": dict(Counter(_detailed_reason(row) or "missing_reason" for row in discarded)),
            "final_outcome": outcome,
            "no_output_reason_explicit": explicit,
            "coverage_requirement_met": coverage_met,
            "selected_identity_lineage_complete": selected_lineage_complete,
            "selected_windows": [
                {
                    "candidate_id": row.get("candidate_id"),
                    "candidate_source_window": _candidate_window(row),
                    "final_source_window": _selected_window(row),
                    "score": row.get("score"),
                    "person_id": row.get("person_id"),
                    "athlete_id": row.get("athlete_id"),
                    "source_video": row.get("source_video"),
                }
                for row in selected
            ],
            "unselected_windows": [
                {
                    "candidate_id": row.get("candidate_id"),
                    "source_window": _candidate_window(row),
                    "score": row.get("score"),
                    "reason": _detailed_reason(row) or "missing_reason",
                    "decision_path": row.get("decision_path"),
                    "person_id": row.get("person_id"),
                    "source_video": row.get("source_video"),
                }
                for row in discarded
            ],
        })

    confirmed = len(athletes)
    represented = sum(1 for athlete in athletes if athlete["selected_action_count"] > 0)
    covered_or_explained = sum(1 for athlete in athletes if athlete["coverage_requirement_met"])
    candidate_seconds = sum(athlete["candidate_seconds"] for athlete in athletes)
    selected_seconds = sum(athlete["selected_seconds"] for athlete in athletes)
    selected_candidates = [row for row in candidates if row.get("selected")]
    selected_lineage_complete_count = sum(
        1
        for row in selected_candidates
        if row.get("person_id") and row.get("athlete_id") and row.get("source_video")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "candidate_decision_ledger_path": str(ledger_path),
            "selection_decision_audit_path": str(selection_audit_path) if selection_audit_path else None,
        },
        "summary": {
            "confirmed_athlete_cluster_count": confirmed,
            "represented_athlete_cluster_count": represented,
            "covered_or_explicitly_explained_cluster_count": covered_or_explained,
            "athlete_draft_coverage_rate": round(represented / confirmed, 3) if confirmed else 1.0,
            "athlete_accountability_rate": round(covered_or_explained / confirmed, 3) if confirmed else 1.0,
            "candidate_action_count": len(candidates),
            "selected_action_count": len(selected_candidates),
            "selected_identity_lineage_complete_count": selected_lineage_complete_count,
            "selected_identity_lineage_completeness_rate": round(selected_lineage_complete_count / len(selected_candidates), 3) if selected_candidates else 1.0,
            "candidate_action_seconds": round(candidate_seconds, 2),
            "selected_action_seconds": round(selected_seconds, 2),
            "action_source_utilization_rate": round(selected_seconds / candidate_seconds, 3) if candidate_seconds else 0.0,
            "coverage_gap_cluster_count": sum(1 for athlete in athletes if not athlete["coverage_requirement_met"]),
        },
        "athletes": athletes,
    }


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        print("usage: build_athlete_coverage_report.py CANDIDATE_LEDGER_JSON OUTPUT_JSON [SELECTION_AUDIT_JSON]", file=sys.stderr)
        return 2
    ledger = Path(sys.argv[1])
    output = Path(sys.argv[2])
    audit = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    report = build_report(ledger, audit)
    _write(output, report)
    summary = report["summary"]
    print(
        "athlete coverage report "
        f"clusters={summary['confirmed_athlete_cluster_count']} "
        f"represented={summary['represented_athlete_cluster_count']} "
        f"accountability={summary['athlete_accountability_rate']} "
        f"lineage={summary['selected_identity_lineage_completeness_rate']} "
        f"utilization={summary['action_source_utilization_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
