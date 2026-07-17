#!/usr/bin/env python3
"""Regression tests for one publishable social-ready reel per eligible athlete."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pipeline/publishable_reel_policy.py"
CHECKER_PATH = ROOT / "scripts/check_publishable_reel_manifest.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def specs(*, audio: bool = True, duration: float = 30.0, width: int = 1080, height: int = 1920) -> dict[str, Any]:
    return {
        "has_audio": audio,
        "duration": duration,
        "width": width,
        "height": height,
        "aspect": width / height,
    }


def event(index: int, source: str = "session.mp4") -> dict[str, Any]:
    return {
        "event_id": f"action-{index}",
        "type": "goal" if index == 1 else "save",
        "sport": "football",
        "start": float(index * 10),
        "end": float(index * 10 + 8),
        "score": 8,
        "_src": source,
    }


def assert_canonical_variant_selection(policy: Any, tmp: Path) -> None:
    clean = tmp / "MULTI_player_p1.mp4"
    music = tmp / "MULTI_player_p1_music.mp4"
    clean.write_bytes(b"silent-intermediate")
    music.write_bytes(b"audio-publishable")
    source_events = [(str(clean), [event(1)]), (str(music), [event(1)])]
    spec_map = {
        str(clean): specs(audio=False),
        str(music): specs(audio=True),
    }

    selected, selected_events, failures = policy.canonicalize_publishable_variants(
        [str(clean), str(music)],
        source_events,
        specs_getter=lambda path: spec_map[path],
    )
    if selected != [str(clean)]:
        raise SystemExit(f"music variant was not collapsed into the canonical path: {selected}")
    if failures:
        raise SystemExit(f"valid canonical selection produced failures: {failures}")
    if clean.read_bytes() != b"audio-publishable" or music.exists():
        raise SystemExit("canonical output did not contain the audio-capable render")
    if selected_events != [(str(clean), [event(1)])]:
        raise SystemExit("canonical output lost event lineage")

    silent = tmp / "MULTI_silent.mp4"
    silent.write_bytes(b"silent")
    selected, selected_events, failures = policy.canonicalize_publishable_variants(
        [str(silent)],
        [(str(silent), [event(2)])],
        specs_getter=lambda _path: specs(audio=False),
    )
    if selected or selected_events or failures != ["no_audio_variant:MULTI_silent.mp4"]:
        raise SystemExit("silent-only output was not blocked deterministically")
    if silent.exists():
        raise SystemExit("silent intermediate remained after publishable selection failed")

    part1 = tmp / "MULTI_multi_p1.mp4"
    part1_music = tmp / "MULTI_multi_p1_music.mp4"
    part2 = tmp / "MULTI_multi_p2.mp4"
    part2_music = tmp / "MULTI_multi_p2_music.mp4"
    for path, content in [
        (part1, b"clean1"),
        (part1_music, b"music1"),
        (part2, b"clean2"),
        (part2_music, b"music2"),
    ]:
        path.write_bytes(content)
    spec_map = {
        str(part1): specs(audio=False, duration=70),
        str(part1_music): specs(audio=True, duration=70),
        str(part2): specs(audio=False, duration=25),
        str(part2_music): specs(audio=True, duration=25),
    }
    selected, _, failures = policy.canonicalize_publishable_variants(
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
        raise SystemExit(f"multiple parts did not produce one canonical output per part: {selected}, {failures}")
    if part1.read_bytes() != b"music1" or part2.read_bytes() != b"music2":
        raise SystemExit("part canonicalization selected the wrong render variants")


def assert_manifest_and_gate(policy: Any, checker: Any, tmp: Path) -> None:
    manifest = tmp / "publishable_reel_manifest.json"
    os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
    policy.reset_manifest()

    p1 = str(tmp / "athlete_p1.mp4")
    p2 = str(tmp / "athlete_p2.mp4")
    spec_map = {
        p1: specs(audio=True, duration=72),
        p2: specs(audio=True, duration=28),
    }
    row = policy.record_athlete_outcome(
        sport="football",
        athlete_label="player #7 in red",
        final_reels=[p1, p2],
        events_by_reel={p1: [event(1)], p2: [event(2)]},
        flagged_paths=set(),
        specs_getter=lambda path: spec_map[path],
    )
    if row["primary_publishable_reel"] != "athlete_p1.mp4":
        raise SystemExit("Part 1 was not selected as the primary publishable reel")
    if row["supplemental_publishable_reels"] != ["athlete_p2.mp4"]:
        raise SystemExit("supplemental publishable parts are not ordered")

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    errors = checker.validate_manifest(payload)
    if errors:
        raise SystemExit(f"valid publishable athlete manifest failed: {errors}")

    missing_output = copy.deepcopy(payload)
    missing_output["athletes"][0]["primary_publishable_reel"] = None
    missing_output["athletes"][0]["supplemental_publishable_reels"] = []
    missing_output["summary"]["publishable_athlete_count"] = 0
    missing_output["summary"]["primary_publishable_reel_count"] = 0
    missing_output["summary"]["supplemental_publishable_reel_count"] = 0
    missing_output["summary"]["coverage_gap_count"] = 1
    errors = checker.validate_manifest(missing_output)
    if not any("no primary publishable reel" in error for error in errors):
        raise SystemExit("missing athlete output did not fail the business gate")

    silent = copy.deepcopy(payload)
    silent["athletes"][0]["parts"][0]["has_audio"] = False
    silent["athletes"][0]["parts"][0]["technical_issues"] = ["missing_audio"]
    silent["athletes"][0]["parts"][0]["publishable"] = False
    errors = checker.validate_manifest(silent)
    if not any("has no audio" in error for error in errors):
        raise SystemExit("silent primary output did not fail the business gate")

    qa_failed = copy.deepcopy(payload)
    qa_failed["athletes"][0]["parts"][0]["qa_passed"] = False
    qa_failed["athletes"][0]["parts"][0]["technical_issues"] = ["final_qa_failed"]
    qa_failed["athletes"][0]["parts"][0]["publishable"] = False
    errors = checker.validate_manifest(qa_failed)
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
    if not any("duplicated across athletes/parts" in error for error in errors):
        raise SystemExit("duplicate output ownership did not fail the business gate")

    policy.reset_manifest()
    empty = json.loads(manifest.read_text(encoding="utf-8"))
    if checker.validate_manifest(empty):
        raise SystemExit("empty no-input manifest should remain a valid zero-athlete result")


def assert_source_contract(policy: Any) -> None:
    policy_source = POLICY_PATH.read_text(encoding="utf-8")
    checker_source = CHECKER_PATH.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    audit = (ROOT / "docs/audit/personal-publishable-reel-completion-plan-20260717.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    diagnostics = (ROOT / "scripts/run_pipeline_with_diagnostics.sh").read_text(encoding="utf-8")

    for text in (policy_source, checker_source, bootstrap, run_tracked):
        ast.parse(text)

    required_policy = [
        "EVERY DISTINCT ATHLETE",
        "ONE usable action is enough",
        "one_primary_publishable_reel_per_eligible_athlete_v1",
        "canonicalize_publishable_variants",
        "record_athlete_outcome",
        "all_final_failures_block",
    ]
    missing = [token for token in required_policy if token not in policy_source]
    if missing:
        raise SystemExit(f"publishable policy is missing product-contract tokens: {missing}")

    required_readme = [
        "Product vision — source of truth",
        "every distinct athlete with at least one complete, visible, usable action",
        "One canonical publishable output per part",
        "QA failure is not publishable",
    ]
    missing = [token for token in required_readme if token not in readme]
    if missing:
        raise SystemExit(f"README is missing the business vision: {missing}")

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

    if "pipeline.publishable_reel_policy" not in bootstrap or "_install_publishable_reel_policy_runtime" not in run_tracked:
        raise SystemExit("publishable policy is not installed by all production entrypoints")
    if "check_publishable_reel_manifest.py" not in diagnostics:
        raise SystemExit("production diagnostics do not enforce the publishable manifest")
    if 'exit "$BUSINESS_GATE_STATUS"' not in diagnostics:
        raise SystemExit("business gate result is not the final successful-process exit code")

    issues = policy.social_ready_issues(specs(audio=False, duration=91, width=1920, height=1080))
    expected = {
        "missing_audio",
        "duration_over_90_seconds",
        "aspect_not_9_16",
        "resolution_below_publishable_floor",
    }
    if not expected.issubset(set(issues)):
        raise SystemExit(f"technical publishability validation is incomplete: {issues}")


def main() -> int:
    policy = load_module("publishable_reel_policy_contract", POLICY_PATH)
    checker = load_module("publishable_reel_checker_contract", CHECKER_PATH)
    with tempfile.TemporaryDirectory(prefix="sportreel-business-contract-") as directory:
        tmp = Path(directory)
        assert_canonical_variant_selection(policy, tmp)
        assert_manifest_and_gate(policy, checker, tmp)
    assert_source_contract(policy)
    print("Publishable reel business contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
