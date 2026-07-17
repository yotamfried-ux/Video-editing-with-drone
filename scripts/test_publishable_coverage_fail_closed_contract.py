#!/usr/bin/env python3
"""Regression: only a truly empty manifest may use the no-input coverage bypass."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_PATH = ROOT / "scripts/check_publishable_manifest_empty.py"
DIAGNOSTICS_PATH = ROOT / "scripts/run_pipeline_with_diagnostics.sh"


def load_classifier():
    spec = importlib.util.spec_from_file_location("publishable_manifest_empty", CLASSIFIER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load publishable manifest empty classifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    classifier = load_classifier()
    with tempfile.TemporaryDirectory(prefix="sportreel-coverage-fail-closed-") as directory:
        tmp = Path(directory)
        manifest = tmp / "manifest.json"

        write(
            manifest,
            {
                "athletes": [],
                "summary": {"eligible_athlete_count": 0},
            },
        )
        if not classifier.is_empty_manifest(manifest):
            raise SystemExit("valid zero-athlete manifest was not recognized as no-input")

        write(
            manifest,
            {
                "athletes": [
                    {
                        "athlete_key": "athlete_A",
                        "eligible": True,
                        "primary_publishable_reel": "DRAFT_A.mp4",
                    }
                ],
                "summary": {"eligible_athlete_count": 1},
            },
        )
        if classifier.is_empty_manifest(manifest):
            raise SystemExit("nonempty publishable manifest could bypass missing coverage")

        write(
            manifest,
            {
                "athletes": [],
                "summary": {"eligible_athlete_count": 1},
            },
        )
        if classifier.is_empty_manifest(manifest):
            raise SystemExit("inconsistent nonzero summary could bypass missing coverage")

        manifest.write_text("not-json", encoding="utf-8")
        if classifier.is_empty_manifest(manifest):
            raise SystemExit("invalid manifest could bypass missing coverage")

    diagnostics = DIAGNOSTICS_PATH.read_text(encoding="utf-8")
    required = [
        'python scripts/check_publishable_manifest_empty.py "$PUBLISHABLE_MANIFEST_FILE"',
        'write_missing_gate_result "athlete coverage report missing for a nonempty or evidenced run"',
        '[ ! -f "$CANDIDATE_LEDGER_FILE" ]',
        '[ ! -f "$SELECTION_FILTER_EVENTS_FILE" ]',
        '[ ! -f "$DRAFT_TRACE_FILE" ]',
    ]
    missing = [token for token in required if token not in diagnostics]
    if missing:
        raise SystemExit(f"production no-input branch is missing fail-closed checks: {missing}")

    print("Publishable coverage fail-closed contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
