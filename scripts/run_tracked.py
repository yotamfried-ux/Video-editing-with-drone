"""Tracked Phase 1 entry point for GitHub Actions."""

import json
import os
import sys
from pathlib import Path

# When executed as `python scripts/run_tracked.py`, Python puts `scripts/` on
# sys.path instead of the repository root. Add the root so top-level packages
# such as `integrations` and `pipeline` import reliably in GitHub Actions.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.run_status import mark_run, mark_terminal_run


_NO_DRAFTS_ERROR = "Pipeline completed without REVIEW drafts."
_produced_review_drafts = False
_last_observed_stage = "starting"
_last_observed_progress = 0.01
_last_observed_meta: dict = {}


def _install_storage_backend_alias() -> None:
    """Route legacy integrations.drive imports through storage.py for non-Drive backends."""
    backend = os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"
    if backend == "drive":
        return
    import integrations.storage as storage
    sys.modules["integrations.drive"] = storage


def _install_status_mirror() -> None:
    """Mirror singleton live progress into the active durable run row."""
    try:
        import integrations.supabase_uploader as status_writer
    except Exception:
        return

    original = status_writer.write_pipeline_status

    def tracked_write_pipeline_status(stage: str, progress: float, **meta) -> None:
        global _produced_review_drafts, _last_observed_stage, _last_observed_progress, _last_observed_meta
        original(stage, progress, **meta)
        _last_observed_stage = stage
        _last_observed_progress = progress
        _last_observed_meta = dict(meta)
        mark_run(stage=stage, progress=progress, meta=meta)
        if stage == "done" and int(meta.get("drafts_created") or 0) > 0:
            _produced_review_drafts = True

    status_writer.write_pipeline_status = tracked_write_pipeline_status


def _install_perception_runtime() -> None:
    from pipeline.perception.runtime import install
    install()


def _install_pipeline_quality_runtime() -> None:
    from pipeline.runtime_quality import install
    install()


def _install_selector_candidate_runtime() -> None:
    from pipeline.selector_candidate_runtime import install
    install()


def _install_teaser_policy_runtime() -> None:
    from pipeline.teaser_policy_runtime import install
    install()


def _install_identity_failsafe_runtime() -> None:
    from pipeline.identity_failsafe import install
    install()


def _install_cross_source_dedup_runtime() -> None:
    from pipeline.cross_source_dedup import install
    install()


def _install_context_runtime() -> None:
    from pipeline.context_qa_long_video import install
    install()


def _install_draft_diagnostics_runtime() -> None:
    from pipeline.draft_diagnostics import install
    install()


def _install_candidate_ledger_runtime() -> None:
    from pipeline.candidate_ledger import install
    install()


def _install_athlete_canonicalization_runtime() -> None:
    from pipeline.athlete_canonicalization import install
    install()


def _selection_filter_path() -> Path:
    try:
        import config
        return Path(config.TMP_DIR) / "selection_filter_events.json"
    except Exception:
        return Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "selection_filter_events.json"


def _no_reviewable_drafts_meta() -> dict | None:
    """Return metadata when zero drafts is a valid diagnostic outcome.

    A run with candidates where every candidate was rejected by pre-render gates
    should not fail the GitHub workflow. It should complete successfully with a
    terminal status that tells the operator there were no reviewable drafts and
    points to the diagnostics artifact for the exact reasons.
    """
    path = _selection_filter_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    records = [item for item in payload.get("records", []) if isinstance(item, dict)]
    if not records:
        return None
    selected_for_render = sum(1 for item in records if item.get("selected_for_render"))
    discarded = sum(1 for item in records if item.get("discarded"))
    clean_subwindow_rescue_count = int(payload.get("clean_subwindow_rescue_count") or 0)
    if selected_for_render > 0:
        # If candidates reached render but no drafts were uploaded, keep failing:
        # that is likely a render/upload bug, not a no-clean-window result.
        return None
    return {
        "error_code": "no_reviewable_drafts",
        "no_drafts_reason": "all_candidates_rejected_before_render",
        "selection_filter_record_count": len(records),
        "selection_filter_discarded_count": discarded,
        "selection_filter_selected_for_render_count": selected_for_render,
        "clean_subwindow_rescue_count": clean_subwindow_rescue_count,
        "selection_filter_events_path": str(path),
        "last_observed_stage": _last_observed_stage,
        "last_observed_progress": _last_observed_progress,
        "last_observed_meta": _last_observed_meta,
    }


def _no_drafts_failure() -> tuple[str, str, dict]:
    upload_error = _last_observed_meta.get("upload_error")
    if upload_error:
        reason = "all_draft_uploads_failed"
        error = f"All draft uploads failed: {upload_error}"
    elif _last_observed_stage == "qa":
        reason = "all_draft_uploads_failed"
        error = "All draft uploads failed after QA; no REVIEW drafts were created."
    else:
        reason = f"no_drafts_after_{_last_observed_stage}"
        error = f"{_NO_DRAFTS_ERROR} Last observed stage: {_last_observed_stage}."
    meta = {
        "error_code": reason,
        "no_drafts_reason": reason,
        "last_observed_stage": _last_observed_stage,
        "last_observed_progress": _last_observed_progress,
        "last_observed_meta": _last_observed_meta,
    }
    if upload_error:
        meta["upload_error"] = upload_error
    return reason, error, meta


mark_run(status="running", stage="starting", progress=0.01)
_install_status_mirror()
_install_storage_backend_alias()
_install_perception_runtime()
_install_pipeline_quality_runtime()
_install_selector_candidate_runtime()
_install_teaser_policy_runtime()
_install_identity_failsafe_runtime()
_install_cross_source_dedup_runtime()
_install_context_runtime()
_install_draft_diagnostics_runtime()
_install_candidate_ledger_runtime()
_install_athlete_canonicalization_runtime()

import pipeline.orchestrator as _orchestrator
from pipeline.orchestrator import main

if __name__ == "__main__":
    from integrations.observability import init_sentry
    init_sentry()
    try:
        main()
    except Exception as exc:
        mark_terminal_run(status="failed", stage="failed", error=str(exc))
        raise

    if _orchestrator.no_input:
        mark_terminal_run(status="no_input", stage="no_input", progress=1.0)
    elif _produced_review_drafts:
        mark_terminal_run(status="succeeded", stage="finished", progress=1.0)
    else:
        no_reviewable = _no_reviewable_drafts_meta()
        if no_reviewable:
            mark_terminal_run(status="no_reviewable_drafts", stage="no_reviewable_drafts", progress=1.0, **no_reviewable)
            print("ℹ️ No REVIEW drafts produced because all candidates were rejected before render; diagnostics artifact contains selection_filter_events.json")
        else:
            stage, error, meta = _no_drafts_failure()
            mark_terminal_run(status="failed", stage=stage, error=error, **meta)
            sys.exit(1)
