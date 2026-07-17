#!/usr/bin/env python3
"""Regression: concurrent REVIEW uploads must not overwrite silent manifest Parts."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
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


def specs(duration: float) -> dict[str, Any]:
    return {
        "has_audio": False,
        "duration": duration,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def event(index: int) -> dict[str, Any]:
    return {
        "athlete_id": "athlete_parallel",
        "type": "wave_catch",
        "sport": "surfing",
        "start": float(index * 20),
        "end": float(index * 20 + 12),
        "score": 8,
        "_src": "parallel-session.mp4",
    }


def attach_final_qa_pass(manifest: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for part in payload["athletes"][0]["parts"]:
        part["qa_evidence_recorded"] = True
        part["qa_verdict"] = "PASS"
        part["qa_passed"] = True
        part["technical_issues"] = []
        part["render_ready"] = True
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    policy = load_module("publishable_reel_policy_concurrency", POLICY_PATH)
    silent = load_module("silent_output_policy_concurrency", SILENT_POLICY_PATH)
    checker = load_module("publishable_reel_checker_concurrency", CHECKER_PATH)
    policy.social_ready_issues = silent.silent_social_ready_issues

    with tempfile.TemporaryDirectory(prefix="sportreel-manifest-concurrency-") as directory:
        tmp = Path(directory)
        manifest = tmp / "publishable_reel_manifest.json"
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()

        part1 = str(tmp / "parallel_p1.mp4")
        part2 = str(tmp / "parallel_p2.mp4")
        spec_map = {part1: specs(70.0), part2: specs(32.0)}
        policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="surfer on orange board",
            final_reels=[part1, part2],
            events_by_reel={part1: [event(1)], part2: [event(2)]},
            flagged_paths=set(),
            specs_getter=lambda path: spec_map[path],
        )
        attach_final_qa_pass(manifest)

        persisted: list[dict[str, Any]] = []
        policy._persist_draft_publishability = lambda record: persisted.append(dict(record))
        uploads = [
            (part1, "DRAFT_orange_board_part_1.mp4", "review/DRAFT_orange_board_part_1.mp4"),
            (part2, "DRAFT_orange_board_part_2.mp4", "review/DRAFT_orange_board_part_2.mp4"),
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda args: policy.mark_upload_result(
                    args[0],
                    args[1],
                    storage_object_id=args[2],
                ),
                uploads,
            ))
        if results != [True, True] or len(persisted) != 2:
            raise SystemExit(f"concurrent uploads were not both authoritatively attached: {results}, {persisted}")

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        athlete = payload["athletes"][0]
        if athlete["primary_publishable_reel"] != "DRAFT_orange_board_part_1.mp4":
            raise SystemExit("parallel upload lost or reordered the primary Part")
        if athlete["supplemental_publishable_reels"] != ["DRAFT_orange_board_part_2.mp4"]:
            raise SystemExit("parallel upload lost the supplemental Part")
        if payload["summary"]["primary_publishable_reel_count"] != 1:
            raise SystemExit("parallel updates corrupted the manifest summary")
        if any(part.get("has_audio") is not False for part in athlete["parts"]):
            raise SystemExit("parallel manifest did not preserve silent output state")

        coverage = {
            "summary": {
                "coverage_gap_cluster_count": 0,
                "athlete_accountability_rate": 1.0,
                "selected_identity_lineage_completeness_rate": 1.0,
            },
            "athletes": [
                {
                    "athlete_cluster_id": "parallel-session.mp4::person_A",
                    "athlete_ids": ["athlete_parallel"],
                    "candidate_action_count": 2,
                    "selected_action_count": 2,
                    "no_output_reason_explicit": False,
                    "coverage_requirement_met": True,
                }
            ],
        }
        errors = checker.validate_manifest(payload, coverage)
        if errors:
            raise SystemExit(f"thread-safe silent manifest failed the strict business gate: {errors}")

    source = POLICY_PATH.read_text(encoding="utf-8")
    required = ["threading.RLock()", "with _MANIFEST_LOCK:"]
    missing = [token for token in required if token not in source]
    if missing:
        raise SystemExit(f"manifest concurrency protection missing: {missing}")

    print("Silent publishable reel manifest concurrency checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
