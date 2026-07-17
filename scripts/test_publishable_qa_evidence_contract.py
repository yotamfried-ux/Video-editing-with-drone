#!/usr/bin/env python3
"""Regression: no reel is publishable without a recorded final QA PASS."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pipeline/publishable_reel_policy.py"
EVIDENCE_PATH = ROOT / "pipeline/publishable_qa_evidence.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs() -> dict[str, Any]:
    return {
        "has_audio": True,
        "duration": 36.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def event() -> dict[str, Any]:
    return {
        "athlete_id": "athlete_qa_7",
        "type": "goal",
        "sport": "football",
        "start": 10.0,
        "end": 19.0,
        "score": 9,
        "_src": "match.mp4",
    }


def read_athlete(manifest: Path) -> dict[str, Any]:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return payload["athletes"][0]


def main() -> int:
    policy = load_module("publishable_qa_policy_test", POLICY_PATH)
    evidence = load_module("publishable_qa_evidence_test", EVIDENCE_PATH)

    with tempfile.TemporaryDirectory(prefix="sportreel-qa-evidence-") as directory:
        tmp = Path(directory)
        manifest = tmp / "publishable_reel_manifest.json"
        reel = str(tmp / "athlete_primary.mp4")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()

        policy.record_athlete_outcome(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
            events_by_reel={reel: [event()]},
            flagged_paths=set(),
            specs_getter=lambda _path: specs(),
        )

        # An empty flagged set is not positive evidence. Missing model grading
        # must fail closed before upload.
        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
        )
        if blocked != {reel}:
            raise SystemExit(f"missing QA evidence did not block the part: {blocked}")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_evidence_recorded") is not False:
            raise SystemExit("manifest did not explicitly record missing QA evidence")
        if part.get("qa_passed") is not False or part.get("render_ready") is not False:
            raise SystemExit("ungraded part remained render-ready")
        if "missing_final_qa_evidence" not in part.get("technical_issues", []):
            raise SystemExit("missing QA evidence reason was not persisted")

        evidence.record_qa_result(
            reel,
            {
                "verdict": "PASS",
                "engagement_score": 82,
                "overall": "Clear personal sports reel.",
                "defects": [],
            },
        )
        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
        )
        if blocked:
            raise SystemExit(f"recorded PASS remained blocked: {blocked}")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_evidence_recorded") is not True or part.get("qa_verdict") != "PASS":
            raise SystemExit("positive QA evidence was not stored in the manifest")
        if part.get("qa_passed") is not True or part.get("render_ready") is not True:
            raise SystemExit("recorded PASS did not restore render readiness")
        if part.get("qa_engagement_score") != 82:
            raise SystemExit("QA score was not retained as evidence")

        evidence.clear_recorded_qa()
        evidence.record_qa_result(
            reel,
            {
                "verdict": "FAIL",
                "engagement_score": 44,
                "overall": "Weak framing.",
                "defects": [{"type": "FRAMING", "severity": "minor"}],
            },
        )
        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
        )
        if blocked != {reel}:
            raise SystemExit("explicit QA FAIL did not block the part")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_verdict") != "FAIL" or part.get("qa_passed") is not False:
            raise SystemExit("QA FAIL evidence was not persisted")
        if "final_qa_failed" not in part.get("technical_issues", []):
            raise SystemExit("QA FAIL reason was not persisted")

    source = EVIDENCE_PATH.read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    required_source = [
        "qa_evidence_recorded",
        "missing_final_qa_evidence",
        "gate_with_required_evidence",
        "record_qa_result",
    ]
    missing = [token for token in required_source if token not in source]
    if missing:
        raise SystemExit(f"QA evidence runtime missing contract tokens: {missing}")
    if "pipeline.publishable_qa_evidence" not in bootstrap:
        raise SystemExit("shared bootstrap does not install explicit QA evidence")
    if "_install_publishable_qa_evidence_runtime()" not in run_tracked:
        raise SystemExit("production runner does not install explicit QA evidence")

    print("Publishable final QA evidence contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
