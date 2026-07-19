#!/usr/bin/env python3
"""Regression: labels alone cannot prove publishable athlete identity."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("publishable_identity_checker", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load publishable manifest checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(athlete_ids: list[str]) -> dict:
    return {
        "schema_version": "sportreel.publishable_reel_manifest.v1",
        "business_contract": "one_primary_publishable_reel_per_eligible_athlete_v1",
        "athletes": [
            {
                "athlete_key": "athlete_manifest_key",
                "athlete_ids": athlete_ids,
                "athlete_label": "surfer in black wetsuit",
                "eligible": True,
                "parts": [
                    {
                        "part_index": 1,
                        "file_name": "DRAFT_black_wetsuit.mp4",
                        "storage_object_id": "review/DRAFT_black_wetsuit.mp4",
                        "authoritative_publishability_required": True,
                        "authoritative_publishability_persisted": True,
                        "authoritative_manifest_revision": "manifest-revision",
                        "uploaded_to_review": True,
                        "upload_error": None,
                        "publishable": True,
                        "qa_evidence_recorded": True,
                        "qa_verdict": "PASS",
                        "qa_passed": True,
                        "has_audio": False,
                        "technical_issues": [],
                        "duration": 42.0,
                        "aspect": 1080 / 1920,
                        "height": 1920,
                    }
                ],
                "primary_publishable_reel": "DRAFT_black_wetsuit.mp4",
                "supplemental_publishable_reels": [],
            }
        ],
        "summary": {
            "eligible_athlete_count": 1,
            "publishable_athlete_count": 1,
            "primary_publishable_reel_count": 1,
            "supplemental_publishable_reel_count": 0,
            "coverage_gap_count": 0,
        },
    }


def coverage(athlete_ids: list[str], lineage_rate: float | None = None) -> dict:
    summary = {
        "coverage_gap_cluster_count": 0,
        "athlete_accountability_rate": 1.0,
    }
    if lineage_rate is not None:
        summary["selected_identity_lineage_completeness_rate"] = lineage_rate
    return {
        "summary": summary,
        "athletes": [
            {
                "athlete_cluster_id": "source.mp4::person_A",
                "athlete_ids": athlete_ids,
                "candidate_action_count": 1,
                "selected_action_count": 1,
                "no_output_reason_explicit": False,
                "coverage_requirement_met": True,
            }
        ],
    }


def main() -> int:
    checker = load_checker()

    valid_errors = checker.validate_manifest(
        manifest(["athlete_canonical_A"]),
        coverage(["athlete_canonical_A"], 1.0),
    )
    if valid_errors:
        raise SystemExit(f"valid canonical lineage failed: {valid_errors}")

    manifest_missing = checker.validate_manifest(
        manifest([]),
        coverage(["athlete_canonical_A"], 1.0),
    )
    if not any("exactly one featured canonical athlete_id" in error for error in manifest_missing):
        raise SystemExit("publishable output without athlete_id was not blocked")

    manifest_mixed = checker.validate_manifest(
        manifest(["athlete_canonical_A", "athlete_canonical_B"]),
        coverage(["athlete_canonical_A"], 1.0),
    )
    if not any("exactly one featured canonical athlete_id" in error for error in manifest_mixed):
        raise SystemExit("one publishable row owning two athletes was not blocked")

    coverage_missing = checker.validate_manifest(
        manifest(["athlete_canonical_A"]),
        coverage([], 0.0),
    )
    if not any("exactly one canonical athlete_id" in error for error in coverage_missing):
        raise SystemExit("selected coverage row without athlete_id was not blocked")
    if not any("selected identity lineage completeness" in error for error in coverage_missing):
        raise SystemExit("lineage summary below 1.0 was not blocked")

    label_only_false_match = checker.validate_manifest(
        manifest(["athlete_canonical_A"]),
        coverage(["athlete_canonical_B"], 1.0),
    )
    if not any("absent from the publishable manifest" in error for error in label_only_false_match):
        raise SystemExit("same description with a different athlete_id falsely matched")

    inferred_complete = checker.validate_manifest(
        manifest(["athlete_canonical_A"]),
        coverage(["athlete_canonical_A"]),
    )
    if inferred_complete:
        raise SystemExit(f"legacy report with complete row IDs should infer full lineage: {inferred_complete}")

    print("Silent publishable identity lineage contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
