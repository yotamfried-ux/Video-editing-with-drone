#!/usr/bin/env python3
"""Fail a production run that violates the per-athlete publishable-reel contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sportreel.publishable_reel_manifest.v1"


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"publishable manifest missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"publishable manifest is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("publishable manifest must be a JSON object")
    return payload


def validate_manifest(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    athletes = payload.get("athletes")
    if not isinstance(athletes, list):
        return [*errors, "athletes must be an array"]

    athlete_keys: set[str] = set()
    output_names: set[str] = set()
    publishable_athletes = 0
    primary_count = 0
    supplemental_count = 0

    for index, raw in enumerate(athletes):
        if not isinstance(raw, dict):
            errors.append(f"athletes[{index}] must be an object")
            continue
        label = str(raw.get("athlete_label") or f"athletes[{index}]")
        key = str(raw.get("athlete_key") or "")
        if not key:
            errors.append(f"{label}: athlete_key is missing")
        elif key in athlete_keys:
            errors.append(f"{label}: duplicate athlete_key {key}")
        athlete_keys.add(key)

        if raw.get("eligible") is not True:
            errors.append(f"{label}: manifest rows must represent eligible athletes")

        primary = raw.get("primary_publishable_reel")
        hard_reject = raw.get("explicit_hard_reject_reason")
        if not primary and not hard_reject:
            errors.append(f"{label}: eligible athlete has no primary publishable reel")
        if primary:
            publishable_athletes += 1
            primary_count += 1

        supplemental = raw.get("supplemental_publishable_reels") or []
        if not isinstance(supplemental, list):
            errors.append(f"{label}: supplemental_publishable_reels must be an array")
            supplemental = []
        supplemental_count += len(supplemental)

        parts = raw.get("parts") or []
        if not isinstance(parts, list):
            errors.append(f"{label}: parts must be an array")
            continue
        if primary and not parts:
            errors.append(f"{label}: primary reel exists without part evidence")

        publishable_parts: list[dict[str, Any]] = []
        for part_pos, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                errors.append(f"{label}: part {part_pos} must be an object")
                continue
            file_name = str(part.get("file_name") or "")
            if not file_name:
                errors.append(f"{label}: part {part_pos} file_name is missing")
            elif file_name in output_names:
                errors.append(f"{label}: output {file_name} is duplicated across athletes/parts")
            output_names.add(file_name)

            if part.get("part_index") != part_pos:
                errors.append(f"{label}: expected ordered part_index {part_pos}")
            if not part.get("publishable"):
                errors.append(f"{label}: part {part_pos} is not publishable")
            else:
                publishable_parts.append(part)
            if part.get("qa_passed") is not True:
                errors.append(f"{label}: part {part_pos} did not pass final QA")
            if part.get("has_audio") is not True:
                errors.append(f"{label}: part {part_pos} has no audio")
            issues = part.get("technical_issues") or []
            if issues:
                errors.append(f"{label}: part {part_pos} technical issues: {issues}")
            try:
                duration = float(part.get("duration"))
            except (TypeError, ValueError):
                duration = 0.0
            if duration <= 0 or duration > 90.0:
                errors.append(f"{label}: part {part_pos} invalid duration {part.get('duration')}")
            try:
                aspect = float(part.get("aspect"))
            except (TypeError, ValueError):
                aspect = 0.0
            if aspect <= 0 or abs(aspect - 9 / 16) > 0.02:
                errors.append(f"{label}: part {part_pos} is not 9:16")
            try:
                height = int(part.get("height") or 0)
            except (TypeError, ValueError):
                height = 0
            if height < 1280:
                errors.append(f"{label}: part {part_pos} resolution is below 720x1280")

        publishable_names = [str(part.get("file_name")) for part in publishable_parts]
        if primary and (not publishable_names or primary != publishable_names[0]):
            errors.append(f"{label}: primary reel must be publishable Part 1")
        if supplemental != publishable_names[1:]:
            errors.append(f"{label}: supplemental reel list does not match ordered publishable parts")
        if primary and len(publishable_parts) != len(parts):
            errors.append(f"{label}: all generated parts must be publishable before athlete coverage passes")

    summary = payload.get("summary") or {}
    expected = {
        "eligible_athlete_count": len(athletes),
        "publishable_athlete_count": publishable_athletes,
        "primary_publishable_reel_count": primary_count,
        "supplemental_publishable_reel_count": supplemental_count,
        "coverage_gap_count": sum(
            1
            for row in athletes
            if isinstance(row, dict)
            and not row.get("primary_publishable_reel")
            and not row.get("explicit_hard_reject_reason")
        ),
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            errors.append(f"summary.{key} must be {value}, got {summary.get(key)}")
    return errors


def _write_result(path: Path, errors: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "sportreel.publishable_reel_gate_result.v1",
        "passed": not errors,
        "errors": errors,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("usage: check_publishable_reel_manifest.py MANIFEST_JSON [RESULT_JSON]", file=sys.stderr)
        return 2
    manifest_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2]) if len(sys.argv) == 3 else None
    payload = _load(manifest_path)
    errors = validate_manifest(payload)
    if result_path:
        _write_result(result_path, errors)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
