#!/usr/bin/env python3
"""Cross-reference structured MISSING_GOOD_MOMENT operator feedback (draft_feedback
table, submitted via POST /api/operator/drafts/feedback) against that draft's
candidate_decision_ledger (pipeline/candidate_ledger.py, persisted per-run in
reels_metadata.json's diagnostic_artifact) — the recall report ROI 10 in
docs/audit/run-28768826828-roi-repair-plan-20260706.md asks for.

Honest about what this can and cannot do: draft_feedback rows do not carry a
time-window reference (see supabase/migrations/20260716_add_draft_feedback.sql —
the schema is draft_name/feedback_event/value_labels/note/ts only), so this report
cannot claim to identify *which* dropped candidate was the missed moment. It
surfaces the dropped/discarded candidates that existed for that draft's run as
evidence for a human to correlate against the feedback note, and reports
`missed_good_moment_count` — the metric ROI 10 explicitly asks for.

reels_metadata.json is a per-run, ephemeral CI artifact (candidate_decision_ledger
is not currently persisted anywhere durable across runs) — this report can only
correlate feedback against a ledger from the same local run/export it's given.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _dropped_candidates(meta: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = meta.get("diagnostic_artifact") if isinstance(meta.get("diagnostic_artifact"), dict) else {}
    ledger = artifact.get("candidate_decision_ledger") if isinstance(artifact.get("candidate_decision_ledger"), dict) else {}
    entries = ledger.get("entries") if isinstance(ledger.get("entries"), list) else []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("decision") == "dropped_or_blocked"]


def build_missed_moment_report(feedback_rows: list[dict[str, Any]], reels_metadata: dict[str, Any]) -> dict[str, Any]:
    missing_rows = [row for row in feedback_rows if isinstance(row, dict) and row.get("feedback_event") == "MISSING_GOOD_MOMENT"]

    entries: list[dict[str, Any]] = []
    for row in missing_rows:
        draft_name = str(row.get("draft_name") or "")
        meta = reels_metadata.get(draft_name) if isinstance(reels_metadata.get(draft_name), dict) else {}
        dropped = _dropped_candidates(meta)
        entries.append({
            "draft_name": draft_name,
            "note": row.get("note", ""),
            "created_at": row.get("created_at"),
            "candidate_ledger_available": bool(meta),
            "dropped_candidate_count": len(dropped),
            "dropped_candidates": dropped,
        })

    with_ledger = sum(1 for entry in entries if entry["candidate_ledger_available"])
    return {
        "schema_version": "sportreel.missed_moment_report.v1",
        "missed_good_moment_count": len(missing_rows),
        "missed_good_moment_with_ledger_count": with_ledger,
        "missed_good_moment_without_ledger_count": len(missing_rows) - with_ledger,
        "entries": entries,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: generate_missed_moment_report.py DRAFT_FEEDBACK_JSON REELS_METADATA_JSON", file=sys.stderr)
        return 2
    feedback_path = Path(sys.argv[1])
    metadata_path = Path(sys.argv[2])
    feedback_rows = _read_json(feedback_path) if feedback_path.exists() else []
    if not isinstance(feedback_rows, list):
        feedback_rows = []
    reels_metadata = _read_json(metadata_path) if metadata_path.exists() else {}
    if not isinstance(reels_metadata, dict):
        reels_metadata = {}
    report = build_missed_moment_report(feedback_rows, reels_metadata)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        f"missed_good_moment_count={report['missed_good_moment_count']} "
        f"with_ledger={report['missed_good_moment_with_ledger_count']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
