#!/usr/bin/env python3
"""Regression tests for the final centered-athlete silent business contract."""
from __future__ import annotations

import ast
import copy
import importlib.util
import math
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


def specs(*, audio: bool | None = False, duration: float = 30.0, width: int = 1080, height: int = 1920) -> dict[str, Any]:
    return {
        "has_audio": audio,
        "duration": duration,
        "width": width,
        "height": height,
        "aspect": width / height,
    }


def valid_manifest() -> dict[str, Any]:
    return {
        "schema_version": "sportreel.publishable_reel_manifest.v1",
        "business_contract": "one_primary_publishable_reel_per_eligible_athlete_v1",
        "athletes": [
            {
                "athlete_key": "athlete_manifest_7",
                "athlete_ids": ["athlete_7"],
                "athlete_label": "player #7 in red",
                "sport": "football",
                "eligible": True,
                "parts": [
                    {
                        "part_index": 1,
                        "file_name": "DRAFT_player_7_part_1.mp4",
                        "uploaded_to_review": True,
                        "upload_error": None,
                        "publishable": True,
                        "qa_evidence_recorded": True,
                        "qa_verdict": "PASS",
                        "qa_passed": True,
                        "has_audio": False,
                        "technical_issues": [],
                        "duration": 72.0,
                        "width": 1080,
                        "height": 1920,
                        "aspect": 1080 / 1920,
                    },
                    {
                        "part_index": 2,
                        "file_name": "DRAFT_player_7_part_2.mp4",
                        "uploaded_to_review": True,
                        "upload_error": None,
                        "publishable": True,
                        "qa_evidence_recorded": True,
                        "qa_verdict": "PASS",
                        "qa_passed": True,
                        "has_audio": False,
                        "technical_issues": [],
                        "duration": 28.0,
                        "width": 1080,
                        "height": 1920,
                        "aspect": 1080 / 1920,
                    },
                ],
                "primary_publishable_reel": "DRAFT_player_7_part_1.mp4",
                "supplemental_publishable_reels": ["DRAFT_player_7_part_2.mp4"],
            }
        ],
        "summary": {
            "eligible_athlete_count": 1,
            "publishable_athlete_count": 1,
            "primary_publishable_reel_count": 1,
            "supplemental_publishable_reel_count": 1,
            "coverage_gap_count": 0,
        },
    }


def valid_coverage() -> dict[str, Any]:
    return {
        "summary": {
            "coverage_gap_cluster_count": 0,
            "athlete_accountability_rate": 1.0,
            "selected_identity_lineage_completeness_rate": 1.0,
        },
        "athletes": [
            {
                "athlete_cluster_id": "session.mp4::person_A",
                "athlete_ids": ["athlete_7"],
                "candidate_action_count": 2,
                "selected_action_count": 2,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            }
        ],
    }


def require_error(errors: list[str], text: str) -> None:
    if not any(text in error for error in errors):
        raise SystemExit(f"expected error containing {text!r}, got {errors}")


def assert_silent_variant_selection(silent: Any, tmp: Path) -> None:
    clean = tmp / "MULTI_player_p1.mp4"
    music = tmp / "MULTI_player_p1_music.mp4"
    clean.write_bytes(b"silent")
    music.write_bytes(b"audio")
    spec_map = {str(clean): specs(), str(music): specs(audio=True)}
    selected, events, failures = silent.canonicalize_silent_variants(
        [str(clean), str(music)],
        [(str(clean), [{"event_id": "goal-1"}]), (str(music), [{"event_id": "goal-1"}])],
        specs_getter=lambda path: spec_map[path],
    )
    if selected != [str(clean)] or failures:
        raise SystemExit(f"silent canonical selection failed: {selected}, {failures}")
    if music.exists() or clean.read_bytes() != b"silent":
        raise SystemExit("legacy audio variant was not removed cleanly")
    if events != [(str(clean), [{"event_id": "goal-1"}])]:
        raise SystemExit("silent canonicalization lost event lineage")


