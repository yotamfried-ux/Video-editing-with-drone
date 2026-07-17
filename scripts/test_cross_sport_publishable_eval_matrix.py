#!/usr/bin/env python3
"""Cross-sport eval matrix for centered-athlete silent publishable reels."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PUBLISHABLE_POLICY_PATH = ROOT / "pipeline/publishable_reel_policy.py"
SILENT_POLICY_PATH = ROOT / "pipeline/silent_output_policy.py"
PERFORMANCE_POLICY_PATH = ROOT / "pipeline/performance_reel_policy.py"
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs(duration: float = 24.0, *, audio: bool = False) -> dict[str, Any]:
    return {
        "has_audio": audio,
        "duration": duration,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def action(
    *,
    athlete_id: str,
    action_type: str,
    sport: str,
    start: float,
    end: float,
    source: str,
    score: int = 8,
) -> dict[str, Any]:
    return {
        "athlete_id": athlete_id,
        "type": action_type,
        "sport": sport,
        "start": start,
        "end": end,
        "score": score,
        "_src": source,
    }


def record_uploaded_athlete(
    policy: Any,
    *,
    sport: str,
    label: str,
    local_path: str,
    draft_name: str,
    event: dict[str, Any],
) -> None:
    policy.record_athlete_outcome(
        sport=sport,
        athlete_label=label,
        final_reels=[local_path],
        events_by_reel={local_path: [event]},
        flagged_paths=set(),
        specs_getter=lambda _path: specs(),
    )
    if not policy.mark_upload_result(local_path, draft_name):
        raise SystemExit(f"could not attach upload for {label}")


def assert_cross_sport_primary_outputs(policy: Any, checker: Any, tmp: Path) -> None:
    manifest = tmp / "publishable_reel_manifest.json"
    os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
    policy.reset_manifest()

    football_path = str(tmp / "football_player_7.mp4")
    skateboard_path = str(tmp / "skater_blue_helmet.mp4")
    football_event = action(
        athlete_id="athlete_football_7",
        action_type="goal",
        sport="football",
        start=12,
        end=22,
        source="match.mp4",
    )
    skateboard_event = action(
        athlete_id="athlete_skater_blue",
        action_type="trick",
        sport="skateboarding",
        start=30,
        end=39,
        source="skate-session.mp4",
    )
    record_uploaded_athlete(
        policy,
        sport="football",
        label="player #7 in red",
        local_path=football_path,
        draft_name="DRAFT_player_7_primary.mp4",
        event=football_event,
    )
    record_uploaded_athlete(
        policy,
        sport="skateboarding",
        label="skater in blue helmet",
        local_path=skateboard_path,
        draft_name="DRAFT_blue_helmet_primary.mp4",
        event=skateboard_event,
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    coverage = {
        "summary": {
            "coverage_gap_cluster_count": 0,
            "athlete_accountability_rate": 1.0,
        },
        "athletes": [
            {
                "athlete_cluster_id": "match.mp4::person_A",
                "athlete_ids": ["athlete_football_7"],
                "descriptions": ["player #7 in red"],
                "candidate_action_count": 1,
                "selected_action_count": 1,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            },
            {
                "athlete_cluster_id": "skate-session.mp4::person_A",
                "athlete_ids": ["athlete_skater_blue"],
                "descriptions": ["skater in blue helmet"],
                "candidate_action_count": 1,
                "selected_action_count": 1,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            },
        ],
    }
    errors = checker.validate_manifest(payload, coverage)
    if errors:
        raise SystemExit(f"valid two-athlete silent cross-sport manifest failed: {errors}")
    if payload["summary"]["eligible_athlete_count"] != 2:
        raise SystemExit("cross-sport manifest did not retain both eligible athletes")
    if payload["summary"]["primary_publishable_reel_count"] != 2:
        raise SystemExit("one-action athletes did not each receive a primary reel")
    if any(
        part.get("has_audio") is not False
        for row in payload["athletes"]
        for part in row.get("parts", [])
    ):
        raise SystemExit("cross-sport outputs were not silent")


def assert_same_description_distinct_ids(policy: Any, checker: Any, tmp: Path) -> None:
    manifest = tmp / "similar-athletes.json"
    os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
    policy.reset_manifest()
    for index, athlete_id in enumerate(("surfer_orange_A", "surfer_orange_B"), start=1):
        local = str(tmp / f"similar_surfer_{index}.mp4")
        record_uploaded_athlete(
            policy,
            sport="surfing",
            label="surfer in black wetsuit on orange board",
            local_path=local,
            draft_name=f"DRAFT_orange_surfer_{index}.mp4",
            event=action(
                athlete_id=athlete_id,
                action_type="wave_catch",
                sport="surfing",
                start=index * 20,
                end=index * 20 + 12,
                source=f"camera-{index}.mp4",
            ),
        )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if len(payload["athletes"]) != 2:
        raise SystemExit("visually similar athletes were collapsed despite distinct canonical IDs")
    if checker.validate_manifest(payload):
        raise SystemExit("distinct canonical silent athletes failed the manifest contract")


def assert_surf_whole_wave_packing(performance: Any) -> None:
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
    flattened = [wave["event_id"] for part in parts for wave in part]
    if flattened != [wave["event_id"] for wave in waves]:
        raise SystemExit("surf eval dropped, duplicated, or reordered a complete wave")
    if len(parts) < 2:
        raise SystemExit("six complete waves were not split into multiple platform-valid parts")
    if any(
        part[index]["end"] != waves[flattened.index(part[index]["event_id"])]["end"]
        for part in parts
        for index in range(len(part))
    ):
        raise SystemExit("surf packing changed a complete wave boundary")


def assert_centered_athlete_with_active_others() -> None:
    from pipeline.primary_actor_policy import ambiguity_reasons, classify_primary_actor

    football = {
        "athlete_id": "player_7",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.94,
        "identity_continuity": "stable",
        "background_people_present": True,
        "multiple_active_subjects": True,
        "competing_active_subjects": True,
        "description": "Player #7 dribbles through two defenders and scores.",
    }
    if ambiguity_reasons(football):
        raise SystemExit("active football participants incorrectly created actor ambiguity")
    football_gate = classify_primary_actor(football, visible_subject_count=5, primary_continuity_ratio=0.88)
    if football_gate.get("decision") != "allowed_primary_actor_clear":
        raise SystemExit(f"centered football player was blocked: {football_gate}")
    if football_gate.get("other_people_allowed") is not True:
        raise SystemExit("football context did not record that other active people are allowed")

    same_wave = {
        "athlete_id": "surfer_target",
        "primary_actor_clear": True,
        "primary_actor_confidence": 0.91,
        "identity_continuity": "stable",
        "background_people_present": True,
        "multiple_active_subjects": True,
        "competing_active_subjects": True,
        "description": "Target surfer remains central while another surfer enters the same wave.",
    }
    if ambiguity_reasons(same_wave):
        raise SystemExit("another surfer on the same wave incorrectly invalidated the target ride")
    surf_gate = classify_primary_actor(same_wave, visible_subject_count=2, primary_continuity_ratio=0.82)
    if surf_gate.get("decision") != "allowed_primary_actor_clear":
        raise SystemExit(f"centered same-wave surfer was blocked: {surf_gate}")
    if surf_gate.get("primary_athlete_centered") is not True:
        raise SystemExit("same-wave result did not preserve the target surfer as the center")

    ambiguous_same_wave = {
        **same_wave,
        "primary_actor_clear": False,
        "identity_continuity": "uncertain",
        "primary_actor_confidence": 0.3,
    }
    if not ambiguity_reasons(ambiguous_same_wave):
        raise SystemExit("uncertain same-wave identity was not blocked")
    blocked = classify_primary_actor(ambiguous_same_wave, visible_subject_count=2, primary_continuity_ratio=0.35)
    if blocked.get("decision") != "review_required":
        raise SystemExit("uncertain same-wave identity did not become review-required")


def assert_source_contracts() -> None:
    analyzer = (ROOT / "pipeline/stages/analyzer.py").read_text(encoding="utf-8")
    identity = (ROOT / "pipeline/stages/identity.py").read_text(encoding="utf-8")
    identity_failsafe = (ROOT / "pipeline/identity_failsafe.py").read_text(encoding="utf-8")
    actor_policy = (ROOT / "pipeline/primary_actor_policy.py").read_text(encoding="utf-8")
    selection_policy = (ROOT / "pipeline/single_athlete_selection_policy.py").read_text(encoding="utf-8")
    publishable = PUBLISHABLE_POLICY_PATH.read_text(encoding="utf-8")
    silent = SILENT_POLICY_PATH.read_text(encoding="utf-8")

    required = {
        "global one-action contract": (publishable, ["EVERY DISTINCT ATHLETE", "ONE usable action is enough"]),
        "football attribution": (analyzer, ["TEAM SPORTS — ATTRIBUTION", "assign to the TACKLER", "assign to the SCORER"]),
        "uncertain identity split": (identity, ["When uncertain, create separate clusters", "A missed merge is better than a"]),
        "identity fail-safe": (identity_failsafe, ["missing thumbnails for identity verification", "medium confidence without bbox perception evidence"]),
        "centered athlete policy": (actor_policy, ["primary_athlete_centered", "other_people_allowed", "same wave"]),
        "same-wave prompt": (selection_policy, ["two surfers on the same wave", "target surfer remains the central"]),
        "silent output policy": (silent, ["video-only, no-audio product contract", "editor._pick_music = no_music_picker", "unexpected_audio"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} is missing eval-contract tokens: {missing}")


def assert_technical_negative_matrix(silent: Any) -> None:
    cases = {
        "unexpected_audio": (specs(audio=True), "unexpected_audio"),
        "unknown_audio": (specs() | {"has_audio": None}, "audio_state_unknown"),
        "over_90": (specs(91.0), "duration_over_90_seconds"),
        "wrong_aspect": (specs() | {"width": 1920, "height": 1080, "aspect": 1920 / 1080}, "aspect_not_9_16"),
        "low_resolution": (specs() | {"width": 540, "height": 960, "aspect": 540 / 960}, "resolution_below_publishable_floor"),
    }
    for label, (payload, expected) in cases.items():
        issues = silent.silent_social_ready_issues(payload)
        if expected not in issues:
            raise SystemExit(f"technical eval {label} did not produce {expected}: {issues}")
    if silent.silent_social_ready_issues(specs()):
        raise SystemExit("valid silent vertical output failed the technical matrix")


def main() -> int:
    policy = load_module("cross_sport_publishable_policy", PUBLISHABLE_POLICY_PATH)
    silent = load_module("cross_sport_silent_policy", SILENT_POLICY_PATH)
    performance = load_module("cross_sport_performance_policy", PERFORMANCE_POLICY_PATH)
    checker = load_module("cross_sport_publishable_checker", CHECKER_PATH)
    policy.social_ready_issues = silent.silent_social_ready_issues
    policy.canonicalize_publishable_variants = silent.canonicalize_silent_variants

    with tempfile.TemporaryDirectory(prefix="sportreel-cross-sport-eval-") as directory:
        tmp = Path(directory)
        assert_cross_sport_primary_outputs(policy, checker, tmp)
        assert_same_description_distinct_ids(policy, checker, tmp)
    assert_surf_whole_wave_packing(performance)
    assert_centered_athlete_with_active_others()
    assert_source_contracts()
    assert_technical_negative_matrix(silent)
    print("Centered-athlete silent cross-sport eval matrix passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
