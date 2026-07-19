"""Require invocation-scoped final QA PASS evidence for every publishable reel.

`flagged_paths` alone is not positive QA evidence: when QA is disabled or a gate
returns without grading, the set can be empty. This patch records each real QA
result under the render-to-QA invocation token and consumes only that invocation's
evidence atomically before REVIEW upload.
"""
from __future__ import annotations

import copy
import os
import sys
import threading
from pathlib import Path
from typing import Any

_ANALYZER_FLAG = "_sportreel_publishable_qa_evidence_analyzer_installed"
_ORCHESTRATOR_FLAG = "_sportreel_publishable_qa_evidence_orchestrator_installed"
_RESULTS_LOCK = threading.RLock()
_QA_RESULTS_BY_INVOCATION: dict[str, dict[str, dict[str, Any]]] = {}


def _path_key(path: str) -> str:
    return os.path.abspath(str(path))


def _resolve_token(invocation_token: str | None = None) -> str:
    if invocation_token:
        return str(invocation_token)
    from pipeline.publishable_pending_scope import current_scope_token

    return str(current_scope_token(required=True))


def clear_recorded_qa(invocation_token: str | None = None) -> None:
    """Clear only one invocation's temporary QA evidence."""
    token = _resolve_token(invocation_token)
    with _RESULTS_LOCK:
        _QA_RESULTS_BY_INVOCATION.pop(token, None)


def record_qa_result(
    path: str,
    result: dict[str, Any],
    *,
    invocation_token: str | None = None,
) -> None:
    """Record one normalized QA result under its invocation and rendered path."""
    token = _resolve_token(invocation_token)
    with _RESULTS_LOCK:
        bucket = _QA_RESULTS_BY_INVOCATION.setdefault(token, {})
        bucket[_path_key(path)] = copy.deepcopy(result if isinstance(result, dict) else {})


def get_recorded_qa(
    path: str,
    *,
    invocation_token: str | None = None,
) -> dict[str, Any] | None:
    """Read one result without consuming evidence from another invocation."""
    token = _resolve_token(invocation_token)
    with _RESULTS_LOCK:
        result = _QA_RESULTS_BY_INVOCATION.get(token, {}).get(_path_key(path))
        return copy.deepcopy(result) if result is not None else None


def consume_recorded_qa(invocation_token: str) -> dict[str, dict[str, Any]]:
    """Atomically consume the complete QA result set for one invocation."""
    token = _resolve_token(invocation_token)
    with _RESULTS_LOCK:
        return copy.deepcopy(_QA_RESULTS_BY_INVOCATION.pop(token, {}))


def apply_final_qa_evidence(
    *,
    sport: str,
    athlete_label: str,
    final_reels: list[str],
    invocation_token: str | None = None,
) -> set[str]:
    """Persist positive QA evidence and return paths that must be review-blocked."""
    import pipeline.publishable_reel_policy as policy

    token = _resolve_token(invocation_token)
    invocation_results = consume_recorded_qa(token)
    final_keys = {_path_key(path): path for path in final_reels or []}
    blocked: set[str] = set()
    with policy._MANIFEST_LOCK:
        payload = policy._read_manifest()
        matched_row = False
        for row in payload.get("athletes", []) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("sport") or "sport") != str(sport or "sport"):
                continue
            if str(row.get("athlete_label") or "unknown athlete") != str(athlete_label or "unknown athlete"):
                continue
            parts = [part for part in row.get("parts", []) or [] if isinstance(part, dict)]
            if not any(_path_key(part.get("local_path") or "") in final_keys for part in parts):
                continue
            matched_row = True
            reasons = list(row.get("blocking_reasons") or [])
            for part in parts:
                local_path = str(part.get("local_path") or "")
                key = _path_key(local_path)
                if key not in final_keys:
                    continue
                result = invocation_results.get(key)
                verdict = str((result or {}).get("verdict") or "").upper()
                overall = str((result or {}).get("overall") or "")
                evidence_recorded = (
                    result is not None
                    and verdict in {"PASS", "FAIL"}
                    and overall.strip().lower() != "qa skipped"
                )
                qa_passed = evidence_recorded and verdict == "PASS"

                issues = [
                    str(issue)
                    for issue in part.get("technical_issues", []) or []
                    if str(issue) not in {"missing_final_qa_evidence", "final_qa_failed"}
                ]
                if not evidence_recorded:
                    issues.append("missing_final_qa_evidence")
                    reasons.append(f"missing_final_qa_evidence:{Path(local_path).name}")
                    blocked.add(final_keys[key])
                elif not qa_passed:
                    issues.append("final_qa_failed")
                    reasons.append(f"final_qa_failed:{Path(local_path).name}")
                    blocked.add(final_keys[key])

                part["qa_invocation_token"] = token
                part["qa_evidence_recorded"] = evidence_recorded
                part["qa_verdict"] = verdict or None
                part["qa_engagement_score"] = (result or {}).get("engagement_score")
                part["qa_overall"] = overall or None
                part["qa_defects"] = copy.deepcopy((result or {}).get("defects") or [])
                part["qa_passed"] = qa_passed
                part["technical_issues"] = sorted(set(issues))
                part["render_ready"] = qa_passed and not part["technical_issues"]

            row["blocking_reasons"] = sorted(set(reasons))
            policy._refresh_row_publishability(row)
            break

        if not matched_row and final_reels:
            raise RuntimeError(
                "publishable QA evidence could not find the athlete manifest row "
                f"for {athlete_label!r} ({sport!r})"
            )
        policy._recompute_summary(payload)
        policy._atomic_write(policy._manifest_path(), payload)
    return blocked


