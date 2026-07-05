#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pipeline.draft_diagnostics import build_diagnostic_artifact
from pipeline.multi_person_clip_gate import annotate_multi_person_events, has_multi_person_defect
from pipeline.qa_gate_policy import BLOCKING_DEFECT_TYPES, is_critical_defect

ROOT = Path(__file__).resolve().parents[1]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(msg)


def main() -> int:
    review_events = annotate_multi_person_events([
        {"event_id": "ride_1", "type": "surf_ride", "track_id": "main", "source_window_track_ids": ["main", "extra"], "start": 1, "end": 9}
    ])
    review_event = review_events[0]
    gate = review_event.get("multi_person_clip_gate", {})
    require(gate.get("decision") == "review_required", "multi-subject ride must require review")
    require(has_multi_person_defect(review_events), "review-required gate was not detected")
    qa_gate = review_event.get("qa_gate", {})
    defects = qa_gate.get("defects", [])
    require(qa_gate.get("qa_review_required") is True, "qa review flag missing")
    require(defects and defects[0].get("type") == "MULTI_PERSON_CLIP", "MULTI_PERSON_CLIP defect missing")
    require(is_critical_defect(defects[0]), "MULTI_PERSON_CLIP must be a critical QA defect")

    allowed_events = annotate_multi_person_events([
        {"event_id": "social_1", "type": "high_five", "track_id": "main", "source_window_track_ids": ["main", "friend"], "value_labels": ["SOCIAL_MOMENT", "HIGH_FIVE"], "start": 3, "end": 6}
    ])
    allowed_gate = allowed_events[0].get("multi_person_clip_gate", {})
    require(allowed_gate.get("decision") == "allowed_social_moment", "intentional social moment should be allowed")
    require(not has_multi_person_defect(allowed_events), "allowed social moment should not be review-required")
    require("qa_gate" not in allowed_events[0], "allowed social moment should not get QA defect")

    artifact = build_diagnostic_artifact("DRAFT_multi_person.mp4", "surfing", review_events, {}, "review/DRAFT_multi_person.mp4")
    require(artifact["identity_clusters"][0]["members"][0].get("multi_person_clip_gate", {}).get("decision") == "review_required", "diagnostic member gate missing")
    require(artifact["ordered_events"][0].get("multi_person_clip_gate", {}).get("decision") == "review_required", "diagnostic ordered gate missing")
    require(any(item.get("reason") == "MULTI_PERSON_CLIP" for item in artifact["dropped_events"]), "diagnostic dropped reason missing")

    require("MULTI_PERSON_CLIP" in BLOCKING_DEFECT_TYPES, "MULTI_PERSON_CLIP not blocking")
    require("IDENTITY_UNCERTAIN" in BLOCKING_DEFECT_TYPES, "IDENTITY_UNCERTAIN not blocking")

    context = (ROOT / "pipeline/context_qa_gate.py").read_text(encoding="utf-8")
    require("annotate_multi_person_events" in context, "context QA does not annotate multi-person events")
    require("has_multi_person_defect" in context, "context QA does not mark review-required multi-person reels")
    require("multi_person_clip_gate" in context, "context QA does not expose multi-person gate")

    print("multi-person clip gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
