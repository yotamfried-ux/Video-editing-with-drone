#!/usr/bin/env python3
"""Regression coverage for renderable PREMATURE_CUT repair windows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.qa_reedit_window_contract import (
    QA_REEDIT_MAX_WINDOW_SEC,
    mark_reedit_extensions,
    prepare_reedit_event,
    reedit_effective_window,
    resolve_reedit_window,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    defects = [{"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 14.0}]
    original = {
        "type": "wave_catch", "start": 332.0, "end": 400.0, "score": 9,
        "description": "long ride with the outcome missing from the prior cut",
        "setup_start": 332.0, "peak_time": 350.0, "outcome_end": 400.0,
        "_is_climax": True, "_cap_dur": 15.0,
    }
    repaired = mark_reedit_extensions([original], [{**original, "end": 403.0, "outcome_end": 403.0}], defects)[0]
    require(repaired["_qa_reedit_allow_long_cut"] is True, "repair override flag missing")
    require((repaired["_qa_reedit_selector_start"], repaired["_qa_reedit_selector_end"]) == (332.0, 400.0), "selector provenance missing")
    require((repaired["_qa_reedit_previous_start"], repaired["_qa_reedit_previous_end"]) == (332.0, 400.0), "previous iteration evidence missing")
    require(repaired["_qa_reedit_requested_end"] == 403.0, "requested end evidence missing")
    require(repaired["_cap_dur"] == QA_REEDIT_MAX_WINDOW_SEC, "long repair was not bounded to safety max")
    require((repaired["final_cut_start"], repaired["final_cut_end"]) == (373.0, 403.0), "repair must preserve the outcome tail")

    prepared = prepare_reedit_event(repaired)
    require((prepared["start"], prepared["end"]) == (373.0, 403.0), "editor input does not match telemetry final cut")
    require(reedit_effective_window(repaired) == (373.0, 403.0), "subject gate and editor windows disagree")
    resolved = resolve_reedit_window(repaired, 548.9)
    require(resolved is not None and (resolved["start"], resolved["end"]) == (373.0, 403.0), "window policy shifted the repair")
    require((resolved["original_start"], resolved["original_end"]) == (332.0, 400.0), "QA resolution overwrote selector provenance")

    # Exact production sequence from run 29194242123. The second retry must keep
    # 496-512.5 as the selector window, not promote 515.5 to original_end.
    selector_event = {
        "type": "highlight", "start": 496.0, "end": 512.5, "score": 9,
        "description": "pink longboard ride", "_is_climax": True, "_cap_dur": 15.0,
    }
    retry_one = mark_reedit_extensions(
        [selector_event], [{**selector_event, "end": 515.5}], defects,
    )[0]
    retry_two = mark_reedit_extensions(
        [retry_one], [{**retry_one, "end": 521.5}], defects,
    )[0]
    require((retry_two["_qa_reedit_selector_start"], retry_two["_qa_reedit_selector_end"]) == (496.0, 512.5), "second retry drifted selector window")
    require((retry_two["_qa_reedit_original_start"], retry_two["_qa_reedit_original_end"]) == (496.0, 512.5), "compatibility original window drifted")
    require((retry_two["_qa_reedit_previous_start"], retry_two["_qa_reedit_previous_end"]) == (496.0, 515.5), "previous retry window not recorded")
    require(retry_two["_qa_reedit_requested_end"] == 521.5, "final retry request missing")
    require((retry_two["final_cut_start"], retry_two["final_cut_end"]) == (496.0, 521.5), "final production repair window is wrong")
    production_resolved = resolve_reedit_window(retry_two, 548.9)
    require(production_resolved is not None, "production repair did not resolve")
    require((production_resolved["selector_original_start"], production_resolved["selector_original_end"]) == (496.0, 512.5), "resolved production window lost selector provenance")
    require((production_resolved["start"], production_resolved["end"]) == (496.0, 521.5), "resolved production final cut is wrong")

    # A policy/source clamp can shift only final_cut_start while raw start remains
    # the selector start. The next retry must report the previous rendered start.
    clamped_previous = {
        **retry_one,
        "start": 496.0,
        "end": 515.5,
        "final_cut_start": 499.0,
        "final_cut_end": 515.5,
    }
    after_clamped = mark_reedit_extensions(
        [clamped_previous], [{**clamped_previous, "end": 518.5}], defects,
    )[0]
    require(after_clamped["_qa_reedit_previous_start"] == 499.0, "retry recorded stale raw start instead of previous rendered start")
    require(after_clamped["_qa_reedit_previous_end"] == 515.5, "retry lost previous raw end")
    require((after_clamped["_qa_reedit_selector_start"], after_clamped["_qa_reedit_selector_end"]) == (496.0, 512.5), "clamped retry changed selector provenance")

    short_original = {**original, "start": 480.0, "end": 495.0, "setup_start": 480.0, "peak_time": 488.0, "outcome_end": 495.0}
    short_repaired = mark_reedit_extensions([short_original], [{**short_original, "end": 498.0}], defects)[0]
    require((short_repaired["final_cut_start"], short_repaired["final_cut_end"]) == (480.0, 498.0), "18s repair should retain the full window")
    require(short_repaired["_cap_dur"] == 18.0, "18s repair should not expand to 30s")

    near_end = resolve_reedit_window({**short_repaired, "end": 552.0, "_qa_reedit_requested_end": 552.0}, 548.9)
    require(near_end is not None and near_end["end"] == 548.9, "repair was not clamped to source duration")
    require((near_end["original_start"], near_end["original_end"]) == (480.0, 495.0), "source-end clamp lost selector window")

    unchanged = mark_reedit_extensions([original], [{**original, "end": 403.0}], [{"type": "IDENTITY_MISMATCH", "severity": "critical"}])[0]
    require("_qa_reedit_allow_long_cut" not in unchanged, "non-cut defects must not override pacing")

    runtime = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    contract = (ROOT / "pipeline/qa_reedit_window_contract.py").read_text(encoding="utf-8")
    require("install_post_orchestrator_patches()" in runtime, "tracked runtime omits canonical post-orchestrator bootstrap")
    require("pipeline.qa_reedit_window_contract" in bootstrap, "canonical bootstrap omits QA re-edit window contract")
    for token in (
        "orchestrator._apply_qa_fixes = apply_with_renderable_extension",
        "editor.cut_clip = cut_with_reedit_window",
        "window_policy.resolve_window = resolve_with_reedit_window",
        "subject_gate_policy.effective_cut_window = effective_with_reedit_window",
    ):
        require(token in contract, f"QA re-edit contract missing runtime hook: {token}")

    print("QA re-edit window contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
