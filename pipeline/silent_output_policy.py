"""Enforce SportReel's video-only, no-audio product contract.

Athletes will add platform-native audio after download. Production therefore creates
and uploads only the clean silent render. Music selection/mixing is disabled, legacy
music variants are discarded, and a file containing audio is a deterministic product
contract failure rather than a preferred output.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_EDITOR_FLAG = "_sportreel_silent_output_editor_installed"
_POLICY_FLAG = "_sportreel_silent_output_policy_installed"
_INSTALL_DONE = False
MAX_PUBLISHABLE_SECONDS = 90.0
MIN_PUBLISHABLE_HEIGHT = 1280


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def silent_social_ready_issues(specs: dict[str, Any]) -> list[str]:
    """Return deterministic reasons a file violates the silent social-ready contract."""
    issues: list[str] = []
    audio_state = specs.get("has_audio")
    if audio_state is True:
        issues.append("unexpected_audio")
    elif audio_state is not False:
        issues.append("audio_state_unknown")

    duration = _finite_float(specs.get("duration"))
    if duration is None or duration <= 0:
        issues.append("invalid_duration")
    elif duration > MAX_PUBLISHABLE_SECONDS:
        issues.append("duration_over_90_seconds")

    aspect = _finite_float(specs.get("aspect"))
    if aspect is None or aspect <= 0 or abs(aspect - 9 / 16) > 0.02:
        issues.append("aspect_not_9_16")

    try:
        height = int(specs.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    if height < MIN_PUBLISHABLE_HEIGHT:
        issues.append("resolution_below_publishable_floor")
    return issues


def _canonical_path(path: str) -> str:
    return path[:-10] + ".mp4" if path.lower().endswith("_music.mp4") else path


def _safe_remove(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def canonicalize_silent_variants(
    reels: list[str],
    events_out: list[tuple[str, list[dict[str, Any]]]],
    *,
    specs_getter: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[list[str], list[tuple[str, list[dict[str, Any]]]], list[str]]:
    """Keep one silent clean render per Part and delete every audio/music variant."""
    if specs_getter is None:
        from pipeline.publishable_reel_policy import _default_specs

        inspect = _default_specs
    else:
        inspect = specs_getter

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
        clean_variants = [path for path in variants if not path.lower().endswith("_music.mp4")]
        specs_by_path: dict[str, dict[str, Any]] = {}
        for path in variants:
            inspected = inspect(path)
            specs_by_path[path] = inspected if isinstance(inspected, dict) else {}

        candidate: str | None = None
        candidate_specs: dict[str, Any] = {}
        for path in clean_variants:
            specs = specs_by_path[path]
            if specs.get("has_audio") is False:
                candidate = path
                candidate_specs = specs
                break

        if candidate is None:
            if any(specs_by_path[path].get("has_audio") is True for path in clean_variants):
                failures.append(f"unexpected_audio_variant:{Path(canonical).name}")
            else:
                failures.append(f"no_silent_variant:{Path(canonical).name}")
            for variant in variants:
                _safe_remove(variant)
            continue

        duration = _finite_float(candidate_specs.get("duration"))
        if duration is None or duration <= 0 or duration > MAX_PUBLISHABLE_SECONDS:
            code = (
                "invalid_duration"
                if duration is None or duration <= 0
                else "duration_over_90_seconds"
            )
            failures.append(f"{code}:{Path(canonical).name}")
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


def _patch_editor() -> None:
    from pipeline.stages import editor

    if getattr(editor, _EDITOR_FLAG, False):
        return
    original_compile_reel = editor.compile_reel
    original_bookend = editor._add_loop_bookend

    def no_music_picker(*_args, **_kwargs) -> None:
        return None

    def compile_silent(*args, **kwargs):
        mutable_args = list(args)
        if len(mutable_args) > 5:
            if mutable_args[5]:
                logger.info("Ignoring music_path because SportReel outputs silent video only")
            mutable_args[5] = None
        else:
            if kwargs.get("music_path"):
                logger.info("Ignoring music_path because SportReel outputs silent video only")
            kwargs["music_path"] = None
        return original_compile_reel(*mutable_args, **kwargs)

    def silent_bookend(reel_path: str, total_dur: float, has_audio: bool = False) -> None:
        return original_bookend(reel_path, total_dur, has_audio=False)

    editor._pick_music = no_music_picker
    editor.compile_reel = compile_silent
    editor._add_loop_bookend = silent_bookend
    setattr(editor, _EDITOR_FLAG, True)


def _patch_publishable_policy() -> None:
    import pipeline.publishable_reel_policy as policy

    if getattr(policy, _POLICY_FLAG, False):
        return
    policy.social_ready_issues = silent_social_ready_issues
    policy.canonicalize_publishable_variants = canonicalize_silent_variants
    setattr(policy, _POLICY_FLAG, True)


def install() -> None:
    """Install the canonical silent, mandatory-CV, quality-first media contract."""
    global _INSTALL_DONE
    if _INSTALL_DONE:
        return
    _patch_editor()
    _patch_publishable_policy()

    # These policies belong to the same media-output contract. Activating them
    # here preserves the repository's canonical bootstrap order while ensuring
    # every entrypoint requires detector/tracker evidence and renders 4K/30 with
    # contain-first framing.
    from pipeline.required_perception_policy import install as install_required_perception
    from pipeline.quality_preserving_framing import install as install_quality_framing

    install_required_perception()
    install_quality_framing()
    _INSTALL_DONE = True