def assert_manifest_contract(checker: Any) -> None:
    payload = valid_manifest()
    coverage = valid_coverage()
    errors = checker.validate_manifest(payload, coverage)
    if errors:
        raise SystemExit(f"valid strict manifest failed: {errors}")

    missing_qa = copy.deepcopy(payload)
    missing_qa["athletes"][0]["parts"][0]["qa_evidence_recorded"] = False
    require_error(checker.validate_manifest(missing_qa, coverage), "lacks explicit final QA evidence")

    failed_qa = copy.deepcopy(payload)
    failed_qa["athletes"][0]["parts"][0]["qa_verdict"] = "FAIL"
    failed_qa["athletes"][0]["parts"][0]["qa_passed"] = False
    require_error(checker.validate_manifest(failed_qa, coverage), "final QA verdict is not PASS")

    audio = copy.deepcopy(payload)
    audio["athletes"][0]["parts"][0]["has_audio"] = True
    require_error(checker.validate_manifest(audio, coverage), "contains unexpected audio")

    unknown_audio = copy.deepcopy(payload)
    unknown_audio["athletes"][0]["parts"][0]["has_audio"] = None
    require_error(checker.validate_manifest(unknown_audio, coverage), "does not prove a silent audio state")

    mixed_row = copy.deepcopy(payload)
    mixed_row["athletes"][0]["athlete_ids"] = ["athlete_7", "athlete_9"]
    require_error(checker.validate_manifest(mixed_row, coverage), "exactly one featured canonical athlete_id")

    nonfinite_duration = copy.deepcopy(payload)
    nonfinite_duration["athletes"][0]["parts"][0]["duration"] = math.nan
    require_error(checker.validate_manifest(nonfinite_duration, coverage), "invalid finite duration")

    nonfinite_aspect = copy.deepcopy(payload)
    nonfinite_aspect["athletes"][0]["parts"][0]["aspect"] = math.inf
    require_error(checker.validate_manifest(nonfinite_aspect, coverage), "not finite 9:16 media")

    bad_summary = copy.deepcopy(payload)
    bad_summary["summary"] = []
    require_error(checker.validate_manifest(bad_summary, coverage), "summary must be an object")

    malformed_counts = copy.deepcopy(coverage)
    malformed_counts["athletes"][0]["candidate_action_count"] = "2"
    require_error(checker.validate_manifest(payload, malformed_counts), "must be a non-negative integer")

    impossible_counts = copy.deepcopy(coverage)
    impossible_counts["athletes"][0]["selected_action_count"] = 3
    require_error(checker.validate_manifest(payload, impossible_counts), "cannot exceed candidate_action_count")

    invalid_rate = copy.deepcopy(coverage)
    invalid_rate["summary"]["athlete_accountability_rate"] = math.nan
    require_error(checker.validate_manifest(payload, invalid_rate), "finite number equal to 1.0")

    duplicate_coverage = copy.deepcopy(coverage)
    duplicate_coverage["athletes"].append(copy.deepcopy(duplicate_coverage["athletes"][0]))
    duplicate_coverage["athletes"][1]["athlete_cluster_id"] = "session.mp4::person_B"
    require_error(checker.validate_manifest(payload, duplicate_coverage), "selected by multiple coverage rows")


def assert_source_contract(silent: Any) -> None:
    policy_source = POLICY_PATH.read_text(encoding="utf-8")
    silent_source = SILENT_POLICY_PATH.read_text(encoding="utf-8")
    checker_source = CHECKER_PATH.read_text(encoding="utf-8")
    strict_source = (ROOT / "scripts/publishable_manifest_contract.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    audit = (ROOT / "docs/audit/personal-publishable-reel-completion-plan-20260717.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")

    for text in (policy_source, silent_source, checker_source, strict_source, bootstrap, run_tracked):
        ast.parse(text)

    required = {
        "policy": (policy_source, ["EVERY DISTINCT ATHLETE", "ONE usable action is enough", "record_athlete_outcome", "mark_upload_result"]),
        "silent": (silent_source, ["video-only, no-audio product contract", "canonicalize_silent_variants", "unexpected_audio", "audio_state_unknown"]),
        "strict checker": (strict_source, ["qa_evidence_recorded", "exactly one featured canonical athlete_id", "math.isfinite", "selected by multiple coverage rows"]),
        "README": (readme, ["One featured athlete per reel, not one visible person", "One canonical silent output per part", "another surfer may enter or ride the same wave"]),
        "bootstrap": (bootstrap, ["pipeline.silent_output_policy"]),
        "production runner": (run_tracked, ["_install_silent_output_policy_runtime()"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} missing contract tokens: {missing}")

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
        raise SystemExit(f"audit missing official references: {missing}")

    issues = silent.silent_social_ready_issues(specs(audio=True, duration=91, width=1920, height=1080))
    expected = {"unexpected_audio", "duration_over_90_seconds", "aspect_not_9_16", "resolution_below_publishable_floor"}
    if not expected.issubset(set(issues)):
        raise SystemExit(f"silent technical contract is incomplete: {issues}")


def main() -> int:
    silent = load_module("silent_output_policy_contract", SILENT_POLICY_PATH)
    checker = load_module("publishable_reel_checker_contract", CHECKER_PATH)
    with tempfile.TemporaryDirectory(prefix="sportreel-business-contract-") as directory:
        assert_silent_variant_selection(silent, Path(directory))
    assert_manifest_contract(checker)
    assert_source_contract(silent)
    print("Strict centered-athlete silent business contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
