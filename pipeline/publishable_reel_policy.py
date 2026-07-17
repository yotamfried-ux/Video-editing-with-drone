"""Per-athlete canonical publishable-reel business contract.

The renderer may create intermediate variants, but the operator should receive one
social-ready output per part. Every eligible athlete must have one primary output
that passed deterministic technical checks and final QA, or the production business
gate must fail with explicit evidence.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = "sportreel.publishable_reel_manifest.v1"
MAX_PUBLISHABLE_SECONDS = 90.0
MIN_PUBLISHABLE_HEIGHT = 1280
_INSTALLED_FLAG = "_sportreel_publishable_reel_policy_installed"
_ORCHESTRATOR_FLAG = "_sportreel_publishable_reel_orchestrator_installed"
_INSTALL_DONE = False
_PENDING_VARIANT_FAILURES: dict[str, list[str]] = {}

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
- The sport-specific rules below decide which actions are usable. The athlete-level
  obligation above is global and must not be weakened by highlight-count preferences.
"""


def _manifest_path() -> Path:
    configured = os.getenv("PUBLISHABLE_REEL_MANIFEST_FILE", "").strip()
    if configured:
        return Path(configured)
    return Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "publishable_reel_manifest.json"


def _empty_manifest() -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def reset_manifest() -> Path:
    """Start a fresh run-scoped manifest and return its path."""
    path = _manifest_path()
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


def _event_lineage(events_by_reel: dict[str, list[dict[str, Any]]]) -> list[str]:
    rows: set[str] = set()
    for events in events_by_reel.values():
        for event in events or []:
            if event.get("_teaser"):
                continue
            source = str(event.get("_src") or event.get("source") or event.get("source_video") or "")
            try:
                start = round(float(event.get("start")), 3)
                end = round(float(event.get("end")), 3)
            except (TypeError, ValueError):
                start, end = -1.0, -1.0
            rows.add(f"{source}|{start:.3f}|{end:.3f}|{event.get('type', '')}")
    return sorted(rows)


def athlete_key(sport: str, athlete_label: str, events_by_reel: dict[str, list[dict[str, Any]]]) -> str:
    """Return a stable run-local key from identity label and source/action lineage."""
    seed = "\n".join([_normal(sport), _normal(athlete_label), *_event_lineage(events_by_reel)])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"athlete_{digest}"


def _default_specs(path: str) -> dict[str, Any]:
    try:
        from integrations.ffmpeg import get_reel_specs
        specs = get_reel_specs(path)
        return specs if isinstance(specs, dict) else {}
    except Exception as exc:
        logger.warning("Could not inspect publishable reel %s: %s", path, exc)
        return {}


