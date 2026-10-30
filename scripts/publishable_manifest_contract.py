"""Strict validation for SportReel's final publishable manifest.

The contract is deliberately independent from the renderer and model code. A
production result passes only when every selected athlete maps to one distinct
single-featured-athlete row, every uploaded Part has explicit final-QA evidence,
and every media field proves a finite, vertical, silent, <=90-second output.
"""
from __future__ import annotations

import math
from typing import Any

SCHEMA_VERSION = "sportreel.publishable_reel_manifest.v1"


class QaGap(str):
    """A finding that is only about a Part/athlete that is NOT being published.

    It is a plain ``str`` (strict validation and every existing consumer see no difference). The
    partial-publish evaluator uses the type to tell "this reel did not pass QA, so it is withheld"
    from an integrity failure that must still fail the run.
    """


def _gap(message: str, *, when: bool = True) -> str:
    return QaGap(message) if when else message


def _id_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value).strip()}


def _required_nonnegative_int(
    value: Any,
    *,
    field: str,
    errors: list[str],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"{field} must be a non-negative integer")
        return 0
    return value


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coverage_matches(
    manifest_rows: list[dict[str, Any]],
    coverage_ids: set[str],
) -> list[dict[str, Any]]:
    if len(coverage_ids) != 1:
        return []
    return [
        row
        for row in manifest_rows
        if _id_set(row.get("athlete_ids")) == coverage_ids
    ]


