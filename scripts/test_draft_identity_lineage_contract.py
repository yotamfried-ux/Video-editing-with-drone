#!/usr/bin/env python3
"""Ensure selector → draft → trace → coverage retains athlete lineage."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.draft_identity_metadata import enrich_metadata_entry


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace_module = load(ROOT / "scripts/build_draft_decision_trace.py", "draft_trace_lineage")
ledger_module = load(ROOT / "scripts/build_candidate_decision_ledger.py", "candidate_ledger_lineage")
coverage_module = load(ROOT / "scripts/build_athlete_coverage_report.py", "athlete_coverage_lineage")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    draft_name = "DRAFT_black_shorts_turquoise_board.mp4"
    event = {
        "type": "wave_catch",
        "score": 9,
        "start": 496.0,
        "end": 515.0,
        "original_start": 496.0,
        "original_end": 512.0,
        "final_cut_start": 498.0,
        "final_cut_end": 515.0,
        "cut_adjustment_reason": "qa_premature_cut_extension",
        "description": "complete ride",
        "edit": {"zoom": 1.2},
        "person_id": "chunk_01:person_A",
        "source_person_id": "person_A",
        "chunk_person_id": "chunk_01:person_A",
        "athlete_id": "ath_1234567890",
        "athlete_canonical_key": "single_source:edited_surf.mp4:chunk_01:person_A",
        "athlete_canonical_evidence_status": "single_source",
        "source_video": "edited_surf.mp4",
        "source": "/tmp/edited_surf.mp4",
        "chunk_index": 1,
        "chunk_source_start": 480.0,
        "chunk_source_end": 548.9,
        "chunk_local_start": 16.0,
        "chunk_local_end": 32.0,
        "timestamp_basis": "chunk_local",
    }
    entry = enrich_metadata_entry({"sport": "surfing", "source_quality": {}}, [event])
    require(entry["identity_lineage_status"] == "complete", "metadata did not mark complete lineage")
    require(entry["person_id"] == "chunk_01:person_A", "metadata person_id missing")
    require(entry["athlete_id"] == "ath_1234567890", "metadata athlete_id missing")
    require(entry["source_videos"] == ["edited_surf.mp4"], "metadata source lineage missing")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        metadata_path = tmp / "reels_metadata.json"
        log_path = tmp / "run.log"
        trace_path = tmp / "draft_decision_trace.json"
        upstream_path = tmp / "selector_candidate_events.json"
        ledger_path = tmp / "candidate_decision_ledger.json"
        metadata_path.write_text(json.dumps({draft_name: entry}), encoding="utf-8")
        log_path.write_text("Long video: edited_surf.mp4\n", encoding="utf-8")

        trace = trace_module.build_trace(metadata_path, log_path)
        trace_path.write_text(json.dumps(trace), encoding="utf-8")
        require(trace["identity_lineage_complete_draft_count"] == 1, "trace did not count complete draft lineage")
        draft = trace["drafts"][0]
        require(draft["person_id"] == "chunk_01:person_A", "draft trace person_id missing")
        require(draft["athlete_id"] == "ath_1234567890", "draft trace athlete_id missing")
        window = draft["source_windows"][0]
        require(window["source_video"] == "edited_surf.mp4", "draft source window missing source")
        require(window["chunk_local_start"] == 16.0, "chunk-local evidence missing")
        require((window["start"], window["end"]) == (498.0, 515.0), "final edited window missing from trace")
        require((window["original_start"], window["original_end"]) == (496.0, 512.0), "selector source window evidence missing")

        upstream = {
            "schema_version": "sportreel.selector_candidate_events.v1",
            "candidates": [
                {
                    "candidate_id": "selector-candidate-A",
                    "person_id": "chunk_01:person_A",
                    "source_person_id": "person_A",
                    "chunk_person_id": "chunk_01:person_A",
                    "person_description": "black shorts on turquoise board",
                    "selected": True,
                    "discarded": False,
                    "selection_reason": "score_above_threshold",
                    "event_type": "wave_catch",
                    "score": 9,
                    "source_video": "edited_surf.mp4",
                    "source_window": {"start": 496.0, "end": 512.0, "duration": 16.0},
                    "chunk_index": 1,
                    "chunk_local_window": {"start": 16.0, "end": 32.0},
                    "timestamp_basis": "chunk_local",
                    "description": "complete ride",
                },
                {
                    "candidate_id": "selector-candidate-B",
                    "person_id": "chunk_01:person_B",
                    "source_person_id": "person_B",
                    "chunk_person_id": "chunk_01:person_B",
                    "person_description": "background surfer in white shirt",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "subject_gated_by_pre_qa_prefilter",
                    "event_type": "wave_catch",
                    "score": 6,
                    "source_video": "edited_surf.mp4",
                    "source_window": {"start": 496.0, "end": 512.0, "duration": 16.0},
                    "chunk_index": 1,
                    "chunk_local_window": {"start": 16.0, "end": 32.0},
                    "timestamp_basis": "chunk_local",
                    "description": "same physical time but different athlete",
                },
            ],
        }
        upstream_path.write_text(json.dumps(upstream), encoding="utf-8")
        ledger = ledger_module.build_ledger(trace_path, upstream_path)
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        require(ledger["candidate_count"] == 2, "same-time candidates for different athletes collided")
        require(ledger["selected_count"] == 1, "edited trace and selector source window did not merge")
        require(ledger["discarded_count"] == 1, "other athlete at same time was lost")
        require(ledger["unmatched_selector_selected_count"] == 0, "selected source window was falsely marked not emitted")
        require(ledger["selected_lineage_complete_count"] == 1, "ledger lineage completeness is wrong")
        selected = next(item for item in ledger["candidates"] if item.get("selected"))
        require(selected["candidate_id"] == "selector-candidate-A", "trace merged into the wrong athlete")
        require(selected["person_id"] == "chunk_01:person_A", "ledger lost person_id")
        require(selected["athlete_id"] == "ath_1234567890", "ledger lost athlete_id")
        require(selected["source_video"] == "edited_surf.mp4", "ledger lost source_video")
        require(selected["matched_via_original_source_window"] is True, "edited draft was not matched via original source window")
        require(selected["final_source_window"] == {"start": 498.0, "end": 515.0, "duration": 17.0}, "actual final cut was not retained separately")

        coverage = coverage_module.build_report(ledger_path)
        require(coverage["summary"]["represented_athlete_cluster_count"] == 1, "coverage did not represent the selected athlete")
        require(coverage["summary"]["selected_identity_lineage_completeness_rate"] == 1.0, "coverage lineage completeness should be 100%")
        by_id = {athlete["athlete_cluster_id"]: athlete for athlete in coverage["athletes"]}
        require(by_id["chunk_01:person_A"]["athlete_ids"] == ["ath_1234567890"], "coverage athlete ID missing")
        require(by_id["chunk_01:person_A"]["selected_windows"][0]["person_id"] == "chunk_01:person_A", "coverage selected window lost person ID")
        require(by_id["chunk_01:person_B"]["final_outcome"] == "target_not_trackable", "other athlete explicit outcome was lost")

    print("draft identity lineage contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