def _patch_analyzer() -> None:
    from pipeline.stages import analyzer

    if getattr(analyzer, _ANALYZER_FLAG, False):
        return
    original_qa = analyzer.qa_check_reel

    def qa_with_evidence(reel_path: str, *args, **kwargs):
        result = original_qa(reel_path, *args, **kwargs)
        record_qa_result(reel_path, result)
        return result

    analyzer.qa_check_reel = qa_with_evidence
    setattr(analyzer, _ANALYZER_FLAG, True)


def _patch_orchestrator() -> None:
    import pipeline.qa_gate_policy as qa_policy

    original_patch_orchestrator = qa_policy._patch_orchestrator

    def patch_orchestrator(orchestrator: Any) -> None:
        original_patch_orchestrator(orchestrator)
        if getattr(orchestrator, _ORCHESTRATOR_FLAG, False):
            return
        original_gate = orchestrator._qa_gate

        def gate_with_required_evidence(reels, events_out, sport, athlete_label, recompile):
            from pipeline.publishable_pending_scope import activate_next_scope, release_scope

            token = activate_next_scope(sport, athlete_label)
            clear_recorded_qa(token)
            try:
                final_reels, events_by_reel, flagged = original_gate(
                    reels,
                    events_out,
                    sport,
                    athlete_label,
                    recompile,
                )
                evidence_blocked = apply_final_qa_evidence(
                    sport=sport,
                    athlete_label=athlete_label,
                    final_reels=list(final_reels or []),
                    invocation_token=token,
                )
                return final_reels, events_by_reel, set(flagged or set()) | evidence_blocked
            finally:
                clear_recorded_qa(token)
                release_scope(token)

        orchestrator._qa_gate = gate_with_required_evidence
        setattr(orchestrator, _ORCHESTRATOR_FLAG, True)

    qa_policy._patch_orchestrator = patch_orchestrator
    existing = sys.modules.get("pipeline.orchestrator")
    if existing is not None:
        patch_orchestrator(existing)


def install() -> None:
    """Install invocation-scoped QA evidence and final product-integrity patches."""
    from pipeline.publishable_pending_scope import install as install_pending_scope

    install_pending_scope()
    _patch_analyzer()
    _patch_orchestrator()
    from pipeline.complete_action_window_policy import install as install_complete_action
    from pipeline.primary_actor_parent_identity import install as install_parent_identity
    from pipeline.publishable_runtime_integrity import install as install_integrity
    from pipeline.silent_qa_policy import install as install_silent_qa

    install_parent_identity()
    install_silent_qa()
    install_complete_action()
    install_integrity()
