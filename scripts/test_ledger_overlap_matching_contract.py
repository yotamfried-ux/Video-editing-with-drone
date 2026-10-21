#!/usr/bin/env python3
"""Contract: a selector-selected action counts as emitted when a draft window overlaps it.

Production run 39647666993 had 46 ledger candidates = 30 selector + 16 draft windows and ZERO matches,
because the exact-equality key (rounded start, end, event type) never survives the window policy.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_candidate_decision_ledger as ledger_builder  # noqa: E402


def selector(person, start, end, source="a.MP4", selected=True, cause=None, event_type="ride"):
    return {"candidate_id": f"{source}-{person}-{start}", "person_id": person, "source_video": source,
            "event_type": event_type, "score": 8, "selected": selected, "discarded": not selected,
            "discard_cause": cause, "source_window": {"start": start, "end": end, "duration": end - start}}


def draft(name, windows):
    return {"draft_id": name, "draft_name": name, "source_windows": windows}


def window(person, start, end, source="a.MP4", original=None, event_type="surf_ride", athlete="ath_1"):
    row = {"person_id": person, "athlete_id": athlete, "source_video": source, "event_type": event_type,
           "start": start, "end": end, "duration": end - start}
    if original:
        row["original_start"], row["original_end"] = original
    return row


def build(drafts, candidates):
    with tempfile.TemporaryDirectory() as tmp:
        trace, upstream = Path(tmp) / "trace.json", Path(tmp) / "up.json"
        trace.write_text(json.dumps({"schema_version": "t", "drafts": drafts}))
        upstream.write_text(json.dumps({"schema_version": "u", "candidates": candidates}))
        return ledger_builder.build_ledger(trace, upstream)


def test_padded_window_with_a_different_event_type_still_matches() -> None:
    result = build([draft("D1", [window("person_A", 6.0, 26.0)])], [selector("person_A", 10.0, 20.0)])
    assert result["selected_count"] == 1 and result["discarded_count"] == 0, result
    assert result["unmatched_selector_selected_count"] == 0, result
    row = result["candidates"][0]
    assert row["athlete_id"] == "ath_1" and row["matched_via_window_overlap"] is True, row


def test_exact_match_path_is_unchanged() -> None:
    result = build([draft("D1", [window("person_A", 10.0, 20.0, event_type="ride")])], [selector("person_A", 10.0, 20.0)])
    assert result["candidates"][0]["matched_via_window_overlap"] is False and result["unmatched_selector_selected_count"] == 0


def test_a_different_athlete_in_the_same_time_window_does_not_match() -> None:
    result = build([draft("D1", [window("person_A", 10.0, 20.0)])],
                   [selector("person_A", 10.0, 20.0), selector("person_B", 11.0, 19.0)])
    assert result["unmatched_selector_selected_count"] == 1, result
    other = next(c for c in result["candidates"] if c.get("person_id") == "person_B")
    assert other["discarded"] is True and other["discard_cause"] == "selected_by_selector_not_emitted_as_draft", other


def test_a_different_source_does_not_match() -> None:
    result = build([draft("D1", [window("person_A", 10.0, 20.0, source="b.MP4")])], [selector("person_A", 10.0, 20.0, source="a.MP4")])
    assert result["unmatched_selector_selected_count"] == 1, result


def test_pairing_is_one_to_one() -> None:
    result = build([draft("D1", [window("person_A", 8.0, 24.0)])],
                   [selector("person_A", 10.0, 16.0), selector("person_A", 12.0, 22.0)])
    assert result["selected_count"] == 1 and result["unmatched_selector_selected_count"] == 1, result


def test_real_selector_discards_are_never_turned_into_selected() -> None:
    result = build([draft("D1", [window("person_A", 10.0, 20.0)])],
                   [selector("person_A", 11.0, 19.0, selected=False, cause="dedup_overlap_lower_score")])
    discarded = [c for c in result["candidates"] if c["discarded"]]
    assert len(discarded) == 1 and discarded[0]["discard_cause"] == "dedup_overlap_lower_score", result
    assert result["selected_count"] == 1


def test_non_overlapping_selection_stays_unmatched() -> None:
    result = build([draft("D1", [window("person_A", 10.0, 20.0)])], [selector("person_A", 60.0, 70.0)])
    assert result["unmatched_selector_selected_count"] == 1, result


def test_coverage_report_resolves_the_matched_athlete() -> None:
    import build_athlete_coverage_report as coverage
    result = build([draft("D1", [window("person_A", 6.0, 26.0)])], [selector("person_A", 10.0, 20.0)])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.json"
        path.write_text(json.dumps(result))
        report = coverage.build_report(path)
    keys = {row["athlete_cluster_id"] for row in report["athletes"]}
    assert keys == {"athlete::ath_1"}, keys    # no stray `a.MP4::person_A` cluster left unaccounted


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS ledger overlap matching contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
