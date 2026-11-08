"""Per-athlete canonical publishable-reel business contract.

The renderer may create intermediate variants, but the operator should receive one
social-ready output per part. Every eligible athlete must have one primary output
that passed deterministic technical checks, final QA, and upload to REVIEW, or the
production business gate must fail with explicit evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "sportreel.publishable_reel_manifest.v1"
STATE_RENDERED = "RENDERED"
STATE_QA_PENDING = "QA_PENDING"
STATE_QA_PASSED = "QA_PASSED"
STATE_UPLOAD_PENDING = "UPLOAD_PENDING"
STATE_UPLOADED = "UPLOADED"
STATE_QA_FAILED = "QA_FAILED"
STATE_UPLOAD_FAILED = "UPLOAD_FAILED"
STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
MAX_PUBLISHABLE_SECONDS = 90.0
MIN_PUBLISHABLE_HEIGHT = 1280
_INSTALLED_FLAG = "_sportreel_publishable_reel_policy_installed"
_ANALYZER_FLAG = "_sportreel_publishable_reel_analyzer_installed"
_ORCHESTRATOR_FLAG = "_sportreel_publishable_reel_orchestrator_installed"
_UPLOAD_FLAG = "_sportreel_publishable_reel_upload_installed"
_INSTALL_DONE = False
_MANIFEST_LOCK = threading.RLock()
_PENDING_VARIANT_FAILURES: dict[str, list[str]] = {}
_PENDING_EVENT_LINEAGE: dict[str, list[dict[str, Any]]] = {}

_GENERAL_PROMPT_OVERRIDE = """

SPORTREEL BUSINESS OUTPUT CONTRACT — APPLIES TO EVERY SPORT:
- The business goal is a personal social-media reel for EVERY DISTINCT ATHLETE who
  performs at least one complete, visible, usable action in the footage.
- Return a separate person record for every such athlete. ONE usable action is enough;
  do not omit an athlete merely because they have fewer than an arbitrary 3-8 events.
- Keep identity attribution conservative. An uncertain match must stay separate or be
  marked for review; never mix athletes to increase coverage.
- Each event must contain the complete readable action from setup through outcome and
  must retain source timestamps. Do not invent or pad timestamps to satisfy duration.
- The sport-specific rules elsewhere in this prompt decide which actions are usable.
  The athlete-level obligation above is global and must not be weakened by highlight-
  count preferences.
