#!/usr/bin/env python3
"""Fail a production run that violates the per-athlete publishable-reel contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sportreel.publishable_reel_manifest.v1"


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


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _id_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _coverage_matches(
    manifest_rows: list[dict[str, Any]],
    coverage_row: dict[str, Any],
) -> list[dict[str, Any]]:
    """Match only with canonical athlete IDs; text labels are never identity proof."""
    coverage_ids = _id_set(coverage_row.get("athlete_ids"))
    if not coverage_ids:
        return []
    matches: list[dict[str, Any]] = []
    for row in manifest_rows:
        manifest_ids = _id_set(row.get("athlete_ids"))
        if coverage_ids.intersection(manifest_ids):
            matches.append(row)
    return matches


def validate_athlete_coverage(
    manifest_rows: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> list[str]:
    """Cross-check upstream athlete candidates against final canonical outcomes."""
    errors: list[str] = []
    rows = coverage.get("athletes")
    if not isinstance(rows, list):
        return ["athlete coverage report athletes must be an array"]

    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"coverage.athletes[{index}] must be an object")
            continue
        cluster = str(raw.get("athlete_cluster_id") or f"coverage.athletes[{index}]")
        candidate_count = _as_int(raw.get("candidate_action_count"))
        selected_count = _as_int(raw.get("selected_action_count"))
        explicit = raw.get("no_output_reason_explicit") is True
        covered = raw.get("coverage_requirement_met") is True
        coverage_ids = _id_set(raw.get("athlete_ids"))

        if candidate_count > 0 and not covered:
            errors.append(f"{cluster}: candidate athlete has an unresolved coverage gap")
        if selected_count > 0:
            if not coverage_ids:
                errors.append(f"{cluster}: selected athlete lacks canonical athlete_id lineage")
                continue
            matches = _coverage_matches(manifest_rows, raw)
            if not matches:
                errors.append(f"{cluster}: selected athlete is absent from the publishable manifest")
            elif len(matches) > 1:
                errors.append(f"{cluster}: canonical athlete maps to multiple publishable manifest rows")
            elif not matches[0].get("primary_publishable_reel"):
                errors.append(f"{cluster}: selected athlete has no primary publishable reel")
        elif candidate_count > 0 and not explicit:
            errors.append(f"{cluster}: no output exists without an explicit rejection reason")

    summary = coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {}
    if _as_int(summary.get("coverage_gap_cluster_count")) > 0:
        errors.append(
            "athlete coverage report contains unresolved cluster gaps: "
            f"{summary.get('coverage_gap_cluster_count')}"
        )
    try:
        accountability = float(summary.get("athlete_accountability_rate"))
    except (TypeError, ValueError):
        accountability = 1.0 if not rows else 0.0
    if accountability < 1.0:
        errors.append(f"athlete accountability rate must be 1.0, got {accountability}")
    try:
        lineage_rate = float(summary.get("selected_identity_lineage_completeness_rate"))
    except (TypeError, ValueError):
        lineage_rate = 1.0 if not any(
            isinstance(row, dict) and _as_int(row.get("selected_action_count")) > 0
            for row in rows
        ) else 0.0
    if lineage_rate < 1.0:
        errors.append(f"selected identity lineage completeness must be 1.0, got {lineage_rate}")
    return errors


def validate_manifest(
    payload: dict[str, Any],
    coverage: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    athletes = payload.get("athletes")
    if not isinstance(athletes, list):
        return [*errors, "athletes must be an array"]

    manifest_rows = [row for row in athletes if isinstance(row, dict)]
    athlete_keys: set[str] = set()
    athlete_id_owners: dict[str, str] = {}
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

        athlete_ids = _id_set(raw.get("athlete_ids"))
        if raw.get("athlete_ids") is not None and not isinstance(raw.get("athlete_ids"), list):
            errors.append(f"{label}: athlete_ids must be an array")
        for athlete_id in athlete_ids:
            owner = athlete_id_owners.get(athlete_id)
            if owner and owner != key:
                errors.append(
                    f"{label}: canonical athlete_id {athlete_id} already belongs to another manifest row"
                )
            athlete_id_owners[athlete_id] = key

        if raw.get("eligible") is not True:
            errors.append(f"{label}: manifest rows must represent eligible athletes")

        primary = raw.get("primary_publishable_reel")
        hard_reject = raw.get("explicit_hard_reject_reason")
        if not primary and not hard_reject:
            errors.append(f"{label}: eligible athlete has no primary publishable reel")
        if primary and not athlete_ids:
            errors.append(f"{label}: publishable athlete lacks canonical athlete_id lineage")
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
                errors.append(f"{label}: part {part_pos} has no uploaded REVIEW draft name")
            elif file_name in output_names:
                errors.append(f"{label}: output {file_name} is duplicated across athletes/parts")
            if file_name:
                output_names.add(file_name)

            if part.get("part_index") != part_pos:
                errors.append(f"{label}: expected ordered part_index {part_pos}")
            if part.get("uploaded_to_review") is not True:
                errors.append(f"{label}: part {part_pos} was not uploaded to REVIEW")
            if part.get("upload_error"):
                errors.append(f"{label}: part {part_pos} upload failed: {part.get('upload_error')}")
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
            errors.append(f"{label}: primary reel must be uploaded publishable Part 1")
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
    for name, value in expected.items():
        if summary.get(name) != value:
            errors.append(f"summary.{name} must be {value}, got {summary.get(name)}")

    if coverage is not None:
        errors.extend(validate_athlete_coverage(manifest_rows, coverage))
    return errors


def _write_result(
    path: Path,
    errors: list[str],
    *,
    manifest_path: Path,
    coverage_path: Path | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "sportreel.publishable_reel_gate_result.v1",
        "passed": not errors,
        "manifest_path": str(manifest_path),
        "athlete_coverage_path": str(coverage_path) if coverage_path else None,
        "errors": errors,
    }
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
    payload = _load(manifest_path, "publishable manifest")
    coverage = _load(coverage_path, "athlete coverage report") if coverage_path else None
    errors = validate_manifest(payload, coverage)
    if result_path:
        _write_result(
            result_path,
            errors,
            manifest_path=manifest_path,
            coverage_path=coverage_path,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
