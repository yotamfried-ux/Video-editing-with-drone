#!/usr/bin/env python3
"""Regression tests for one silent publishable reel per eligible athlete."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
POLICY_PATH = ROOT / "pipeline/publishable_reel_policy.py"
SILENT_POLICY_PATH = ROOT / "pipeline/silent_output_policy.py"
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs(*, audio: bool = False, duration: float = 30.0, width: int = 1080, height: int = 1920) -> dict[str, Any]:
    return {
        "has_audio": audio,
        "duration": duration,
        "width": width,
        "height": height,
        "aspect": width / height,
    }


def event(index: int, source: str = "session.mp4", athlete_id: str = "athlete_7") -> dict[str, Any]:
    return {
        "event_id": f"action-{index}",
        "athlete_id": athlete_id,
        "type": "goal" if index == 1 else "save",
        "sport": "football",
        "start": float(index * 10),
        "end": float(index * 10 + 8),
        "score": 8,
        "_src": source,
    }


def assert_canonical_variant_selection(silent: Any, tmp: Path) -> None:
    clean = tmp / "MULTI_player_p1.mp4"
    music = tmp / "MULTI_player_p1_music.mp4"
    clean.write_bytes(b"silent-publishable")
    music.write_bytes(b"audio-legacy")
    source_events = [(str(clean), [event(1)]), (str(music), [event(1)])]
    spec_map = {
        str(clean): specs(audio=False),
        str(music): specs(audio=True),
    }

    selected, selected_events, failures = silent.canonicalize_silent_variants(
        [str(clean), str(music)],
        source_events,
        specs_getter=lambda path: spec_map[path],
    )
    if selected != [str(clean)]:
        raise SystemExit(f"silent canonical path was not selected: {selected}")
    if failures:
        raise SystemExit(f"valid silent selection produced failures: {failures}")
    if clean.read_bytes() != b"silent-publishable" or music.exists():
        raise SystemExit("audio variant was not removed while preserving the clean render")
    if selected_events != [(str(clean), [event(1)])]:
        raise SystemExit("silent canonical output lost event lineage")

    audio_only = tmp / "MULTI_audio_only.mp4"
    audio_only.write_bytes(b"audio")
    selected, selected_events, failures = silent.canonicalize_silent_variants(
        [str(audio_only)],
        [(str(audio_only), [event(2)])],
        specs_getter=lambda _path: specs(audio=True),
    )
    if selected or selected_events or failures != ["unexpected_audio_variant:MULTI_audio_only.mp4"]:
        raise SystemExit(f"audio-only output was not blocked deterministically: {failures}")
    if audio_only.exists():
        raise SystemExit("audio-only output remained after the silent contract failed")

    part1 = tmp / "MULTI_multi_p1.mp4"
    part1_music = tmp / "MULTI_multi_p1_music.mp4"
    part2 = tmp / "MULTI_multi_p2.mp4"
    part2_music = tmp / "MULTI_multi_p2_music.mp4"
    for path, content in [
        (part1, b"silent1"),
        (part1_music, b"music1"),
        (part2, b"silent2"),
        (part2_music, b"music2"),
    ]:
        path.write_bytes(content)
    spec_map = {
        str(part1): specs(audio=False, duration=70),
        str(part1_music): specs(audio=True, duration=70),
        str(part2): specs(audio=False, duration=25),
        str(part2_music): specs(audio=True, duration=25),
    }
    selected, _, failures = silent.canonicalize_silent_variants(
        [str(part1), str(part1_music), str(part2), str(part2_music)],
        [
            (str(part1), [event(1)]),
            (str(part1_music), [event(1)]),
            (str(part2), [event(2)]),
            (str(part2_music), [event(2)]),
        ],
        specs_getter=lambda path: spec_map[path],
    )
    if selected != [str(part1), str(part2)] or failures:
        raise SystemExit(f"multiple silent parts failed canonical selection: {selected}, {failures}")
    if part1.read_bytes() != b"silent1" or part2.read_bytes() != b"silent2":
        raise SystemExit("silent Part contents were replaced by audio variants")
    if part1_music.exists() or part2_music.exists():
        raise SystemExit("legacy music variants were not deleted")


def coverage_payload(*, athlete_id: str = "athlete_7", description: str = "player #7 in red") -> dict[str, Any]:
    return {
        "summary": {
            "coverage_gap_cluster_count": 0,
            "athlete_accountability_rate": 1.0,
        },
        "athletes": [
            {
                "athlete_cluster_id": "session.mp4::person_A",
                "athlete_ids": [athlete_id],
                "descriptions": [description],
                "candidate_action_count": 2,
                "selected_action_count": 2,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            }
        ],
    }


def assert_manifest_and_gate(policy: Any, checker: Any, silent: Any, tmp: Path) -> None:
    policy.social_ready_issues = silent.silent_social_ready_issues
    policy.canonicalize_publishable_variants = silent.canonicalize_silent_variants

    manifest = tmp / "publishable_reel_manifest.json"
    os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
    policy.reset_manifest()

    p1 = str(tmp / "athlete_p1.mp4")
    p2 = str(tmp / "athlete_p2.mp4")
    spec_map = {
        p1: specs(audio=False, duration=72),
        p2: specs(audio=False, duration=28),
    }
    row = policy.record_athlete_outcome(
        sport="football",
        athlete_label="player #7 in red",
        final_reels=[p1, p2],
        events_by_reel={p1: [event(1)], p2: [event(2)]},
        flagged_paths=set(),
        specs_getter=lambda path: spec_map[path],
    )
    if row["primary_publishable_reel"] is not None:
        raise SystemExit("rendered output became publishable before REVIEW upload confirmation")
    pre_upload = json.loads(manifest.read_text(encoding="utf-8"))
    if not any("was not uploaded to REVIEW" in error for error in checker.validate_manifest(pre_upload)):
        raise SystemExit("unuploaded rendered output did not fail the business gate")

    if not policy.mark_upload_result(p1, "DRAFT_player_7_part_1.mp4"):
        raise SystemExit("Part 1 upload could not be attached to the manifest")
    if not policy.mark_upload_result(p2, "DRAFT_player_7_part_2.mp4"):
        raise SystemExit("Part 2 upload could not be attached to the manifest")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    row = payload["athletes"][0]
    if row["primary_publishable_reel"] != "DRAFT_player_7_part_1.mp4":
        raise SystemExit("uploaded Part 1 was not selected as the primary publishable reel")
    if row["supplemental_publishable_reels"] != ["DRAFT_player_7_part_2.mp4"]:
        raise SystemExit("uploaded supplemental publishable parts are not ordered")
    if row["athlete_ids"] != ["athlete_7"]:
        raise SystemExit("canonical athlete identity was not preserved in the manifest")
    if any(part.get("has_audio") is not False for part in row["parts"]):
        raise SystemExit("publishable manifest did not preserve the required silent state")

    coverage = coverage_payload()
    errors = checker.validate_manifest(payload, coverage)
    if errors:
        raise SystemExit(f"valid silent publishable athlete manifest failed: {errors}")

    unmatched_coverage = coverage_payload(athlete_id="athlete_missing", description="player #99 in green")
    errors = checker.validate_manifest(payload, unmatched_coverage)
    if not any("absent from the publishable manifest" in error for error in errors):
        raise SystemExit("upstream selected athlete missing from the manifest was not detected")

    unresolved_coverage = coverage_payload()
    unresolved_coverage["athletes"][0]["coverage_requirement_met"] = False
    unresolved_coverage["summary"]["coverage_gap_cluster_count"] = 1
    unresolved_coverage["summary"]["athlete_accountability_rate"] = 0.0
    errors = checker.validate_manifest(payload, unresolved_coverage)
    if not any("unresolved coverage gap" in error for error in errors):
        raise SystemExit("unresolved athlete coverage was not blocked")

    missing_output = copy.deepcopy(payload)
    missing_output["athletes"][0]["primary_publishable_reel"] = None
    missing_output["athletes"][0]["supplemental_publishable_reels"] = []
    missing_output["summary"]["publishable_athlete_count"] = 0
    missing_output["summary"]["primary_publishable_reel_count"] = 0
    missing_output["summary"]["supplemental_publishable_reel_count"] = 0
    missing_output["summary"]["coverage_gap_count"] = 1
    errors = checker.validate_manifest(missing_output, coverage)
    if not any("no primary publishable reel" in error for error in errors):
        raise SystemExit("missing athlete output did not fail the business gate")

    audio = copy.deepcopy(payload)
    audio["athletes"][0]["parts"][0]["has_audio"] = True
    audio["athletes"][0]["parts"][0]["technical_issues"] = ["unexpected_audio"]
    audio["athletes"][0]["parts"][0]["publishable"] = False
    errors = checker.validate_manifest(audio, coverage)
    if not any("contains unexpected audio" in error for error in errors):
        raise SystemExit("audio-bearing primary output did not fail the silent business gate")

    unknown_audio = copy.deepcopy(payload)
    unknown_audio["athletes"][0]["parts"][0]["has_audio"] = None
    errors = checker.validate_manifest(unknown_audio, coverage)
    if not any("does not prove a silent audio state" in error for error in errors):
        raise SystemExit("unknown audio state did not fail closed")

    qa_failed = copy.deepcopy(payload)
    qa_failed["athletes"][0]["parts"][0]["qa_passed"] = False
    qa_failed["athletes"][0]["parts"][0]["technical_issues"] = ["final_qa_failed"]
    qa_failed["athletes"][0]["parts"][0]["publishable"] = False
    errors = checker.validate_manifest(qa_failed, coverage)
    if not any("did not pass final QA" in error for error in errors):
        raise SystemExit("QA-failed output was incorrectly accepted as publishable")

    duplicate = copy.deepcopy(payload)
    second = copy.deepcopy(duplicate["athletes"][0])
    second["athlete_key"] = "athlete_second"
    second["athlete_label"] = "player #9 in blue"
    duplicate["athletes"].append(second)
    duplicate["summary"]["eligible_athlete_count"] = 2
    duplicate["summary"]["publishable_athlete_count"] = 2
    duplicate["summary"]["primary_publishable_reel_count"] = 2
    duplicate["summary"]["supplemental_publishable_reel_count"] = 2
    errors = checker.validate_manifest(duplicate)
    if not any("canonical athlete_id" in error for error in errors):
        raise SystemExit("duplicate canonical athlete ownership did not fail the business gate")
    if not any("duplicated across athletes/parts" in error for error in errors):
        raise SystemExit("duplicate output ownership did not fail the business gate")

    policy.reset_manifest()
    empty = json.loads(manifest.read_text(encoding="utf-8"))
    empty_coverage = {
        "summary": {"coverage_gap_cluster_count": 0, "athlete_accountability_rate": 1.0},
        "athletes": [],
    }
    if checker.validate_manifest(empty, empty_coverage):
        raise SystemExit("empty no-input manifest should remain a valid zero-athlete result")


def assert_semantic_and_qa_validation(policy: Any) -> None:
    valid = {
        "activity": "football",
        "persons": [
            {
                "id": "person_A",
                "description": "player #7 in red",
                "events": [event(1)],
            }
        ],
    }
    parsed = policy.validate_session_semantics(valid)
    if parsed["persons"][0]["id"] != "person_A":
        raise SystemExit("valid session semantics were not preserved")

    duplicate_person = copy.deepcopy(valid)
    duplicate_person["persons"].append(copy.deepcopy(valid["persons"][0]))
    try:
        policy.validate_session_semantics(duplicate_person)
    except ValueError as exc:
        if "duplicate person id" not in str(exc):
            raise
    else:
        raise SystemExit("duplicate model person IDs were not rejected")

    invalid_window = copy.deepcopy(valid)
    invalid_window["persons"][0]["events"][0]["end"] = invalid_window["persons"][0]["events"][0]["start"]
    try:
        policy.validate_session_semantics(invalid_window)
    except ValueError as exc:
        if "invalid time window" not in str(exc):
            raise
    else:
        raise SystemExit("invalid model event window was not rejected")

    unavailable = policy.require_real_qa_result({
        "verdict": "PASS",
        "technical": {"pass": True},
        "defects": [],
        "engagement_score": 100,
        "overall": "QA skipped",
    })
    if unavailable.get("verdict") != "FAIL":
        raise SystemExit("unavailable final QA did not fail closed")
    if not any(defect.get("type") == "QA_UNAVAILABLE" for defect in unavailable.get("defects", [])):
        raise SystemExit("QA outage did not produce explicit blocking evidence")


def assert_source_contract(policy: Any, silent: Any) -> None:
    policy_source = POLICY_PATH.read_text(encoding="utf-8")
    silent_source = SILENT_POLICY_PATH.read_text(encoding="utf-8")
    checker_source = CHECKER_PATH.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    audit = (ROOT / "docs/audit/personal-publishable-reel-completion-plan-20260717.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    diagnostics = (ROOT / "scripts/run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")

    for text in (policy_source, silent_source, checker_source, bootstrap, run_tracked):
        ast.parse(text)

    required_policy = [
        "EVERY DISTINCT ATHLETE",
        "ONE usable action is enough",
        "one_primary_publishable_reel_per_eligible_athlete_v1",
        "record_athlete_outcome",
        "mark_upload_result",
        "validate_session_semantics",
        "require_real_qa_result",
        "all_final_failures_block",
        "uploaded_to_review",
    ]
    missing = [token for token in required_policy if token not in policy_source]
    if missing:
        raise SystemExit(f"publishable policy is missing product-contract tokens: {missing}")

    required_silent = [
        "video-only, no-audio product contract",
        "silent_social_ready_issues",
        "canonicalize_silent_variants",
        "unexpected_audio",
        "audio_state_unknown",
        "editor._pick_music = no_music_picker",
        "kwargs[\"music_path\"] = None",
    ]
    missing = [token for token in required_silent if token not in silent_source]
    if missing:
        raise SystemExit(f"silent output policy is incomplete: {missing}")

    required_readme = [
        "Product vision — source of truth",
        "every distinct athlete with at least one complete, visible, usable action",
        "One canonical silent output per part",
        "QA failure is not publishable",
        "centered on one target athlete",
    ]
    missing = [token for token in required_readme if token not in readme]
    if missing:
        raise SystemExit(f"README is missing the revised business vision: {missing}")

    official_refs = [
        "https://ai.google.dev/gemini-api/docs/video-understanding",
        "https://ai.google.dev/gemini-api/docs/structured-output",
        "https://cloud.google.com/video-intelligence/docs/feature-person-detection",
        "https://cloud.google.com/video-intelligence/docs/feature-object-tracking",
        "https://developers.openai.com/api/reference/resources/evals",
        "https://developers.openai.com/api/reference/resources/graders",
        "https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices",
        "https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool",
    ]
    missing = [url for url in official_refs if url not in audit]
    if missing:
        raise SystemExit(f"audit is missing official documentation references: {missing}")

    if "pipeline.silent_output_policy" not in bootstrap or "_install_silent_output_policy_runtime" not in run_tracked:
        raise SystemExit("silent output policy is not installed by all production entrypoints")
    if "check_publishable_reel_manifest.py" not in diagnostics:
        raise SystemExit("production diagnostics do not enforce the publishable manifest")
    if '"$ATHLETE_COVERAGE_FILE"' not in diagnostics:
        raise SystemExit("production business gate is not reconciled with athlete coverage evidence")
    if 'exit "$BUSINESS_GATE_STATUS"' not in diagnostics:
        raise SystemExit("business gate result is not the final successful-process exit code")

    issues = silent.silent_social_ready_issues(specs(audio=True, duration=91, width=1920, height=1080))
    expected = {
        "unexpected_audio",
        "duration_over_90_seconds",
        "aspect_not_9_16",
        "resolution_below_publishable_floor",
    }
    if not expected.issubset(set(issues)):
        raise SystemExit(f"silent technical publishability validation is incomplete: {issues}")
    if silent.silent_social_ready_issues(specs(audio=False)):
        raise SystemExit("valid silent vertical output was incorrectly rejected")


def main() -> int:
    policy = load_module("publishable_reel_policy_contract", POLICY_PATH)
    silent = load_module("silent_output_policy_contract", SILENT_POLICY_PATH)
    checker = load_module("publishable_reel_checker_contract", CHECKER_PATH)
    with tempfile.TemporaryDirectory(prefix="sportreel-business-contract-") as directory:
        tmp = Path(directory)
        assert_canonical_variant_selection(silent, tmp)
        assert_manifest_and_gate(policy, checker, silent, tmp)
    assert_semantic_and_qa_validation(policy)
    assert_source_contract(policy, silent)
    print("Silent publishable reel business contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