def social_ready_issues(specs: dict[str, Any]) -> list[str]:
    """Return deterministic reasons that a rendered file is not directly publishable."""
    issues: list[str] = []
    if not specs.get("has_audio"):
        issues.append("missing_audio")
    try:
        duration = float(specs.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        issues.append("invalid_duration")
    elif duration > MAX_PUBLISHABLE_SECONDS:
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
        if float(candidate_specs.get("duration") or 0.0) > MAX_PUBLISHABLE_SECONDS:
            failures.append(f"duration_over_90_seconds:{Path(canonical).name}")
            for variant in variants:
                _safe_remove(variant)
            continue

        candidate_events = event_map.get(candidate) or event_map.get(canonical) or []
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


def record_athlete_outcome(
    *,
    sport: str,
    athlete_label: str,
    final_reels: list[str],
    events_by_reel: dict[str, list[dict[str, Any]]],
    flagged_paths: set[str],
    variant_failures: list[str] | None = None,
    specs_getter: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist one eligible athlete's canonical output and QA/technical state."""
    inspect = specs_getter or _default_specs
    parts: list[dict[str, Any]] = []
    publishable_names: list[str] = []
    blocking_reasons = list(variant_failures or [])

    for index, path in enumerate(final_reels or [], start=1):
        specs = inspect(path)
        issues = social_ready_issues(specs)
        qa_passed = path not in set(flagged_paths or set())
        if not qa_passed:
            issues = [*issues, "final_qa_failed"]
        is_publishable = qa_passed and not issues
        name = Path(path).name
        if is_publishable:
            publishable_names.append(name)
        else:
            blocking_reasons.extend(f"{issue}:{name}" for issue in issues)
        events = [event for event in events_by_reel.get(path, []) if not event.get("_teaser")]
        parts.append({
            "part_index": index,
            "file_name": name,
            "qa_passed": qa_passed,
            "technical_issues": issues,
            "publishable": is_publishable,
            "action_count": len(events),
            "duration": specs.get("duration"),
            "width": specs.get("width"),
            "height": specs.get("height"),
            "aspect": specs.get("aspect"),
            "has_audio": bool(specs.get("has_audio")),
        })

    primary = publishable_names[0] if publishable_names else None
    row = {
        "athlete_key": athlete_key(sport, athlete_label, events_by_reel),
        "athlete_label": athlete_label or "unknown athlete",
        "sport": sport or "sport",
        "eligible": True,
        "action_lineage": _event_lineage(events_by_reel),
        "action_count": len(_event_lineage(events_by_reel)),
        "parts": parts,
        "primary_publishable_reel": primary,
        "supplemental_publishable_reels": publishable_names[1:],
        "blocking_reasons": sorted(set(blocking_reasons)),
        "business_outcome": (
            "publishable_ready"
            if primary
            else "review_required"
            if final_reels
            else "no_publishable_variant"
        ),
    }

    payload = _read_manifest()
    existing = [item for item in payload.get("athletes", []) if item.get("athlete_key") != row["athlete_key"]]
    payload["athletes"] = [*existing, row]
    _recompute_summary(payload)
    _atomic_write(_manifest_path(), payload)
    return row


def _patch_analyzer_prompt() -> None:
    from pipeline.stages import analyzer
    current = str(getattr(analyzer, "_IDENTITY_PROMPT", ""))
    if _GENERAL_PROMPT_OVERRIDE not in current:
        analyzer._IDENTITY_PROMPT = current + _GENERAL_PROMPT_OVERRIDE


def _patch_editor_outputs() -> None:
    from pipeline.stages import editor
    if getattr(editor, _INSTALLED_FLAG, False):
        return

    original_create_reel = editor.create_reel
    original_compile_multi = editor.compile_multi_source_reel

    def create_reel(video_path, events, sport="", athlete_label="", _events_out=None):
        raw_events_out: list[tuple[str, list[dict[str, Any]]]] = []
        raw_reels = original_create_reel(
            video_path,
            events,
            sport=sport,
            athlete_label=athlete_label,
            _events_out=raw_events_out,
        )
        selected, selected_events, failures = canonicalize_publishable_variants(raw_reels, raw_events_out)
        _PENDING_VARIANT_FAILURES[_pending_key(sport, athlete_label)] = failures
        if _events_out is not None:
            _events_out.extend(selected_events)
        return selected

    def compile_multi_source_reel(appearances, sport="", athlete_label="", _events_out=None):
        raw_events_out: list[tuple[str, list[dict[str, Any]]]] = []
        raw_reels = original_compile_multi(
            appearances,
            sport=sport,
            athlete_label=athlete_label,
            _events_out=raw_events_out,
        )
        selected, selected_events, failures = canonicalize_publishable_variants(raw_reels, raw_events_out)
        _PENDING_VARIANT_FAILURES[_pending_key(sport, athlete_label)] = failures
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
            failures = _PENDING_VARIANT_FAILURES.pop(_pending_key(sport, athlete_label), [])
            record_athlete_outcome(
                sport=sport,
                athlete_label=athlete_label,
                final_reels=list(final_reels or []),
                events_by_reel=dict(events_by_reel or {}),
                flagged_paths=set(flagged or set()),
                variant_failures=failures,
            )
            return final_reels, events_by_reel, flagged

        orchestrator._qa_blocking = all_final_failures_block
        orchestrator._qa_gate = qa_gate
        setattr(orchestrator, _ORCHESTRATOR_FLAG, True)

    qa_policy._patch_orchestrator = patch_orchestrator
    existing = sys.modules.get("pipeline.orchestrator")
    if existing is not None:
        patch_orchestrator(existing)
    setattr(qa_policy, _INSTALLED_FLAG, True)


def install() -> None:
    """Install the global business prompt, canonical output, manifest, and QA gate."""
    global _INSTALL_DONE
    if _INSTALL_DONE:
        return
    reset_manifest()
    _patch_analyzer_prompt()
    _patch_editor_outputs()
    _patch_orchestrator_contract()
    _INSTALL_DONE = True
