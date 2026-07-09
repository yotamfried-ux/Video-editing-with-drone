#!/usr/bin/env python3
"""Contract test for long-video pre-QA subject gate filtering.

This is intentionally source-level: the bug was a production behavior gap where
long-video candidates were rendered and uploaded even though the same context QA
metadata already knew they were single-athlete drafts with extra visible
subjects. The contract keeps that policy from regressing without needing real
R2/Gemini credentials in CI.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pipeline" / "context_qa_long_video.py"


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    required = [
        "def _prepare_events_for_render",
        "_annotate_subject_gates(events or [], local_path, athlete_label)",
        "clean = [event for event in annotated if not _has_subject_gate_defect([event])]",
        "_dedupe_render_events(clean)",
        "_strip_runtime_event_keys(event)",
        "No clean single-athlete events",
        "Pre-QA skipped",
        "orchestrator.create_reel(local_path, render_events",
        "raw_events = events_by_reel.get(reel, render_events)",
    ]
    missing = [token for token in required if token not in text]
    if missing:
        raise AssertionError(f"long-video subject prefilter contract missing tokens: {missing}")

    # Guard the specific regression from run 28992279625: MULTI_PERSON_CLIP was
    # discovered only after upload. The render path must call the prefilter before
    # create_reel, so the first create_reel call should use render_events.
    prepare_idx = text.index("render_events, blocked_count, duplicate_count = _prepare_events_for_render")
    create_idx = text.index("orchestrator.create_reel(local_path, render_events")
    if prepare_idx > create_idx:
        raise AssertionError("long-video create_reel runs before subject-gate prefilter")

    print("long-video subject prefilter contract ok")


if __name__ == "__main__":
    main()