"""


def _manifest_path() -> Path:
    configured = os.getenv("PUBLISHABLE_REEL_MANIFEST_FILE", "").strip()
    if configured:
        return Path(configured)
    return Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "publishable_reel_manifest.json"


def _current_pipeline_run_id() -> str:
    return os.getenv("PIPELINE_RUN_ID", "").strip() or os.getenv("GITHUB_RUN_ID", "").strip() or "local_run"


def _remote_checkpoint_enabled() -> bool:
    """Use the existing SportReel R2 bucket only for stable, tracked R2 runs."""
    return (
        os.getenv("STORAGE_BACKEND", "drive").strip().lower() == "r2"
        and bool(os.getenv("PIPELINE_RUN_ID", "").strip())
        and os.getenv("SPORTREEL_REMOTE_MANIFEST_CHECKPOINT", "1").strip().lower()
        not in {"0", "false", "no", "off"}
    )


def _checkpoint_key() -> str:
    """Path-safe, non-PII key in the EXISTING R2 bucket."""
    run_id = os.getenv("PIPELINE_RUN_ID", "").strip()
    if not run_id:
        raise RuntimeError("R2 manifest checkpoint requires a stable PIPELINE_RUN_ID")
    fingerprint = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return f"metadata/pipeline_checkpoints/{fingerprint}.json"


def _load_remote_manifest() -> dict[str, Any] | None:
    from botocore.exceptions import ClientError
    from integrations import r2_storage as r2

    try:
        response = r2._client().get_object(Bucket=r2._bucket(), Key=_checkpoint_key())
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise  # A transient/auth failure must never silently reset the run.
    data = json.loads(response["Body"].read())
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError("R2 manifest checkpoint corrupt or wrong schema")
    if str(data.get("pipeline_run_id") or "") != _current_pipeline_run_id():
        raise RuntimeError("R2 manifest checkpoint belongs to a different run")
    if not isinstance(data.get("athletes"), list):
        raise RuntimeError("R2 manifest checkpoint athletes array is invalid")
    return data


def _store_remote_manifest(payload: dict[str, Any]) -> None:
    from integrations import r2_storage as r2

    serialized = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    r2._client().put_object(
        Bucket=r2._bucket(), Key=_checkpoint_key(),
        Body=serialized, ContentType="application/json",
    )


def _write_local_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def initialize_manifest() -> Path:
    """Restore same-run checkpoint across runner restarts; never erase blindly."""
    path = _manifest_path()
    with _MANIFEST_LOCK:
        if _remote_checkpoint_enabled():
            # Remote checkpoint is authoritative: a runner can lose its /tmp disk,
            # or crash between a successful R2 write and local atomic replace.
            recovered = _load_remote_manifest()
            if recovered is not None:
                _write_local_manifest(path, recovered)
                return path
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if (
                isinstance(data, dict)
                and data.get("schema_version") == MANIFEST_SCHEMA_VERSION
                and data.get("pipeline_run_id") == _current_pipeline_run_id()
                and isinstance(data.get("athletes"), list)
            ):
                return path
        _atomic_write(path, _empty_manifest())
    return path


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pipeline_run_id": _current_pipeline_run_id(),
        "business_contract": "one_primary_publishable_reel_per_eligible_athlete_v1",
        "athletes": [],
        "summary": {
            "eligible_athlete_count": 0,
            "publishable_athlete_count": 0,
            "primary_publishable_reel_count": 0,
            "supplemental_publishable_reel_count": 0,
            "coverage_gap_count": 0,
        },
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    # Persist remote checkpoint FIRST. If the process dies after R2 acknowledges
    # the write, initialize_manifest restores the newest authoritative state.
    if _remote_checkpoint_enabled():
        _store_remote_manifest(payload)
    _write_local_manifest(path, payload)


def reset_manifest() -> Path:
    """Start a fresh run-scoped manifest and return its path."""
    path = _manifest_path()
    with _MANIFEST_LOCK:
        _atomic_write(path, _empty_manifest())
    return path


def _read_manifest() -> dict[str, Any]:
    path = _manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_manifest()
    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return _empty_manifest()
    if not isinstance(payload.get("athletes"), list):
        payload["athletes"] = []
    return payload


def _normal(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _event_identity(event: dict[str, Any]) -> tuple[str, float, float, str]:
    source = str(event.get("_src") or event.get("source") or event.get("source_video") or "")
    try:
        start = round(float(event.get("start")), 3)
        end = round(float(event.get("end")), 3)
    except (TypeError, ValueError):
        start, end = -1.0, -1.0
    return source, start, end, str(event.get("type") or "")


def _flatten_events(events_out: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, float, float, str], dict[str, Any]] = {}
    for _, events in events_out or []:
        for event in events or []:
            if not isinstance(event, dict) or event.get("_teaser"):
                continue
            unique.setdefault(_event_identity(event), dict(event))
    return list(unique.values())


def _event_lineage(events_by_reel: dict[str, list[dict[str, Any]]]) -> list[str]:
    rows: set[str] = set()
    for events in events_by_reel.values():
        for event in events or []:
            if not isinstance(event, dict) or event.get("_teaser"):
                continue
            source, start, end, event_type = _event_identity(event)
            rows.add(f"{source}|{start:.3f}|{end:.3f}|{event_type}")
    return sorted(rows)


def _athlete_ids(events_by_reel: dict[str, list[dict[str, Any]]]) -> list[str]:
    return sorted({
        str(event.get("athlete_id"))
        for events in events_by_reel.values()
        for event in events or []
        if isinstance(event, dict) and event.get("athlete_id")
    })


def athlete_key(sport: str, athlete_label: str, events_by_reel: dict[str, list[dict[str, Any]]]) -> str:
    """Return a stable run-local key, anchored to canonical identity when available.

    QA/recompile passes may change action lineage. They must update the same athlete
    manifest row instead of creating duplicate ownership rows for one athlete_id.
    """
    ids = _athlete_ids(events_by_reel)
    if len(ids) == 1:
        seed = "\n".join([_normal(sport), "canonical", ids[0]])
    else:
        seed = "\n".join([_normal(sport), *ids, _normal(athlete_label), *_event_lineage(events_by_reel)])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"athlete_{digest}"


def validate_session_semantics(parsed: dict[str, Any]) -> dict[str, Any]:
    """Validate model JSON semantically after parsing; valid JSON alone is insufficient."""
    if not isinstance(parsed, dict):
        raise ValueError("session result must be an object")
    persons = parsed.get("persons")
    if not isinstance(persons, list):
        raise ValueError("session persons must be an array")

    seen_person_ids: set[str] = set()
    validated_people: list[dict[str, Any]] = []
    for person_index, person in enumerate(persons):
        if not isinstance(person, dict):
            raise ValueError(f"person {person_index} must be an object")
        person_id = str(person.get("id") or "").strip()
        if not person_id:
            raise ValueError(f"person {person_index} is missing id")
        if person_id in seen_person_ids:
            raise ValueError(f"duplicate person id: {person_id}")
        seen_person_ids.add(person_id)
        events = person.get("events")
        if not isinstance(events, list):
            raise ValueError(f"{person_id} events must be an array")
        validated_events: list[dict[str, Any]] = []
        for event_index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError(f"{person_id} event {event_index} must be an object")
            try:
                start = float(event.get("start"))
                end = float(event.get("end"))
                score = int(event.get("score"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{person_id} event {event_index} has invalid numeric fields") from exc
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError(f"{person_id} event {event_index} has invalid time window")
            if not 1 <= score <= 10:
                raise ValueError(f"{person_id} event {event_index} score must be 1-10")
            if not str(event.get("type") or "").strip():
                raise ValueError(f"{person_id} event {event_index} is missing type")
            validated_events.append(dict(event))
        validated_people.append({**person, "id": person_id, "events": validated_events})
    return {**parsed, "persons": validated_people}


def require_real_qa_result(result: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when model QA was unavailable instead of approving an ungraded reel."""
    if not isinstance(result, dict):
        result = {}
    overall = str(result.get("overall") or "").strip().lower()
    if result.get("verdict") in {"PASS", "FAIL"} and overall != "qa skipped":
        return result
    technical = result.get("technical") if isinstance(result.get("technical"), dict) else {}
    defects = [item for item in result.get("defects", []) or [] if isinstance(item, dict)]
    defects.append({
        "type": "QA_UNAVAILABLE",
        "severity": "critical",
        "at_seconds": 0,
        "note": "Final social-media QA did not return a real grade.",
    })
    return {
        **result,
        "verdict": "FAIL",
        "technical": technical,
        "defects": defects,
        "engagement_score": 0,
        "overall": "Final QA unavailable; approval blocked.",
    }


