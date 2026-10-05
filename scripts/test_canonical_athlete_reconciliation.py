#!/usr/bin/env python3
from __future__ import annotations
import json
import tempfile
from pathlib import Path

from pipeline.publishable_reel_policy import athlete_key
from scripts.build_athlete_coverage_report import build_report


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise AssertionError(msg)


def main() -> None:
    # Recompile/QA lineage changes must not create a second manifest owner.
    first = {"a.mp4": [{"athlete_id": "ath_same", "event_id": "e1", "source_video": "a.mp4"}]}
    second = {"b.mp4": [{"athlete_id": "ath_same", "event_id": "e2", "source_video": "b.mp4"}]}
    require(
        athlete_key("surfing", "label one", first) == athlete_key("surfing", "changed label", second),
        "canonical athlete key changed across lineage/label changes",
    )

    # Source-local person rows that already resolve to one canonical athlete are one
    # accountability unit, not duplicate athletes.
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ledger.json"
        p.write_text(json.dumps({
            "candidates": [
                {"candidate_id": "c1", "source_video": "a.mp4", "person_id": "person_A",
                 "athlete_id": "ath_same", "selected": True, "discarded": False,
                 "source_window": {"start": 0, "end": 5, "duration": 5}},
                {"candidate_id": "c2", "source_video": "b.mp4", "person_id": "person_B",
                 "athlete_id": "ath_same", "selected": True, "discarded": False,
                 "source_window": {"start": 10, "end": 16, "duration": 6}},
            ],
            "detected_athlete_registry": [
                {"source_video": "a.mp4", "person_id": "person_A", "detected_event_count": 1},
                {"source_video": "b.mp4", "person_id": "person_B", "detected_event_count": 1},
            ],
        }), encoding="utf-8")
        report = build_report(p)
        require(report["summary"]["confirmed_athlete_cluster_count"] == 1, str(report["summary"]))
        require(report["summary"]["coverage_gap_cluster_count"] == 0, str(report["summary"]))
        require(report["summary"]["athlete_accountability_rate"] == 1.0, str(report["summary"]))
        athlete = report["athletes"][0]
        require(athlete["athlete_ids"] == ["ath_same"], str(athlete))
        require(set(athlete["source_videos"]) == {"a.mp4", "b.mp4"}, str(athlete))

    print("canonical athlete reconciliation contract ok")


if __name__ == "__main__":
    main()
