#!/usr/bin/env python3
"""Contract: pipeline.editorial_value_ranker is additive-only.

It must add an editorial_value_score/editorial_value_categories field to every
candidate ledger entry without changing decision/value_labels/any other existing
field, and must never touch pipeline.stages.editor's _partition_events/_group_dur
(that would be a live selection-behavior change, deliberately out of scope --
same reasoning already recorded for PQ-008's _partition_events).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    from pipeline.editorial_value_ranker import CATEGORY_LABELS, score_editorial_value

    full_ride_event = {"type": "ride", "description": "a clean full ride", "score": 8, "ride_segment": True, "track_id": "7"}
    scored = score_editorial_value(full_ride_event)
    assert_true("editorial_value_score" in scored, "score missing")
    assert_true(scored["editorial_value_categories"] == ["long_ride"], f"expected long_ride category, got {scored['editorial_value_categories']}")

    boring_event = {"type": "paddle", "description": "dead time, no visible action", "score": 3}
    boring_scored = score_editorial_value(boring_event)
    assert_true(boring_scored["editorial_value_score"] < scored["editorial_value_score"], "a BORING-labeled candidate must score lower than a FULL_RIDE candidate")

    # Additive-only: wrapping build_candidate_entry must not drop or change any
    # existing field, only add the two new ones.
    fake_candidate_ledger = types.ModuleType("pipeline.candidate_ledger")

    def fake_build_candidate_entry(event, index, *, draft_name, decision=None, reason=None):
        return {"candidate_id": f"{draft_name}:{index}", "type": event.get("type", ""), "value_labels": ["FULL_RIDE"], "decision": decision or "selected"}

    fake_candidate_ledger.build_candidate_entry = fake_build_candidate_entry

    import pipeline.editorial_value_ranker as ranker
    ranker._patch_candidate_ledger(fake_candidate_ledger)
    assert_true(getattr(fake_candidate_ledger, ranker._INSTALLED_FLAG, False), "install flag must be set")

    entry = fake_candidate_ledger.build_candidate_entry(full_ride_event, 0, draft_name="DRAFT_x.mp4")
    assert_true(entry["candidate_id"] == "DRAFT_x.mp4:0", "wrapped entry lost an existing field")
    assert_true(entry["value_labels"] == ["FULL_RIDE"], "wrapped entry changed an existing field")
    assert_true(entry["decision"] == "selected", "wrapped entry changed the decision field")
    assert_true("editorial_value_score" in entry, "wrapped entry missing the new additive field")

    # Idempotent install (matches every other install() in this codebase).
    original_ref = fake_candidate_ledger.build_candidate_entry
    ranker._patch_candidate_ledger(fake_candidate_ledger)
    assert_true(fake_candidate_ledger.build_candidate_entry is original_ref, "install must be idempotent")

    # Category mapping must not silently invent categories with no requested-label backing.
    assert_true(set(CATEGORY_LABELS) == {"long_ride", "turn_cutback", "fall_recovery", "social_moment", "high_five", "good_style"}, "category label set drifted")
    assert_true("clean_takeoff" not in CATEGORY_LABELS and "strong_ending" not in CATEGORY_LABELS, "clean_takeoff/strong_ending have no reliable signal and must stay unmapped, not faked")

    # Must not touch live selection/partitioning behavior. The module docstring
    # references pipeline.stages.editor by name (prose explaining the scoping
    # decision) -- scope this check to the code after the docstring so that
    # prose doesn't produce a false-positive violation.
    ranker_source = (ROOT / "pipeline/editorial_value_ranker.py").read_text(encoding="utf-8")
    _, _, code_after_docstring = ranker_source.partition('"""\nfrom __future__')
    code_after_docstring = "from __future__" + code_after_docstring if code_after_docstring else ranker_source
    assert_true("pipeline.stages.editor" not in code_after_docstring, "editorial_value_ranker must not import/patch pipeline.stages.editor")

    print("Editorial value ranker contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