def _default_specs(path: str) -> dict[str, Any]:
    try:
        from integrations.ffmpeg import get_reel_specs
        specs = get_reel_specs(path)
        return specs if isinstance(specs, dict) else {}
    except Exception as exc:
        logger.warning("Could not inspect publishable reel %s: %s", path, exc)
        return {}


def _one_reel_per_athlete() -> bool:
    return os.getenv("SPORTREEL_ONE_REEL_PER_ATHLETE", "1").strip().lower() not in {"0", "false", "no", "off"}


def social_ready_issues(specs: dict[str, Any]) -> list[str]:
    """Return deterministic reasons that a rendered file is not directly publishable."""
    issues: list[str] = []
    audio_state = specs.get("has_audio")
    if audio_state is True:
        issues.append("unexpected_audio")
    elif audio_state is not False:
        issues.append("audio_state_unknown")
    try:
        duration = float(specs.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    allow_unbounded = bool(specs.get("single_reel_per_athlete")) and _one_reel_per_athlete()
    if duration <= 0:
        issues.append("invalid_duration")
    elif duration > MAX_PUBLISHABLE_SECONDS and not allow_unbounded:
        issues.append("duration_over_90_seconds")
    try:
        aspect = float(specs.get("aspect"))
    except (TypeError, ValueError):
        aspect = 0.0
    if aspect <= 0 or abs(aspect - 9 / 16) > 0.02:
        issues.append("aspect_not_9_16")
    try:
        height = int(specs.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    if height < MIN_PUBLISHABLE_HEIGHT:
        issues.append("resolution_below_publishable_floor")
    return issues


def _canonical_path(path: str) -> str:
    if path.lower().endswith("_music.mp4"):
        return path[:-10] + ".mp4"
    return path


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def canonicalize_publishable_variants(
    reels: list[str],
    events_out: list[tuple[str, list[dict[str, Any]]]],
    *,
    specs_getter: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[list[str], list[tuple[str, list[dict[str, Any]]]], list[str]]:
    """Collapse intermediate clean/music variants into one audio-capable file per part."""
    inspect = specs_getter or _default_specs
    event_map = {path: list(events or []) for path, events in events_out}
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for path in reels or []:
        canonical = _canonical_path(path)
        if canonical not in groups:
            groups[canonical] = []
            order.append(canonical)
        groups[canonical].append(path)

    selected: list[str] = []
    selected_events: list[tuple[str, list[dict[str, Any]]]] = []
    failures: list[str] = []

    for canonical in order:
        variants = groups[canonical]
        preferred = sorted(variants, key=lambda item: ("_music.mp4" not in item.lower(), variants.index(item)))
        candidate: str | None = None
        candidate_specs: dict[str, Any] = {}
        for variant in preferred:
            specs = inspect(variant)
            if specs.get("has_audio"):
                candidate = variant
                candidate_specs = specs
                break
        if candidate is None:
            failures.append(f"no_audio_variant:{Path(canonical).name}")
            for variant in variants:
                _safe_remove(variant)
            continue
        candidate_events = event_map.get(candidate) or event_map.get(canonical) or []
        allow_unbounded = _one_reel_per_athlete() and (
            len(order) == 1 and (len(candidate_events) > 1 or bool(candidate_specs.get("single_reel_per_athlete")))
        )
        if float(candidate_specs.get("duration") or 0.0) > MAX_PUBLISHABLE_SECONDS and not allow_unbounded:
            failures.append(f"duration_over_90_seconds:{Path(canonical).name}")
            for variant in variants:
                _safe_remove(variant)
            continue
        if candidate != canonical:
            try:
                os.replace(candidate, canonical)
            except OSError as exc:
                failures.append(f"canonical_rename_failed:{Path(canonical).name}:{exc}")
                for variant in variants:
                    _safe_remove(variant)
                continue
        for variant in variants:
            if variant not in {candidate, canonical}:
                _safe_remove(variant)
        selected.append(canonical)
        selected_events.append((canonical, candidate_events))

    return selected, selected_events, failures


def _pending_key(sport: str, athlete_label: str) -> str:
    return f"{_normal(sport)}::{_normal(athlete_label)}"


def _refresh_row_publishability(row: dict[str, Any]) -> None:
    parts = [part for part in row.get("parts", []) if isinstance(part, dict)]
    publishable_names: list[str] = []
    for part in parts:
        ready = bool(part.get("render_ready"))
        uploaded = bool(part.get("uploaded_to_review"))
        authority_ok = (
            not part.get("authoritative_publishability_required")
            or part.get("authoritative_publishability_persisted") is True
        )
        # Never count an uploaded render as publishable without persisted,
        # positive QA evidence and clean technical checks.
        qa_ok = (
            part.get("qa_evidence_recorded") is True
            and str(part.get("qa_verdict") or "").upper() == "PASS"
            and part.get("qa_passed") is True
            and not (part.get("technical_issues") or [])
        )
        publishable = ready and uploaded and not part.get("upload_error") and authority_ok and qa_ok
        part["publishable"] = publishable
        if publishable and part.get("review_draft_name"):
            publishable_names.append(str(part["review_draft_name"]))
    row["primary_publishable_reel"] = publishable_names[0] if publishable_names else None
    row["supplemental_publishable_reels"] = publishable_names[1:]
    if publishable_names and len(publishable_names) == len(parts):
        row["business_outcome"] = "publishable_ready"
    elif publishable_names:
        row["business_outcome"] = "partial_publishable_output"
    elif parts:
        row["business_outcome"] = "review_or_upload_required"
    else:
        row["business_outcome"] = "no_publishable_variant"


def _recompute_summary(payload: dict[str, Any]) -> None:
    athletes = [row for row in payload.get("athletes", []) if isinstance(row, dict)]
    publishable = [row for row in athletes if row.get("primary_publishable_reel")]
    payload["summary"] = {
        "eligible_athlete_count": len(athletes),
        "publishable_athlete_count": len(publishable),
        "primary_publishable_reel_count": sum(1 for row in athletes if row.get("primary_publishable_reel")),
        "supplemental_publishable_reel_count": sum(
            len(row.get("supplemental_publishable_reels") or []) for row in athletes
        ),
        "coverage_gap_count": sum(1 for row in athletes if not row.get("primary_publishable_reel")),
    }


def _manifest_revision(row: dict[str, Any], part: dict[str, Any]) -> str:
    snapshot = {
        "athlete_key": row.get("athlete_key"),
        "athlete_ids": row.get("athlete_ids"),
        "part_index": part.get("part_index"),
        "storage_object_id": part.get("storage_object_id"),
        "qa_evidence_recorded": part.get("qa_evidence_recorded"),
        "qa_verdict": part.get("qa_verdict"),
        "qa_passed": part.get("qa_passed"),
        "technical_issues": part.get("technical_issues"),
        "media_specs_revision": part.get("media_specs_revision"),
        "render_ready": part.get("render_ready"),
        "uploaded_to_review": part.get("uploaded_to_review"),
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def qa_note_reasons(part: dict[str, Any], limit: int = 6) -> list[str]:
    """Human-readable QA findings for a Part that did not pass, so the operator sees WHY (and so do we).

    The verdict alone ("final_qa_failed") used to be all that reached the database and the app; the
    model's score and per-defect notes stayed in the log. Empty for a passing or ungraded Part.
    """
    if str(part.get("qa_verdict") or "").upper() != "FAIL":
        return []
    out: list[str] = []
    score = part.get("qa_engagement_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        out.append(f"qa_score:{int(score)}/{os.getenv('QA_ENGAGEMENT_THRESHOLD', '60')}")
    overall = str(part.get("qa_overall") or "").strip()
    if overall:
        out.append(f"qa_summary:{overall[:160]}")
    for defect in part.get("qa_defects", []) or []:
        if not isinstance(defect, dict) or len(out) >= limit:
            continue
        kind = str(defect.get("type") or defect.get("code") or "DEFECT").upper()
        if kind == "QA_REVIEW_REQUIRED":
            continue  # bookkeeping marker, not a finding
        note = str(defect.get("note") or "").strip()
        severity = str(defect.get("severity") or "").lower()
        out.append(f"qa_{severity or 'defect'}:{kind}" + (f": {note[:140]}" if note else ""))
    return out


def _draft_publishability_record(
    row: dict[str, Any],
    part: dict[str, Any],
    *,
    storage_object_id: str,
    draft_name: str,
) -> dict[str, Any]:
    technical_issues = [str(item) for item in part.get("technical_issues", []) or []]
    intended_publishable = bool(
        part.get("render_ready")
        and part.get("uploaded_to_review")
        and not part.get("upload_error")
        and not technical_issues
        and part.get("qa_evidence_recorded") is True
        and str(part.get("qa_verdict") or "").upper() == "PASS"
        and part.get("qa_passed") is True
    )
    reasons = [str(item) for item in row.get("blocking_reasons", []) or []]
    reasons.extend(qa_note_reasons(part))
    if not intended_publishable and not reasons:
        reasons.append("authoritative_publishability_contract_not_satisfied")
    return {
        "storage_object_id": storage_object_id,
        "draft_name": draft_name,
        "pipeline_run_id": os.getenv("PIPELINE_RUN_ID") or None,
        "athlete_key": row.get("athlete_key"),
        "part_index": int(part.get("part_index") or 0),
        "publishable": intended_publishable,
        "qa_evidence_recorded": part.get("qa_evidence_recorded") is True,
        "qa_verdict": str(part.get("qa_verdict") or "").upper() or None,
        "qa_passed": part.get("qa_passed") is True,
        "technical_issues": technical_issues,
        "approval_blocked_reasons": sorted(set(reasons)),
        "media_specs_revision": part.get("media_specs_revision"),
        "manifest_revision": _manifest_revision(row, part),
    }


def _persist_draft_publishability(record: dict[str, Any]) -> None:
    from integrations.supabase_uploader import upsert_draft_publishability

    upsert_draft_publishability(record)


def _find_upload_part(
    payload: dict[str, Any],
    draft_path: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    target = os.path.abspath(str(draft_path))
    # Exact-path matches must also be unique. Silently choosing the first row
    # can attribute an uploaded draft to the wrong athlete.
    exact_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in payload.get("athletes", []) or []:
        if not isinstance(row, dict):
            continue
        for part in row.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            paths = {os.path.abspath(str(part.get("local_path") or ""))}
            paths.update(
                os.path.abspath(str(alias))
                for alias in part.get("upload_path_aliases", []) or []
            )
            if target in paths:
                exact_matches.append((row, part))
    if len(exact_matches) == 1:
        return exact_matches[0]
    if exact_matches:
        logger.error("Ambiguous upload path %s matches %d manifest parts", target, len(exact_matches))
        return None

    # Some upload paths are materialized in a different temporary directory after
    # the manifest row is written. Reconcile by basename only when it is unique
    # across the entire manifest; ambiguity remains fail-closed.
    target_name = os.path.basename(target)
    basename_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in payload.get("athletes", []) or []:
        if not isinstance(row, dict):
            continue
        for part in row.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            names = {os.path.basename(str(part.get("local_path") or ""))}
            names.update(os.path.basename(str(alias)) for alias in part.get("upload_path_aliases", []) or [])
            if target_name and target_name in names:
                basename_matches.append((row, part))
    if len(basename_matches) == 1:
        return basename_matches[0]
    return None


def _specs_key(path: str) -> str:
    return os.path.abspath(str(path))


def _media_specs_revision(specs: dict[str, Any]) -> str:
    payload = json.dumps(specs, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _resolve_specs_snapshot(
    paths: list[str],
    inspect: Callable[[str], dict[str, Any]],
    specs_by_path: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    provided = specs_by_path or {}
    snapshot: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = provided.get(path) or provided.get(_specs_key(path))
        if value is None:
            value = inspect(path)
        snapshot[_specs_key(path)] = dict(value) if isinstance(value, dict) else {}
    return snapshot


def record_athlete_outcome(
    *,
    sport: str,
    athlete_label: str,
    final_reels: list[str],
    events_by_reel: dict[str, list[dict[str, Any]]],
    flagged_paths: set[str],
    variant_failures: list[str] | None = None,
    specs_getter: Callable[[str], dict[str, Any]] | None = None,
    specs_by_path: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist one eligible athlete's rendered output before upload confirmation."""
    inspect = specs_getter or _default_specs
    specs_snapshot = _resolve_specs_snapshot(list(final_reels or []), inspect, specs_by_path)
    parts: list[dict[str, Any]] = []
    blocking_reasons = list(variant_failures or [])

    for index, path in enumerate(final_reels or [], start=1):
        specs = dict(specs_snapshot.get(_specs_key(path), {}))
        events = [event for event in events_by_reel.get(path, []) if not event.get("_teaser")]
        if _one_reel_per_athlete() and len(final_reels or []) == 1 and len(events) > 1:
            specs["single_reel_per_athlete"] = True
        issues = social_ready_issues(specs)
        qa_passed = path not in set(flagged_paths or set())
        if not qa_passed:
            issues = [*issues, "final_qa_failed"]
        render_ready = qa_passed and not issues
        name = Path(path).name
        if not render_ready:
            blocking_reasons.extend(f"{issue}:{name}" for issue in issues)
        if not qa_passed:
            part_state = STATE_QA_FAILED
            failure_reason = "final_qa_failed"
        elif issues:
            part_state = STATE_REVIEW_REQUIRED if any("review" in str(i).lower() for i in issues) else STATE_QA_FAILED
            failure_reason = ";".join(str(i) for i in issues)
        elif render_ready:
            part_state = STATE_UPLOAD_PENDING
            failure_reason = None
        else:
            part_state = STATE_RENDERED
            failure_reason = None

        content_sha256 = ""
        try:
            if Path(path).exists() and Path(path).is_file():
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                content_sha256 = h.hexdigest()
        except Exception:
            pass
        if not content_sha256:
            content_sha256 = _media_specs_revision(specs)

        ath_key = athlete_key(sport, athlete_label, events_by_reel)
        product_id = f"reel_{ath_key[:16]}_{index}_{content_sha256[:12]}"
        run_id = os.getenv("RUN_ID") or os.getenv("GITHUB_RUN_ID") or "local_run"
        ath_ids = _athlete_ids(events_by_reel)
        athlete_id = ath_ids[0] if ath_ids else ath_key

        parts.append({
            "part_index": index,
            "product_id": product_id,
            "athlete_id": athlete_id,
            "run_id": run_id,
            "content_sha256": content_sha256,
            "state": part_state,
            "attempts": 1,
            "attempt_history": [
                {
                    "state": part_state,
                    "failure_reason": failure_reason,
                    "run_id": run_id,
                }
            ],
            "failure_reason": failure_reason,
            "local_path": path,
            "local_file_name": name,
            "file_name": None,
            "review_draft_name": None,
            "uploaded_to_review": False,
            "upload_error": None,
            "qa_passed": qa_passed,
            "technical_issues": issues,
            "render_ready": render_ready,
            "publishable": False,
            "action_count": len(events),
            "duration": specs.get("duration"),
            "width": specs.get("width"),
            "height": specs.get("height"),
            "aspect": specs.get("aspect"),
            "has_audio": specs.get("has_audio") if isinstance(specs.get("has_audio"), bool) else None,
            "media_specs_revision": _media_specs_revision(specs),
        })

    row = {
        "athlete_key": athlete_key(sport, athlete_label, events_by_reel),
        "athlete_ids": _athlete_ids(events_by_reel),
        "athlete_label": athlete_label or "unknown athlete",
        "sport": sport or "sport",
        "eligible": True,
        "action_lineage": _event_lineage(events_by_reel),
        "action_count": len(_event_lineage(events_by_reel)),
        "parts": parts,
        "primary_publishable_reel": None,
        "supplemental_publishable_reels": [],
        "blocking_reasons": sorted(set(blocking_reasons)),
        "business_outcome": "render_ready_pending_upload" if any(part["render_ready"] for part in parts) else "no_publishable_variant",
    }
    _refresh_row_publishability(row)

    with _MANIFEST_LOCK:
        payload = _read_manifest()
        athletes = [item for item in payload.get("athletes", []) if isinstance(item, dict)]
        prior = next((item for item in athletes if item.get("athlete_key") == row["athlete_key"]), None)
        if prior is not None:
            # An athlete can be emitted in multiple render batches. Do not drop
            # already rendered/uploaded parts when a later batch is recorded.
            # Re-recording the same path replaces that part (new QA/specs), while
            # unrelated paths retain their upload/authority state.
            merged = {str(part.get("local_path")): dict(part)
                      for part in prior.get("parts", [])
                      if isinstance(part, dict) and part.get("local_path")}
            for part in row["parts"]:
                prev = merged.get(str(part["local_path"]))
                if prev and prev.get("state") == STATE_UPLOADED and prev.get("content_sha256") == part.get("content_sha256"):
                    part["state"] = STATE_UPLOADED
                    part["uploaded_to_review"] = True
                    part["review_draft_name"] = prev.get("review_draft_name")
                    part["file_name"] = prev.get("file_name")
                    part["storage_object_id"] = prev.get("storage_object_id")
                    part["attempts"] = prev.get("attempts", 1)
                    part["attempt_history"] = prev.get("attempt_history", [])
                    part["failure_reason"] = None
                elif prev and prev.get("attempts"):
                    part["attempts"] = prev["attempts"] + 1
                    part["attempt_history"] = list(prev.get("attempt_history", [])) + part.get("attempt_history", [])
                merged[str(part["local_path"])] = part
            row["parts"] = list(merged.values())
            for index, part in enumerate(row["parts"], start=1):
                part["part_index"] = index
            row["action_lineage"] = list(dict.fromkeys(
                [*(prior.get("action_lineage") or []), *row["action_lineage"]]
            ))
            row["action_count"] = len(row["action_lineage"])
            row["athlete_ids"] = sorted(set(
                [*(prior.get("athlete_ids") or []), *row["athlete_ids"]]
            ))
            row["blocking_reasons"] = sorted(set(
                [*(prior.get("blocking_reasons") or []), *row["blocking_reasons"]]
            ))
            _refresh_row_publishability(row)
        existing = [item for item in athletes if item.get("athlete_key") != row["athlete_key"]]
        payload["athletes"] = [*existing, row]
        _recompute_summary(payload)
        _atomic_write(_manifest_path(), payload)
    return row


def mark_upload_result(
    draft_path: str,
    draft_name: str,
    error: str | None = None,
    *,
    storage_object_id: str | None = None,
) -> bool:
    """Attach REVIEW upload and persist authoritative server-side publishability.

    The storage upload can succeed before the database authority write. In that
    case the object remains visible but is fail-closed by the API, and the manifest
    receives an explicit blocking issue so the business gate fails.
    """
    authority_record: dict[str, Any] | None = None
    with _MANIFEST_LOCK:
        payload = _read_manifest()
        matched_pair = _find_upload_part(payload, draft_path)
        if matched_pair is None:
            logger.warning("Publishable manifest could not match uploaded draft path %s", draft_path)
            return False
        row, part = matched_pair
        part["upload_error"] = str(error) if error else None
        part["uploaded_to_review"] = error is None
        if error is None:
            part["state"] = STATE_UPLOADED
            part["failure_reason"] = None
            history = list(part.get("attempt_history", []))
            history.append({
                "state": STATE_UPLOADED,
                "failure_reason": None,
                "step": "upload_success",
            })
            part["attempt_history"] = history
            part["review_draft_name"] = draft_name
            part["file_name"] = draft_name
            part["uploaded_local_path"] = os.path.abspath(str(draft_path))
            if storage_object_id:
                part["storage_object_id"] = str(storage_object_id)
                part["authoritative_publishability_required"] = True
                part["authoritative_publishability_persisted"] = False
                authority_record = _draft_publishability_record(
                    row,
                    part,
                    storage_object_id=str(storage_object_id),
                    draft_name=draft_name,
                )
        else:
            part["state"] = STATE_UPLOAD_FAILED
            part["failure_reason"] = str(error)
            history = list(part.get("attempt_history", []))
            history.append({
                "state": STATE_UPLOAD_FAILED,
                "failure_reason": str(error),
                "step": "upload_error",
            })
            part["attempt_history"] = history
            reasons = list(row.get("blocking_reasons") or [])
            reasons.append(f"review_upload_failed:{Path(draft_path).name}:{error}")
            row["blocking_reasons"] = sorted(set(reasons))
        _refresh_row_publishability(row)
        _recompute_summary(payload)
        _atomic_write(_manifest_path(), payload)

    if authority_record is None:
        return True

    try:
        _persist_draft_publishability(authority_record)
    except Exception as exc:
        logger.exception("Authoritative draft publishability persistence failed for %s", draft_name)
        with _MANIFEST_LOCK:
            payload = _read_manifest()
            matched_pair = _find_upload_part(payload, draft_path)
            if matched_pair is not None:
                row, part = matched_pair
                issues = [str(item) for item in part.get("technical_issues", []) or []]
                if "publishability_authority_persistence_failed" not in issues:
                    issues.append("publishability_authority_persistence_failed")
                part["technical_issues"] = sorted(set(issues))
                part["authoritative_publishability_persisted"] = False
                reasons = list(row.get("blocking_reasons") or [])
                reasons.append(f"publishability_authority_persistence_failed:{draft_name}:{exc}")
                row["blocking_reasons"] = sorted(set(reasons))
                _refresh_row_publishability(row)
                _recompute_summary(payload)
                _atomic_write(_manifest_path(), payload)
        return True

    with _MANIFEST_LOCK:
        payload = _read_manifest()
        matched_pair = _find_upload_part(payload, draft_path)
        if matched_pair is not None:
            row, part = matched_pair
            part["authoritative_publishability_persisted"] = True
            part["authoritative_manifest_revision"] = authority_record["manifest_revision"]
            _refresh_row_publishability(row)
            _recompute_summary(payload)
            _atomic_write(_manifest_path(), payload)
    return True


def _patch_analyzer_contract() -> None:
    from pipeline.stages import analyzer
    if getattr(analyzer, _ANALYZER_FLAG, False):
        return
    current = str(getattr(analyzer, "_IDENTITY_PROMPT", ""))
    if _GENERAL_PROMPT_OVERRIDE not in current:
        analyzer._IDENTITY_PROMPT = current + _GENERAL_PROMPT_OVERRIDE

    original_parse = analyzer._parse_session
    original_qa = analyzer.qa_check_reel

    def parse_with_business_validation(raw_text: str) -> dict[str, Any]:
        return validate_session_semantics(original_parse(raw_text))

    def qa_with_required_grade(*args, **kwargs):
        return require_real_qa_result(original_qa(*args, **kwargs))

    analyzer._parse_session = parse_with_business_validation
    analyzer.qa_check_reel = qa_with_required_grade
    setattr(analyzer, _ANALYZER_FLAG, True)


def _stamp_render_invocation(
    selected_events: list, scope_token: str, *, invocation_id: str | None = None
) -> list:
    """Preserve ONE stable invocation ID throughout render, EDL, QA and upload."""
    if not str(scope_token).startswith("publishable_"):
        return selected_events
    if invocation_id is None:
        from pipeline.publishable_pending_scope import bind_invocation_id
        invocation_id = f"render_{uuid.uuid4().hex}"
        bind_invocation_id(scope_token, invocation_id)
    return [
        (path, [{**event, "_render_invocation_id": invocation_id}
                for event in (events or [])])
        for path, events in selected_events
    ]


def _patch_editor_outputs() -> None:
    from pipeline.stages import editor
    if getattr(editor, _INSTALLED_FLAG, False):
        return

    original_create_reel = editor.create_reel
    original_compile_multi = editor.compile_multi_source_reel

    def create_reel(video_path, events, sport="", athlete_label="", _events_out=None, **kwargs):
        raw_events_out: list[tuple[str, list[dict[str, Any]]]] = []
        # An invocation ID is pipeline metadata; the physical editor does not
        # accept this keyword. Passing it through previously raised TypeError,
        # triggering a legacy retry without scope correlation.
        inv_id = kwargs.pop("invocation_id", None)
        raw_reels = original_create_reel(
            video_path,
            events,
            sport=sport,
            athlete_label=athlete_label,
            _events_out=raw_events_out,
            **kwargs,
        )
        key = _pending_key(sport, athlete_label, invocation_id=inv_id)
        _PENDING_EVENT_LINEAGE[key] = _flatten_events(raw_events_out) or [
            dict(event) for event in events or [] if isinstance(event, dict) and not event.get("_teaser")
        ]
        selected, selected_events, failures = canonicalize_publishable_variants(raw_reels, raw_events_out)
        selected_events = _stamp_render_invocation(selected_events, key, invocation_id=inv_id)
        _PENDING_VARIANT_FAILURES[key] = failures
        if _events_out is not None:
            _events_out.extend(selected_events)
        return selected

    def compile_multi_source_reel(appearances, sport="", athlete_label="", _events_out=None, **kwargs):
        raw_events_out: list[tuple[str, list[dict[str, Any]]]] = []
        inv_id = kwargs.pop("invocation_id", None)
        raw_reels = original_compile_multi(
            appearances,
            sport=sport,
            athlete_label=athlete_label,
            _events_out=raw_events_out,
            **kwargs,
        )
        key = _pending_key(sport, athlete_label, invocation_id=inv_id)
        input_events = [
            dict(event)
            for appearance in appearances or []
            for event in appearance.get("events", []) or []
            if isinstance(event, dict) and not event.get("_teaser")
        ]
        _PENDING_EVENT_LINEAGE[key] = _flatten_events(raw_events_out) or input_events
        selected, selected_events, failures = canonicalize_publishable_variants(raw_reels, raw_events_out)
        selected_events = _stamp_render_invocation(selected_events, key, invocation_id=inv_id)
        _PENDING_VARIANT_FAILURES[key] = failures
        if _events_out is not None:
            _events_out.extend(selected_events)
        return selected

    editor.create_reel = create_reel
    editor.compile_multi_source_reel = compile_multi_source_reel
    setattr(editor, _INSTALLED_FLAG, True)


def _patch_orchestrator_contract() -> None:
    import pipeline.qa_gate_policy as qa_policy
    if getattr(qa_policy, _INSTALLED_FLAG, False):
        return

    original_patch_orchestrator = qa_policy._patch_orchestrator

    def patch_orchestrator(orchestrator: Any) -> None:
        original_patch_orchestrator(orchestrator)
        if getattr(orchestrator, _ORCHESTRATOR_FLAG, False):
            return
        original_qa_gate = orchestrator._qa_gate

        def all_final_failures_block(qa: dict[str, Any]) -> bool:
            return qa.get("verdict") != "PASS"

        def qa_gate(reels, events_out, sport, athlete_label, recompile):
            final_reels, events_by_reel, flagged = original_qa_gate(
                reels,
                events_out,
                sport,
                athlete_label,
                recompile,
            )
            key = _pending_key(sport, athlete_label)
            failures = _PENDING_VARIANT_FAILURES.pop(key, [])
            fallback_events = _PENDING_EVENT_LINEAGE.pop(key, [])
            evidence_map = dict(events_by_reel or {})
            if fallback_events:
                evidence_map["__eligible_input__"] = fallback_events
            record_athlete_outcome(
                sport=sport,
                athlete_label=athlete_label,
                final_reels=list(final_reels or []),
                events_by_reel=evidence_map,
                flagged_paths=set(flagged or set()),
                variant_failures=failures,
            )
            return final_reels, events_by_reel, flagged

        orchestrator._qa_blocking = all_final_failures_block
        orchestrator._qa_gate = qa_gate

        if not getattr(orchestrator, _UPLOAD_FLAG, False):
            original_upload = orchestrator.upload_draft

            def upload_with_manifest(draft_path: str, draft_name: str):
                try:
                    result = original_upload(draft_path, draft_name)
                except Exception as exc:
                    mark_upload_result(draft_path, draft_name, error=str(exc))
                    raise
                mark_upload_result(
                    draft_path,
                    draft_name,
                    storage_object_id=str(result or draft_name),
                )
                return result

            orchestrator.upload_draft = upload_with_manifest
            setattr(orchestrator, _UPLOAD_FLAG, True)

        setattr(orchestrator, _ORCHESTRATOR_FLAG, True)

    qa_policy._patch_orchestrator = patch_orchestrator
    existing = sys.modules.get("pipeline.orchestrator")
    if existing is not None:
        patch_orchestrator(existing)
    setattr(qa_policy, _INSTALLED_FLAG, True)


def install() -> None:
    """Install the global prompt, validation, canonical output, manifest, and gates."""
    global _INSTALL_DONE
    if _INSTALL_DONE:
        return
    initialize_manifest()
    _patch_analyzer_contract()
    _patch_editor_outputs()
    _patch_orchestrator_contract()
    _INSTALL_DONE = True
