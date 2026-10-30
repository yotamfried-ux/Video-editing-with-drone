#!/usr/bin/env python3
"""CLI and compatibility exports for the strict publishable-reel contract."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.publishable_manifest_contract import (
        GATE_MODES,
        SCHEMA_VERSION,
        evaluate_gate,
        validate_athlete_coverage,
        validate_manifest,
    )
except ModuleNotFoundError:
    from publishable_manifest_contract import (
        GATE_MODES,
        SCHEMA_VERSION,
        evaluate_gate,
        validate_athlete_coverage,
        validate_manifest,
    )


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"{label} missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must be a JSON object")
    return payload


def _write_result(
    path: Path,
    errors: list[str],
    *,
    manifest_path: Path,
    coverage_path: Path | None,
    evaluation: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "sportreel.publishable_reel_gate_result.v1",
        "passed": not errors,
        "manifest_path": str(manifest_path),
        "athlete_coverage_path": str(coverage_path) if coverage_path else None,
        "errors": errors,
    }
    if evaluation is not None:
        # Additive fields; consumers that only read passed/errors are unaffected.
        for key in (
            "mode",
            "outcome",
            "qa_gaps",
            "blocking_errors",
            "eligible_athlete_count",
            "publishable_athlete_count",
            "published_part_count",
        ):
            payload[key] = evaluation[key]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if len(sys.argv) not in {2, 3, 4}:
        print(
            "usage: check_publishable_reel_manifest.py MANIFEST_JSON "
            "[RESULT_JSON] [ATHLETE_COVERAGE_JSON]",
            file=sys.stderr,
        )
        return 2
    manifest_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
    coverage_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None

    try:
        payload = _load(manifest_path, "publishable manifest")
        coverage = _load(coverage_path, "athlete coverage report") if coverage_path else None
        # strict (default): any finding fails. partial: reels withheld for failing QA are reported
        # but do not fail the run while at least one athlete has a publishable reel.
        mode = os.getenv("PUBLISHABLE_GATE_MODE", "strict").strip().lower() or "strict"
        if mode not in GATE_MODES:
            raise SystemExit(f"PUBLISHABLE_GATE_MODE must be one of {GATE_MODES}, got {mode!r}")
        evaluation = evaluate_gate(payload, coverage, mode=mode)
        errors = evaluation["errors"]
    except SystemExit as exc:
        errors = [str(exc)]
        if result_path:
            _write_result(
                result_path,
                errors,
                manifest_path=manifest_path,
                coverage_path=coverage_path,
            )
        print("publishable reel business gate failed:", file=sys.stderr)
        print(f"- {errors[0]}", file=sys.stderr)
        return 1

    if result_path:
        _write_result(
            result_path,
            errors,
            manifest_path=manifest_path,
            coverage_path=coverage_path,
            evaluation=evaluation,
        )
    if errors:
        print("publishable reel business gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    summary = payload.get("summary") or {}
    print(
        "publishable reel business gate passed "
        f"athletes={summary.get('eligible_athlete_count', 0)} "
        f"primary={summary.get('primary_publishable_reel_count', 0)} "
        f"supplemental={summary.get('supplemental_publishable_reel_count', 0)}"
    )
    if evaluation["outcome"] == "partial":
        print(
            "publishable reel business gate PARTIAL: "
            f"{evaluation['publishable_athlete_count']}/{evaluation['eligible_athlete_count']} athletes "
            f"published, {len(evaluation['qa_gaps'])} QA finding(s) on withheld reels"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
