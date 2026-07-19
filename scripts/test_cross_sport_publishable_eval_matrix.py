#!/usr/bin/env python3
"""Cross-sport eval matrix for centered-athlete silent publishable reels."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PERFORMANCE_POLICY_PATH = ROOT / "pipeline/performance_reel_policy.py"
SILENT_POLICY_PATH = ROOT / "pipeline/silent_output_policy.py"
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strict_part(index: int, name: str, duration: float) -> dict[str, Any]:
    return {
        "part_index": index,
        "file_name": name,
        "storage_object_id": f"review/{name}",
        "authoritative_publishability_required": True,
        "authoritative_publishability_persisted": True,
        "authoritative_manifest_revision": f"manifest-{index}",
        "uploaded_to_review": True,
        "upload_error": None,
        "publishable": True,
        "qa_evidence_recorded": True,
        "qa_verdict": "PASS",
        "qa_passed": True,
        "has_audio": False,
        "technical_issues": [],
        "duration": duration,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def assert_cross_sport_manifest(checker: Any) -> None:
    payload = {
        "schema_version": "sportreel.publishable_reel_manifest.v1",
        "athletes": [
            {
                "athlete_key": "football_7",
                "athlete_ids": ["athlete_football_7"],
                "athlete_label": "player #7 in red",
                "eligible": True,
                "parts": [strict_part(1, "DRAFT_player_7.mp4", 24.0)],
                "primary_publishable_reel": "DRAFT_player_7.mp4",
                "supplemental_publishable_reels": [],
            },
            {
                "athlete_key": "skater_blue",
                "athlete_ids": ["athlete_skater_blue"],
                "athlete_label": "skater in blue helmet",
                "eligible": True,
                "parts": [strict_part(1, "DRAFT_skater_blue.mp4", 18.0)],
                "primary_publishable_reel": "DRAFT_skater_blue.mp4",
                "supplemental_publishable_reels": [],
            },
        ],
        "summary": {
            "eligible_athlete_count": 2,
            "publishable_athlete_count": 2,
            "primary_publishable_reel_count": 2,
            "supplemental_publishable_reel_count": 0,
            "coverage_gap_count": 0,
        },
    }
    coverage = {
        "summary": {
            "coverage_gap_cluster_count": 0,
            "athlete_accountability_rate": 1.0,
            "selected_identity_lineage_completeness_rate": 1.0,
        },
        "athletes": [
            {
                "athlete_cluster_id": "match.mp4::person_A",
                "athlete_ids": ["athlete_football_7"],
                "candidate_action_count": 1,
                "selected_action_count": 1,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            },
            {
                "athlete_cluster_id": "skate.mp4::person_A",
                "athlete_ids": ["athlete_skater_blue"],
                "candidate_action_count": 1,
                "selected_action_count": 1,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            },
        ],
    }
    errors = checker.validate_manifest(payload, coverage)
    if errors:
        raise SystemExit(f"valid strict two-sport manifest failed: {errors}")


def assert_centered_athlete_with_active_others() -> None:
    from pipeline.primary_actor_policy import ambiguity_reasons, classify_primary_actor

    cases = [
        {
            "name": "football group play",
            "event": {
                "athlete_id": "player_7",
                "primary_actor_clear": True,
                "primary_actor_confidence": 0.94,
                "identity_continuity": "stable",
                "multiple_active_subjects": True,
                "competing_active_subjects": True,
            },
            "visible": 5,
            "continuity": 0.88,
        },
        {
            "name": "shared surf wave",
            "event": {
                "athlete_id": "surfer_target",
                "primary_actor_clear": True,
                "primary_actor_confidence": 0.91,
                "identity_continuity": "stable",
                "multiple_active_subjects": True,
                "competing_active_subjects": True,
            },
            "visible": 2,
            "continuity": 0.82,
        },
    ]
    for case in cases:
        event = case["event"]
        if ambiguity_reasons(event):
            raise SystemExit(f"{case['name']} was rejected despite positive centrality evidence")
        gate = classify_primary_actor(
            event,
            visible_subject_count=case["visible"],
            primary_continuity_ratio=case["continuity"],
        )
        if gate.get("decision") != "allowed_primary_actor_clear":
            raise SystemExit(f"{case['name']} was blocked: {gate}")
        if gate.get("other_people_allowed") is not True:
            raise SystemExit(f"{case['name']} did not preserve surrounding participants")

    insufficient = {
        "athlete_id": "surfer_target",
        "multiple_active_subjects": True,
        "competing_active_subjects": True,
    }
    if not ambiguity_reasons(insufficient):
        raise SystemExit("target ID alone approved a crowded/shared-wave action")
    if classify_primary_actor(insufficient, visible_subject_count=2).get("decision") != "review_required":
        raise SystemExit("missing centrality evidence did not fail closed")


def assert_whole_wave_boundaries(performance: Any) -> None:
    waves = [
        {
            "event_id": f"wave-{index}",
            "athlete_id": "surfer_all_waves",
            "type": "wave_catch",
            "sport": "surfing",
            "start": float(index * 30),
            "end": float(index * 30 + 18),
            "score": 4 if index == 3 else 8,
            "_src": "surf-session.mp4",
            "edit": {"slowmo": False},
        }
        for index in range(1, 7)
    ]
    parts = performance.partition_complete_performance_reels(waves, False)
    flattened = [wave for part in parts for wave in part]
    if [wave["event_id"] for wave in flattened] != [wave["event_id"] for wave in waves]:
        raise SystemExit("surf eval dropped, duplicated, or reordered a complete wave")
    if len(parts) < 2:
        raise SystemExit("six complete waves were not split into multiple Parts")
    expected_windows = {
        wave["event_id"]: (wave["start"], wave["end"])
        for wave in waves
    }
    for wave in flattened:
        actual = (wave.get("start"), wave.get("end"))
        if actual != expected_windows[wave["event_id"]]:
            raise SystemExit(
                f"wave boundary changed for {wave['event_id']}: "
                f"expected {expected_windows[wave['event_id']]}, got {actual}"
            )


def assert_silent_matrix(silent: Any) -> None:
    valid = {
        "has_audio": False,
        "duration": 30.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }
    if silent.silent_social_ready_issues(valid):
        raise SystemExit("valid silent vertical output failed")
    cases = {
        "unexpected_audio": valid | {"has_audio": True},
        "audio_state_unknown": valid | {"has_audio": None},
        "duration_over_90_seconds": valid | {"duration": 91.0},
        "aspect_not_9_16": valid | {"aspect": 16 / 9},
        "resolution_below_publishable_floor": valid | {"height": 960},
    }
    for expected, payload in cases.items():
        if expected not in silent.silent_social_ready_issues(payload):
            raise SystemExit(f"silent negative matrix did not produce {expected}")


def assert_source_contract() -> None:
    actor = (ROOT / "pipeline/primary_actor_policy.py").read_text(encoding="utf-8")
    selection = (ROOT / "pipeline/single_athlete_selection_policy.py").read_text(encoding="utf-8")
    silent = SILENT_POLICY_PATH.read_text(encoding="utf-8")
    required = {
        "actor": (actor, ["primary_athlete_centered", "other_people_allowed", "_centered_evidence_gaps"]),
        "selection": (selection, ["two surfers on the same wave", "target surfer remains the central"]),
        "silent": (silent, ["video-only, no-audio product contract", "editor._pick_music = no_music_picker", "unexpected_audio"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} missing cross-sport contract tokens: {missing}")


def main() -> int:
    checker = load_module("cross_sport_checker", CHECKER_PATH)
    performance = load_module("cross_sport_performance", PERFORMANCE_POLICY_PATH)
    silent = load_module("cross_sport_silent", SILENT_POLICY_PATH)
    assert_cross_sport_manifest(checker)
    assert_centered_athlete_with_active_others()
    assert_whole_wave_boundaries(performance)
    assert_silent_matrix(silent)
    assert_source_contract()
    print("Centered-athlete silent cross-sport eval matrix passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
