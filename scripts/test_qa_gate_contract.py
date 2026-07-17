#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.qa_gate_policy import (
        BLOCKING_DEFECT_TYPES,
        attach_qa_diagnostics,
        build_qa_diagnostics,
        critical_defects,
        _augment_metadata_file,
    )

    required = {"IDENTITY_MISMATCH", "NO_VISIBLE_ACTION", "BAD_FRAMING", "DUPLICATE_MOMENT"}
    if not required.issubset(BLOCKING_DEFECT_TYPES):
        raise SystemExit("missing required blocking defect types")

    qa = {
        "verdict": "FAIL",
        "overall": "identity mismatch and bad framing",
        "engagement_score": 32,
        "defects": [
            {"type": "IDENTITY_MISMATCH", "severity": "critical", "at_seconds": 4.5, "event_id": "ev1", "source": "a.mp4", "note": "two athletes mixed"},
            {"type": "BAD_FRAMING", "severity": "critical", "at_seconds": 8.0, "event_id": "ev2", "source": "b.mp4", "note": "athlete cropped out"},
            {"type": "COLOR", "severity": "minor", "note": "minor issue"},
        ],
    }
    if len(critical_defects(qa)) != 2:
        raise SystemExit("critical defects were not identified correctly")

    diag = build_qa_diagnostics(qa, retry_count=2, decision="flagged_manual_review", reel_path="/tmp/reel.mp4")
    if diag["final_verdict"] != "FAIL" or diag["retry_count"] != 2:
        raise SystemExit("final verdict or retry count missing")
    if diag["critical_defect_count"] != 2:
        raise SystemExit("critical defect count missing")
    for key in ["type", "severity", "event_id", "source", "decision"]:
        if key not in diag["defects"][0]:
            raise SystemExit(f"defect metadata missing required field: {key}")
    if diag["decision"] != "flagged_manual_review":
        raise SystemExit("decision missing from QA diagnostics")

    events = attach_qa_diagnostics([{"type": "cutback", "score": 8}], diag)
    if events[0].get("qa_gate", {}).get("defects", [])[0].get("source") != "a.mp4":
        raise SystemExit("QA diagnostics were not attached to events")

    with tempfile.TemporaryDirectory() as td:
        meta_file = os.path.join(td, "reels_metadata.json")
        with open(meta_file, "w", encoding="utf-8") as handle:
            json.dump({"DRAFT_test.mp4": {"sport": "surfing", "events": []}}, handle)
        _augment_metadata_file(meta_file, "DRAFT_test.mp4", diag)
        saved = json.load(open(meta_file, encoding="utf-8"))
        if saved["DRAFT_test.mp4"].get("qa_gate", {}).get("critical_defect_count") != 2:
            raise SystemExit("QA gate metadata was not persisted")

    text = (ROOT / "pipeline/qa_gate_policy.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    for token in ["_OrchestratorPatchFinder", "_OrchestratorPatchLoader", "_patch_orchestrator", "original_qa_gate", "original_save_metadata", "qa_gate_with_diagnostics", "save_metadata_with_qa"]:
        if token not in text:
            raise SystemExit(f"missing install token: {token}")
    if "import pipeline.orchestrator" in text:
        raise SystemExit("QA gate policy must not import orchestrator during bootstrap")
    if "pipeline.qa_gate_policy" not in boot:
        raise SystemExit("QA gate policy is not bootstrapped")

    print("QA gate diagnostics contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
