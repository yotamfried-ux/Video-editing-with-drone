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
    from pipeline.draft_diagnostics import REQUIRED_SECTIONS, augment_metadata_entry, build_diagnostic_artifact

    events = [
        {
            "event_id": "ev1",
            "_src": "raw/cam_a.mp4",
            "type": "cutback",
            "score": 9,
            "original_start": 10,
            "original_end": 24,
            "start": 11,
            "end": 22,
            "final_cut_start": 11,
            "final_cut_end": 22,
            "cut_adjustment_reason": "cap_preserved_action",
            "description": "surfer completes a cutback",
            "track_id": "track-7",
            "bbox_xyxy": [10, 20, 80, 140],
            "perception_confidence": 0.91,
            "visible_ratio": 0.88,
            "identity_confidence": "high",
            "_is_climax": True,
            "dedup_dropped_duplicates": [{"source": "raw/cam_b.mp4", "reason": "same_wave"}],
            "qa_gate": {
                "decision": "flagged_manual_review",
                "final_verdict": "FAIL",
                "retry_count": 2,
                "defects": [
                    {"type": "BAD_FRAMING", "severity": "critical", "event_id": "ev1", "source": "raw/cam_a.mp4", "blocking": True}
                ],
            },
        }
    ]
    artifact = build_diagnostic_artifact("DRAFT_test.mp4", "surfing", events, {"width": 1920, "height": 1080}, "review/DRAFT_test.mp4")
    for section in REQUIRED_SECTIONS:
        if section not in artifact:
            raise SystemExit(f"missing artifact section: {section}")
    if artifact["final_upload_key"] != "review/DRAFT_test.mp4":
        raise SystemExit("final upload key missing")
    if artifact["source_videos"][0]["name"] != "cam_a.mp4":
        raise SystemExit("source video trace missing")
    if artifact["raw_gemini_events"][0]["start"] != 10:
        raise SystemExit("raw Gemini event timing missing")
    if artifact["perception_tracks"][0]["track_id"] != "track-7":
        raise SystemExit("perception track missing")
    if artifact["identity_clusters"][0]["members"][0]["identity_confidence"] != "high":
        raise SystemExit("identity cluster metadata missing")
    if artifact["ordered_events"][0]["is_climax"] is not True:
        raise SystemExit("ordered event narrative role missing")
    if len(artifact["dropped_events"]) < 2:
        raise SystemExit("dropped event diagnostics missing")
    if artifact["qa"]["retry_count"] != 2:
        raise SystemExit("QA retry diagnostics missing")

    with tempfile.TemporaryDirectory() as td:
        meta_file = os.path.join(td, "reels_metadata.json")
        with open(meta_file, "w", encoding="utf-8") as handle:
            json.dump({"DRAFT_test.mp4": {"sport": "surfing"}}, handle)
        augment_metadata_entry(meta_file, "DRAFT_test.mp4", artifact)
        saved = json.load(open(meta_file, encoding="utf-8"))
        if saved["DRAFT_test.mp4"].get("diagnostic_artifact", {}).get("qa", {}).get("final_verdict") != "FAIL":
            raise SystemExit("diagnostic artifact was not persisted")

    text = (ROOT / "pipeline/draft_diagnostics.py").read_text(encoding="utf-8")
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    for token in ["build_diagnostic_artifact", "augment_metadata_entry", "_wrap_qa_hook", "save_with_diagnostics"]:
        if token not in text:
            raise SystemExit(f"missing install token: {token}")
    if "importlib.abc" in text or "MetaPathFinder" in text:
        raise SystemExit("draft diagnostics must compose with QA hook, not install a competing import hook")
    if "pipeline.draft_diagnostics" not in boot:
        raise SystemExit("draft diagnostics is not bootstrapped")

    print("Draft diagnostics contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
