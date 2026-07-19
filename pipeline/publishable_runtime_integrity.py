"""Runtime integrity hardening for the final publishable manifest.

This module closes two cross-layer gaps that are easy to miss in isolated tests:

* a rendered Part starts fail-closed until explicit final-QA evidence is applied;
* long-video staging paths remain aliases of the original manifest Part during upload.

Invocation-scoped QA storage is owned exclusively by
``pipeline.publishable_pending_scope`` and ``pipeline.publishable_qa_evidence``.
This module must not replace those functions with a second token implementation.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable

_INSTALL_DONE = False
_POLICY_FLAG = "_sportreel_publishable_runtime_integrity_policy_installed"
_CONTEXT_FLAG = "_sportreel_publishable_runtime_integrity_context_installed"


def _path_key(path: str) -> str:
    return os.path.abspath(str(path))


def _audio_state(specs: dict[str, Any]) -> bool | None:
    value = specs.get("has_audio")
    return value if isinstance(value, bool) else None


def _inspect_once(
    paths: list[str],
    inspect: Callable[[str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Inspect each final file exactly once and normalize non-object results."""
    specs_by_path: dict[str, dict[str, Any]] = {}
    for path in paths:
        inspected = inspect(path)
        specs_by_path[_path_key(path)] = inspected if isinstance(inspected, dict) else {}
    return specs_by_path


def _patch_policy() -> None:
    import pipeline.publishable_reel_policy as policy

    if getattr(policy, _POLICY_FLAG, False):
        return
    original_record = policy.record_athlete_outcome
    original_mark_upload_result = policy.mark_upload_result

    def record_fail_closed(
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
        inspect = specs_getter or policy._default_specs
        snapshot = specs_by_path or _inspect_once(list(final_reels or []), inspect)
        row = original_record(
            sport=sport,
            athlete_label=athlete_label,
            final_reels=final_reels,
            events_by_reel=events_by_reel,
            flagged_paths=flagged_paths,
            variant_failures=variant_failures,
            specs_getter=specs_getter,
            specs_by_path=snapshot,
        )
        with policy._MANIFEST_LOCK:
            payload = policy._read_manifest()
            for manifest_row in payload.get("athletes", []) or []:
                if not isinstance(manifest_row, dict):
                    continue
                if manifest_row.get("athlete_key") != row.get("athlete_key"):
                    continue
                reasons = list(manifest_row.get("blocking_reasons") or [])
                for part in manifest_row.get("parts", []) or []:
                    if not isinstance(part, dict):
                        continue
                    local_path = str(part.get("local_path") or "")
                    specs = snapshot.get(_path_key(local_path), {}) or snapshot.get(local_path, {})
                    part["has_audio"] = _audio_state(specs)
                    part["qa_evidence_recorded"] = False
                    part["qa_verdict"] = None
                    part["qa_passed"] = False
                    issues = [
                        str(issue)
                        for issue in part.get("technical_issues", []) or []
                        if str(issue) != "final_qa_failed"
                    ]
                    if "missing_final_qa_evidence" not in issues:
                        issues.append("missing_final_qa_evidence")
                    part["technical_issues"] = sorted(set(issues))
                    part["render_ready"] = False
                    part["publishable"] = False
                    part.setdefault("upload_path_aliases", [])
                    reasons.append(
                        f"missing_final_qa_evidence:{Path(local_path).name}"
                    )
                manifest_row["blocking_reasons"] = sorted(set(reasons))
                policy._refresh_row_publishability(manifest_row)
                row = copy.deepcopy(manifest_row)
                break
            policy._recompute_summary(payload)
            policy._atomic_write(policy._manifest_path(), payload)
        return row

    def register_staged_upload_path(original_path: str, staged_path: str) -> bool:
        original_key = _path_key(original_path)
        staged_key = _path_key(staged_path)
        with policy._MANIFEST_LOCK:
            payload = policy._read_manifest()
            matched = False
            for manifest_row in payload.get("athletes", []) or []:
                if not isinstance(manifest_row, dict):
                    continue
                for part in manifest_row.get("parts", []) or []:
                    if not isinstance(part, dict):
                        continue
                    local_key = _path_key(str(part.get("local_path") or ""))
                    aliases = {
                        _path_key(str(alias))
                        for alias in part.get("upload_path_aliases", []) or []
                    }
                    if original_key not in {local_key, *aliases}:
                        continue
                    aliases.add(staged_key)
                    part["upload_path_aliases"] = sorted(aliases)
                    matched = True
                    break
            if matched:
                policy._atomic_write(policy._manifest_path(), payload)
            return matched

    def mark_upload_result(
        draft_path: str,
        draft_name: str,
        error: str | None = None,
        *,
        storage_object_id: str | None = None,
    ) -> bool:
        return original_mark_upload_result(
            draft_path,
            draft_name,
            error=error,
            storage_object_id=storage_object_id,
        )

    policy.record_athlete_outcome = record_fail_closed
    policy.register_staged_upload_path = register_staged_upload_path
    policy.mark_upload_result = mark_upload_result
    setattr(policy, _POLICY_FLAG, True)


def _patch_context_staging() -> None:
    try:
        import pipeline.context_qa_long_video as context
    except Exception:
        return
    if getattr(context, _CONTEXT_FLAG, False):
        return
    original_stage = context._stage_reel_candidate

    def stage_with_manifest_alias(
        reel_path: str,
        tmp_dir: str,
        index: int,
        draft_name: str,
    ) -> str | None:
        staged = original_stage(reel_path, tmp_dir, index, draft_name)
        if staged:
            import pipeline.publishable_reel_policy as policy

            if not policy.register_staged_upload_path(reel_path, staged):
                raise RuntimeError(
                    "staged long-video upload path could not be attached to the "
                    f"publishable manifest: {reel_path} -> {staged}"
                )
        return staged

    context._stage_reel_candidate = stage_with_manifest_alias
    setattr(context, _CONTEXT_FLAG, True)


def install() -> None:
    """Install fail-closed manifest and staging-path integrity only."""
    global _INSTALL_DONE
    if _INSTALL_DONE:
        return
    _patch_policy()
    _patch_context_staging()
    _INSTALL_DONE = True
