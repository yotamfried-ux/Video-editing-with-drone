#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pipeline.draft_diagnostics import build_diagnostic_artifact
from pipeline.multi_person_clip_gate import annotate_multi_person_events, has_multi_person_defect
from pipeline.qa_gate_policy import BLOCKING_DEFECT_TYPES, is_critical_defect
from pipeline.subject_gate_policy import build_subject_gate, effective_cut_window, has_subject_isolation_defect

ROOT = Path(__file__).resolve().parents[1]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(msg)


def det(track_id: int, time_sec: float) -> dict:
    return {
        "source_video": "source.mp4",
        "time_sec": time_sec,
        "track_id": track_id,
        "raw_track_id": track_id,
        "bbox_xyxy": [100, 100, 200, 300],
        "frame_width": 1920,
        "frame_height": 1080,
    }


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

    subject_event = {"event_id": "ride_2", "type": "surf_ride", "start": 10, "end": 30, "score": 8}
    subject_gate = build_subject_gate(
        subject_event,
        [det(1, 20.0), det(1, 21.0), det(2, 20.5), det(2, 21.5)],
        0,
        source_video="source.mp4",
    )
    require(subject_gate is not None, "subject gate should detect multiple significant canonical tracks")
    require(subject_gate.get("decision") == "review_required", "subject gate must require review")
    require(subject_gate.get("defect", {}).get("type") == "MULTI_PERSON_CLIP", "subject gate defect missing")
    dominant_gate = build_subject_gate(
        subject_event,
        [det(1, 20.0), det(1, 21.0), det(1, 22.0), det(2, 20.5)],
        0,
        source_video="source.mp4",
    )
    require(dominant_gate is None, "dominant primary track should not be flagged")
    capped = effective_cut_window({"start": 1.0, "end": 25.0})
    require(capped == (14.0, 25.0), f"non-climax window should match actual editor cap: {capped}")
    subject_review_event = {
        **subject_event,
        "subject_isolation_gate": subject_gate,
        "qa_gate": {"qa_review_required": True, "defects": [subject_gate["defect"]]},
    }
    require(has_subject_isolation_defect([subject_review_event]), "subject isolation defect not detected")

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
    require("annotate_subject_events" in context, "context QA does not annotate subject gates")
    require("has_subject_isolation_defect" in context, "context QA does not mark subject isolation reels")
    require("subject_isolation_gate" in context, "context QA does not expose subject gate")

    long_context = (ROOT / "pipeline/context_qa_long_video.py").read_text(encoding="utf-8")
    require("annotate_subject_events" in long_context, "long-video context QA does not annotate subject gates")
    require("has_subject_isolation_defect" in long_context, "long-video context QA does not mark subject isolation reels")
    require("QA-FLAGGED" in long_context, "long-video subject drafts must be visibly QA-FLAGGED")

    print("multi-person clip gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
