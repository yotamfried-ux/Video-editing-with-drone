#!/usr/bin/env python3
"""Cross-sport eval matrix for the per-athlete publishable-reel product contract."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLISHABLE_POLICY_PATH = ROOT / "pipeline/publishable_reel_policy.py"
PERFORMANCE_POLICY_PATH = ROOT / "pipeline/performance_reel_policy.py"
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs(duration: float = 24.0) -> dict[str, Any]:
    return {
        "has_audio": True,
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
        raise SystemExit(f"valid two-athlete cross-sport manifest failed: {errors}")
    if payload["summary"]["eligible_athlete_count"] != 2:
        raise SystemExit("cross-sport manifest did not retain both eligible athletes")
    if payload["summary"]["primary_publishable_reel_count"] != 2:
        raise SystemExit("one-action athletes did not each receive a primary reel")


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
        raise SystemExit("distinct canonical athletes failed the manifest contract")


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
    if any(part[index]["end"] != waves[flattened.index(part[index]["event_id"])]["end"] for part in parts for index in range(len(part))):
        raise SystemExit("surf packing changed a complete wave boundary")


def assert_source_contracts() -> None:
    analyzer = (ROOT / "pipeline/stages/analyzer.py").read_text(encoding="utf-8")
    identity = (ROOT / "pipeline/stages/identity.py").read_text(encoding="utf-8")
    identity_failsafe = (ROOT / "pipeline/identity_failsafe.py").read_text(encoding="utf-8")
    actor_policy = (ROOT / "pipeline/primary_actor_policy.py").read_text(encoding="utf-8")
    publishable = PUBLISHABLE_POLICY_PATH.read_text(encoding="utf-8")

    required = {
        "global one-action contract": (publishable, ["EVERY DISTINCT ATHLETE", "ONE usable action is enough"]),
        "football attribution": (analyzer, ["TEAM SPORTS — ATTRIBUTION", "assign to the TACKLER", "assign to the SCORER"]),
        "uncertain identity split": (identity, ["When uncertain, create separate clusters", "A missed merge is better than a"]),
        "identity fail-safe": (identity_failsafe, ["missing thumbnails for identity verification", "medium confidence without bbox perception evidence"]),
        "background people policy": (actor_policy, ["background_people_allowed", "primary_actor"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} is missing eval-contract tokens: {missing}")


def assert_technical_negative_matrix(policy: Any) -> None:
    cases = {
        "no_audio": (specs() | {"has_audio": False}, "missing_audio"),
        "over_90": (specs(91.0), "duration_over_90_seconds"),
        "wrong_aspect": (specs() | {"width": 1920, "height": 1080, "aspect": 1920 / 1080}, "aspect_not_9_16"),
        "low_resolution": (specs() | {"width": 540, "height": 960, "aspect": 540 / 960}, "resolution_below_publishable_floor"),
    }
    for label, (payload, expected) in cases.items():
        issues = policy.social_ready_issues(payload)
        if expected not in issues:
            raise SystemExit(f"technical eval {label} did not produce {expected}: {issues}")


def main() -> int:
    policy = load_module("cross_sport_publishable_policy", PUBLISHABLE_POLICY_PATH)
    performance = load_module("cross_sport_performance_policy", PERFORMANCE_POLICY_PATH)
    checker = load_module("cross_sport_publishable_checker", CHECKER_PATH)
    with tempfile.TemporaryDirectory(prefix="sportreel-cross-sport-eval-") as directory:
        tmp = Path(directory)
        assert_cross_sport_primary_outputs(policy, checker, tmp)
        assert_same_description_distinct_ids(policy, checker, tmp)
    assert_surf_whole_wave_packing(performance)
    assert_source_contracts()
    assert_technical_negative_matrix(policy)
    print("Cross-sport publishable reel eval matrix passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