def _qa_findings(part: dict[str, Any]) -> str:
    """' (score 40; BAD_FIRST_CLIP, DEAD_TIME)' - why QA failed this Part, appended to the gate error."""
    bits: list[str] = []
    score = part.get("qa_engagement_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        bits.append(f"score {int(score)}")
    kinds = []
    for defect in part.get("qa_defects", []) or []:
        kind = str(defect.get("type") or defect.get("code") or "").upper() if isinstance(defect, dict) else ""
        if kind and kind != "QA_REVIEW_REQUIRED" and kind not in kinds:
            kinds.append(kind)
    if kinds:
        bits.append(", ".join(kinds[:5]))
    return f" ({'; '.join(bits)})" if bits else ""


def validate_athlete_coverage(
    manifest_rows: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    rows = coverage.get("athletes")
    if not isinstance(rows, list):
        return ["athlete coverage report athletes must be an array"]

    selected_rows: list[dict[str, Any]] = []
    selected_id_owners: dict[str, str] = {}
    for index, raw in enumerate(rows):
        prefix = f"coverage.athletes[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{prefix} must be an object")
            continue
        cluster = str(raw.get("athlete_cluster_id") or prefix)
        candidate_count = _required_nonnegative_int(
            raw.get("candidate_action_count"),
            field=f"{cluster}.candidate_action_count",
            errors=errors,
        )
        selected_count = _required_nonnegative_int(
            raw.get("selected_action_count"),
            field=f"{cluster}.selected_action_count",
            errors=errors,
        )
        if selected_count > candidate_count:
            errors.append(
                f"{cluster}: selected_action_count cannot exceed candidate_action_count"
            )
        explicit = raw.get("no_output_reason_explicit") is True
        covered = raw.get("coverage_requirement_met") is True
        coverage_ids = _id_set(raw.get("athlete_ids"))

        if candidate_count > 0 and not covered:
            errors.append(f"{cluster}: candidate athlete has an unresolved coverage gap")

        if selected_count > 0:
            selected_rows.append(raw)
            if len(coverage_ids) != 1:
                errors.append(
                    f"{cluster}: selected athlete must have exactly one canonical athlete_id"
                )
                continue
            athlete_id = next(iter(coverage_ids))
            previous = selected_id_owners.get(athlete_id)
            if previous and previous != cluster:
                errors.append(
                    f"{cluster}: canonical athlete_id {athlete_id} is selected by multiple coverage rows"
                )
            selected_id_owners[athlete_id] = cluster

            matches = _coverage_matches(manifest_rows, coverage_ids)
            if not matches:
                errors.append(f"{cluster}: selected athlete is absent from the publishable manifest")
            elif len(matches) > 1:
                errors.append(f"{cluster}: canonical athlete maps to multiple publishable manifest rows")
            elif not matches[0].get("primary_publishable_reel"):
                errors.append(_gap(
                    f"{cluster}: selected athlete has no primary publishable reel",
                    when=bool(matches[0].get("parts")),
                ))
        elif candidate_count > 0 and not explicit:
            errors.append(f"{cluster}: no output exists without an explicit rejection reason")

    summary = coverage.get("summary")
    if not isinstance(summary, dict):
        errors.append("athlete coverage report summary must be an object")
        summary = {}

    gap_count = _required_nonnegative_int(
        summary.get("coverage_gap_cluster_count"),
        field="coverage.summary.coverage_gap_cluster_count",
        errors=errors,
    )
    if gap_count > 0:
        errors.append(f"athlete coverage report contains unresolved cluster gaps: {gap_count}")

    accountability = _finite_float(summary.get("athlete_accountability_rate"))
    if accountability is None:
        errors.append("athlete accountability rate must be a finite number equal to 1.0")
    elif accountability != 1.0:
        errors.append(f"athlete accountability rate must be 1.0, got {accountability}")

    raw_lineage_rate = summary.get("selected_identity_lineage_completeness_rate")
    if raw_lineage_rate is None:
        lineage_rate = 1.0 if all(
            len(_id_set(row.get("athlete_ids"))) == 1 for row in selected_rows
        ) else 0.0
    else:
        lineage_rate = _finite_float(raw_lineage_rate)
        if lineage_rate is None:
            errors.append(
                "selected identity lineage completeness must be a finite number equal to 1.0"
            )
    if lineage_rate is not None and lineage_rate != 1.0:
        errors.append(
            f"selected identity lineage completeness must be 1.0, got {lineage_rate}"
        )
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

        raw_ids = raw.get("athlete_ids")
        if not isinstance(raw_ids, list):
            errors.append(f"{label}: athlete_ids must be an array")
        athlete_ids = _id_set(raw_ids)
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
            # With generated Parts, every one of them failed QA: withheld, not lost. With no Part
            # at all the athlete vanished somewhere in the pipeline, which stays a blocking error.
            errors.append(_gap(
                f"{label}: eligible athlete has no primary publishable reel",
                when=bool(raw.get("parts")),
            ))
        if primary and len(athlete_ids) != 1:
            errors.append(
                f"{label}: publishable row must contain exactly one featured canonical athlete_id"
            )
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
            errors.append(f"{label}: primary reel exists without Part evidence")

        publishable_parts: list[dict[str, Any]] = []
        for part_pos, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                errors.append(f"{label}: Part {part_pos} must be an object")
                continue
            file_name = str(part.get("file_name") or "")
            if not file_name:
                errors.append(f"{label}: Part {part_pos} has no uploaded REVIEW draft name")
            elif file_name in output_names:
                errors.append(f"{label}: output {file_name} is duplicated across athletes/Parts")
            if file_name:
                output_names.add(file_name)

            if part.get("part_index") != part_pos:
                errors.append(f"{label}: expected ordered part_index {part_pos}")
            if part.get("uploaded_to_review") is not True:
                errors.append(f"{label}: Part {part_pos} was not uploaded to REVIEW")
            if part.get("upload_error"):
                errors.append(f"{label}: Part {part_pos} upload failed: {part.get('upload_error')}")
            withheld = part.get("publishable") is not True
            if withheld:
                errors.append(_gap(f"{label}: Part {part_pos} is not publishable"))
            else:
                publishable_parts.append(part)

            if not str(part.get("storage_object_id") or "").strip():
                errors.append(f"{label}: Part {part_pos} lacks immutable REVIEW storage identity")
            if part.get("authoritative_publishability_required") is not True:
                errors.append(f"{label}: Part {part_pos} did not require server-side publishability authority")
            if part.get("authoritative_publishability_persisted") is not True:
                errors.append(f"{label}: Part {part_pos} publishability authority was not persisted")
            if not str(part.get("authoritative_manifest_revision") or "").strip():
                errors.append(f"{label}: Part {part_pos} lacks authoritative manifest revision")

            if part.get("qa_evidence_recorded") is not True:
                errors.append(f"{label}: Part {part_pos} lacks explicit final QA evidence")
            if str(part.get("qa_verdict") or "").upper() != "PASS":
                errors.append(_gap(
                    f"{label}: Part {part_pos} final QA verdict is not PASS{_qa_findings(part)}",
                    when=withheld,
                ))
            if part.get("qa_passed") is not True:
                errors.append(_gap(f"{label}: Part {part_pos} did not pass final QA", when=withheld))

            audio_state = part.get("has_audio")
            if audio_state is True:
                errors.append(_gap(f"{label}: Part {part_pos} contains unexpected audio", when=withheld))
            elif audio_state is not False:
                errors.append(_gap(
                    f"{label}: Part {part_pos} does not prove a silent audio state", when=withheld
                ))

            issues = part.get("technical_issues")
            if not isinstance(issues, list):
                errors.append(f"{label}: Part {part_pos} technical_issues must be an array")
                issues = []
            if issues:
                errors.append(_gap(f"{label}: Part {part_pos} technical issues: {issues}", when=withheld))

            duration = _finite_float(part.get("duration"))
            if duration is None or duration <= 0 or duration > 90.0:
                errors.append(_gap(
                    f"{label}: Part {part_pos} invalid finite duration {part.get('duration')}",
                    when=withheld,
                ))
            aspect = _finite_float(part.get("aspect"))
            if aspect is None or aspect <= 0 or abs(aspect - 9 / 16) > 0.02:
                errors.append(_gap(f"{label}: Part {part_pos} is not finite 9:16 media", when=withheld))
            height = part.get("height")
            if isinstance(height, bool) or not isinstance(height, int) or height < 1280:
                errors.append(_gap(f"{label}: Part {part_pos} resolution is below 720x1280", when=withheld))

        publishable_names = [str(part.get("file_name")) for part in publishable_parts]
        if primary and (not publishable_names or primary != publishable_names[0]):
            errors.append(f"{label}: primary reel must be uploaded publishable Part 1")
        if supplemental != publishable_names[1:]:
            errors.append(f"{label}: supplemental reel list does not match ordered publishable Parts")
        if primary and len(publishable_parts) != len(parts):
            errors.append(_gap(
                f"{label}: every generated Part must be publishable before athlete coverage passes"
            ))

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
        summary = {}
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


GATE_MODES = ("strict", "partial")


def evaluate_gate(
    payload: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    *,
    mode: str = "strict",
) -> dict[str, Any]:
    """Run the manifest contract and decide the run outcome.

    ``strict``: any finding fails the run (the historical behaviour).
    ``partial``: findings that only concern Parts/athletes withheld for failing QA do not fail the
    run, provided that (1) nothing else is wrong (uploads, storage identity, duplicates, summary and
    coverage accounting, an athlete with no Part at all, every *published* Part's own checks) and
    (2) at least one athlete has a publishable reel. With eligible athletes but nothing
    publishable the run still fails, so a run with no output is never reported as a success.
    """
    if mode not in GATE_MODES:
        raise ValueError(f"unknown gate mode {mode!r}; expected one of {GATE_MODES}")
    findings = validate_manifest(payload, coverage)
    blocking = [str(item) for item in findings if not isinstance(item, QaGap)]
    qa_gaps = [str(item) for item in findings if isinstance(item, QaGap)]

    athletes = [row for row in payload.get("athletes", []) or [] if isinstance(row, dict)]
    eligible = len(athletes)
    publishable = sum(1 for row in athletes if row.get("primary_publishable_reel"))
    published_parts = sum(
        1
        for row in athletes
        for part in row.get("parts", []) or []
        if isinstance(part, dict) and part.get("publishable") is True
    )

    errors = list(blocking)
    if mode == "strict":
        errors.extend(qa_gaps)
    elif qa_gaps and not blocking and publishable == 0:
        errors.extend(qa_gaps)
        errors.append("no eligible athlete has a publishable reel; the run produced no output")

    passed = not errors
    outcome = "failed" if not passed else ("partial" if qa_gaps else "complete")
    return {
        "mode": mode,
        "passed": passed,
        "outcome": outcome,
        "errors": errors,
        "blocking_errors": blocking,
        "qa_gaps": qa_gaps,
        "eligible_athlete_count": eligible,
        "publishable_athlete_count": publishable,
        "published_part_count": published_parts,
    }
