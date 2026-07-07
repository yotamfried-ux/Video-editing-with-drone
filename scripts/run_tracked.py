"""Tracked Phase 1 entry point for GitHub Actions."""

import os
import sys

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
    """Route legacy integrations.drive imports through storage.py for non-Drive backends.

    pipeline.orchestrator still imports the historical Drive adapter. For the
    GitHub Actions entry point we can safely alias that module to the storage
    router when STORAGE_BACKEND=r2, while leaving default Drive behavior exactly
    unchanged.
    """
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
    """Attach detector/tracker sidecar evidence before crop/identity hardening."""
    from pipeline.perception.runtime import install
    install()


def _install_pipeline_quality_runtime() -> None:
    """Harden analyzer output before orchestrator imports analyze_session."""
    from pipeline.runtime_quality import install
    install()


def _install_selector_candidate_runtime() -> None:
    """Emit selected/discarded selector candidates from analyzer parsing."""
    from pipeline.selector_candidate_runtime import install
    install()


def _install_teaser_policy_runtime() -> None:
    """Disable cold-open teaser clips so REVIEW drafts do not repeat moments."""
    from pipeline.teaser_policy_runtime import install
    install()


def _install_identity_failsafe_runtime() -> None:
    """Harden identity clustering before orchestrator imports cluster_clips."""
    from pipeline.identity_failsafe import install
    install()


def _install_cross_source_dedup_runtime() -> None:
    """Filter repeated cross-source moments before editor partitioning."""
    from pipeline.cross_source_dedup import install
    install()


def _install_draft_diagnostics_runtime() -> None:
    """Ensure draft diagnostics are installed in the tracked pipeline entrypoint."""
    from pipeline.draft_diagnostics import install
    install()


def _install_candidate_ledger_runtime() -> None:
    """Ensure candidate decision ledger patches diagnostics before metadata save."""
    from pipeline.candidate_ledger import install
    install()


def _install_athlete_canonicalization_runtime() -> None:
    """Assign stable athlete IDs before orchestrator binds analyzer/identity functions."""
    from pipeline.athlete_canonicalization import install
    install()


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
        stage, error, meta = _no_drafts_failure()
        mark_terminal_run(status="failed", stage=stage, error=error, **meta)
        sys.exit(1)
