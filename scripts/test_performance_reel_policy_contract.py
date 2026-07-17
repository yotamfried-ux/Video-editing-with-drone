#!/usr/bin/env python3
"""Regression contract for coverage-first per-athlete performance reels."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pipeline/performance_reel_policy.py"
sys.path.insert(0, str(ROOT))


def load_policy():
    spec = importlib.util.spec_from_file_location("performance_reel_policy_contract", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load performance_reel_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(index: int, start: float, end: float, score: int = 7, **extra):
    return {
        "event_id": f"wave-{index}",
        "type": "surf_ride",
        "sport": "surfing",
        "start": start,
        "end": end,
        "score": score,
        "description": f"complete readable wave {index}",
        "_src": "session.mp4",
        **extra,
    }


def main() -> int:
    policy = load_policy()

    readable_low_score = event(1, 0, 12, score=4)
    failed_takeoff = event(
        2,
        20,
        23,
        score=4,
        ride_completed=False,
        hard_reject_reason="failed_takeoff",
        description="falls immediately during a failed takeoff",
    )
    high_score_failed_takeoff = event(
        3,
        30,
        34,
        score=8,
        ride_completed=False,
        hard_reject_reason="no_ride_established",
        description="misses the wave and never stands",
    )
    non_surf = {"type": "walk", "sport": "football", "score": 4, "start": 0, "end": 8}
    if not policy.keep_event_for_performance_reel(readable_low_score, "surfing"):
        raise SystemExit("readable low-score surf ride was incorrectly discarded")
    if policy.keep_event_for_performance_reel(failed_takeoff, "surfing"):
        raise SystemExit("explicit failed takeoff was incorrectly preserved")
    if policy.keep_event_for_performance_reel(high_score_failed_takeoff, "surfing"):
        raise SystemExit("high score bypassed explicit no-ride evidence")
    if policy.keep_event_for_performance_reel(non_surf, "football"):
        raise SystemExit("generic low-score non-surf event bypassed the existing quality floor")

    waves = [
        event(1, 0, 18, 8),
        event(2, 30, 48, 7),
        event(3, 60, 78, 9),
        event(4, 90, 108, 7),
        event(5, 120, 138, 8),
        event(6, 150, 168, 6),
    ]
    parts = policy.partition_complete_performance_reels(
        waves,
        slowmo_capable=False,
        target_max=89.0,
        xfade_dur=0.25,
    )
    flattened = [item for part in parts for item in part]
    ids = [item["event_id"] for item in flattened]
    if ids != [f"wave-{index}" for index in range(1, 7)]:
        raise SystemExit(f"waves were reordered, duplicated, or discarded: {ids}")
    if len(parts) != 2:
        raise SystemExit(f"six 18-second waves should split into two reels, got {len(parts)}")
    for part_index, part in enumerate(parts, start=1):
        if not part:
            raise SystemExit("empty performance reel part created")
        estimated = float(part[0]["performance_reel_estimated_part_duration"])
        if estimated > 89.0:
            raise SystemExit(f"part {part_index} exceeds the safe 90-second budget: {estimated}")
        if any(item["performance_reel_part"] != part_index for item in part):
            raise SystemExit("part metadata does not match packing result")
        if any(item["performance_reel_total_wave_count"] != 6 for item in part):
            raise SystemExit("total wave coverage metadata is incomplete")

    # Duplicate removal must happen before packing, otherwise the same wave can
    # land once near the end of Part 1 and again at the start of Part 2.
    from pipeline.final_duplicate_guard import remove_duplicate_events

    duplicate_across_boundary = [
        event(10, 0, 44, 8, event_fingerprint="same-wave"),
        event(11, 50, 94, 7),
        event(12, 100, 144, 9, event_fingerprint="same-wave"),
    ]
    deduplicated = remove_duplicate_events(duplicate_across_boundary)
    duplicate_parts = policy.partition_complete_performance_reels(
        deduplicated,
        slowmo_capable=False,
        target_max=89.0,
        xfade_dur=0.25,
    )
    duplicate_ids = [item["event_id"] for part in duplicate_parts for item in part]
    if len(duplicate_ids) != 2 or len(set(duplicate_ids)) != 2:
        raise SystemExit(f"duplicate wave crossed a performance-reel boundary: {duplicate_ids}")

    defects = [
        {"type": "DEAD_TIME", "severity": "critical"},
        {"type": "LOW_QUALITY", "severity": "critical"},
        {"type": "BAD_FIRST_CLIP", "severity": "critical"},
        {"type": "IDENTITY_MISMATCH", "severity": "critical"},
        {"type": "PREMATURE_CUT", "severity": "critical"},
    ]
    filtered = policy._filter_surf_qa_defects(defects)
    filtered_types = {item["type"] for item in filtered}
    if filtered_types != {"IDENTITY_MISMATCH", "PREMATURE_CUT"}:
        raise SystemExit(f"QA deletion policy retained the wrong defect set: {filtered_types}")

    policy_source = POLICY_PATH.read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    review = (ROOT / "mobile/src/app/(operator)/review.tsx").read_text(encoding="utf-8")
    for source in (policy_source, sitecustomize, bootstrap):
        ast.parse(source)

    required_policy_tokens = [
        "EVERY DISTINCT WAVE RIDE",
        "MAX_PERFORMANCE_REEL_SEC = 89.0",
        "performance_reel_total_wave_count",
        "QA_FAIL: Reel did not pass final quality review.",
        "feedback.get_negative_feedback_hint = lambda: \"\"",
        "remove_duplicate_events(list(events or []))",
        "if surf_event and is_explicit_failed_takeoff",
    ]
    missing = [token for token in required_policy_tokens if token not in policy_source]
    if missing:
        raise SystemExit(f"performance policy is missing contract tokens: {missing}")
    if "pipeline.performance_reel_policy" not in sitecustomize:
        raise SystemExit("production scripts do not install the performance reel policy")
    if "pipeline.performance_reel_policy" not in bootstrap:
        raise SystemExit("shared bootstrap does not install the performance reel policy")
    forbidden_review_tokens = [
        "FEEDBACK_FLAGS",
        "DraftFeedbackResponse",
        "OperatorFeedbackEvent",
        "submitFlag",
        "Feedback recorded",
    ]
    present = [token for token in forbidden_review_tokens if token in review]
    if present:
        raise SystemExit(f"button-based feedback UI is still present: {present}")
    for required in [
        "Performance reels waiting for review",
        "QA passed · ready to review",
        "Send QA notes to re-edit",
    ]:
        if required not in review:
            raise SystemExit(f"review screen missing clear product status: {required}")

    print("Performance reel policy contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
