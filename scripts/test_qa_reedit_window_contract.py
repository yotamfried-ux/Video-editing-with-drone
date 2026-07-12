#!/usr/bin/env python3
"""Regression coverage for PREMATURE_CUT edits that were re-capped to 15s."""
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
)
from pipeline.window_policy import resolve_window


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    original = {
        "type": "wave_catch",
        "start": 332.0,
        "end": 400.0,
        "score": 9,
        "description": "long ride with the outcome missing from the prior cut",
        "_is_climax": True,
        "_cap_dur": 15.0,
    }
    fixed = {**original, "end": 403.0}
    defects = [{"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 14.0}]
    marked = mark_reedit_extensions([original], [fixed], defects)
    require(len(marked) == 1, "repair should retain the event")
    repaired = marked[0]
    require(repaired["_qa_reedit_allow_long_cut"] is True, "repair override flag missing")
    require(repaired["_qa_reedit_original_end"] == 400.0, "original end evidence missing")
    require(repaired["_qa_reedit_requested_end"] == 403.0, "requested end evidence missing")
    require(repaired["_cap_dur"] == QA_REEDIT_MAX_WINDOW_SEC, "long repair was not bounded to safety max")
    require((repaired["final_cut_start"], repaired["final_cut_end"]) == (373.0, 403.0), "repair must preserve the action outcome tail")

    prepared = prepare_reedit_event(repaired)
    require((prepared["start"], prepared["end"]) == (373.0, 403.0), "editor input does not match telemetry final cut")
    require(prepared["end"] - prepared["start"] == 30.0, "repair window should exceed the old 15s cap")
    require(reedit_effective_window(repaired) == (373.0, 403.0), "subject gate and editor windows disagree")
    resolved = resolve_window(prepared, 548.9)
    require(resolved is not None, "window policy rejected the valid repaired window")
    require((resolved["start"], resolved["end"]) == (373.0, 403.0), "window policy re-capped or shifted the repaired window")

    short_original = {**original, "start": 480.0, "end": 495.0, "_cap_dur": 15.0}
    short_fixed = {**short_original, "end": 498.0}
    short_repaired = mark_reedit_extensions([short_original], [short_fixed], defects)[0]
    require((short_repaired["final_cut_start"], short_repaired["final_cut_end"]) == (480.0, 498.0), "18s repair should retain its full source window")
    require(short_repaired["_cap_dur"] == 18.0, "18s repair should not expand to the 30s maximum")

    unchanged = mark_reedit_extensions([original], [fixed], [{"type": "IDENTITY_MISMATCH", "severity": "critical"}])[0]
    require("_qa_reedit_allow_long_cut" not in unchanged, "non-cut QA defects must not override pacing caps")

    runtime = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    contract = (ROOT / "pipeline/qa_reedit_window_contract.py").read_text(encoding="utf-8")
    for token in (
        "_install_qa_reedit_window_contract()",
        "from pipeline.qa_reedit_window_contract import install",
    ):
        require(token in runtime, f"tracked runtime missing QA re-edit window wiring: {token}")
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
