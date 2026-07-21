"""Single source of truth for installing SportReel's runtime quality/safety patches.

Every real pipeline entrypoint must apply the same set of monkey-patches so
behavior does not silently diverge by entrypoint. Historically each entrypoint
(``scripts/run_tracked.py`` for GitHub Actions, ``run.py``/``run_surf.py`` for
manual local runs, ``scripts/reset_and_rerun.py``'s inline pipeline mode)
grew its own partial list, so a fix landed in one entrypoint (for example
``pipeline.identity_failsafe`` or ``pipeline.r2_batch_scope``) could be
silently inactive in another. This module is the single ordered list; every
entrypoint should call it instead of hand-rolling its own subset.

Order matters: several patches wrap the same target function (for example
``pipeline.stages.analyzer.analyze_session`` or ``pipeline.stages.editor.
cut_clip``), so whichever installs last becomes the outermost wrapper. The
order below reproduces the composite order that already runs in the GitHub
Actions production path today (``scripts/sitecustomize.py`` +
``scripts/usercustomize.py``, auto-imported by Python before
``scripts/run_tracked.py``'s own body executes, followed by that body's
explicit installs). Do not reorder without re-verifying that dependent
comments (for example ``raw_timestamp_recovery`` must precede
``chunk_timeline_runtime``/``selector_candidate_runtime``) still hold.

Every patch module's ``install()`` is idempotent (guarded by a flag on the
module it patches), so calling this from multiple places — once via the
auto-imported ``scripts/sitecustomize.py``, again here — is safe and cheap.
"""

from __future__ import annotations

import os
import sys


def _install_storage_backend_alias() -> None:
    """Route legacy integrations.drive imports through storage.py for non-Drive backends."""
    backend = os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"
    if backend == "drive":
        return
    import integrations.storage as storage

    sys.modules["integrations.drive"] = storage


def _install_r2_batch_scope() -> None:
    """Scope R2 raw-video listing to a batch prefix when a batch id is set.

    Previously only installed by the root ``sitecustomize.py``, which never
    actually runs for ``python scripts/run_tracked.py`` (Python's automatic
    ``sitecustomize`` import only sees the script's own directory --
    ``scripts/`` -- not the repository root), so this was silently inactive
    in the real GitHub Actions production run despite being wired elsewhere.
    """
    backend = os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive"
    batch_id = (os.getenv("RAW_BATCH_ID") or os.getenv("BATCH_ID") or "").strip()
    if backend != "r2" or not batch_id:
        return
    from pipeline.r2_batch_scope import install

    install()


def install_pre_orchestrator_patches() -> None:
    """Install every patch that must be active before `pipeline.orchestrator` is imported."""
    _install_storage_backend_alias()
    _install_r2_batch_scope()

    from pipeline.perception.runtime import install as install_perception

    install_perception()

    # Perception is a production requirement, not an opt-in enhancement. Install
    # immediately after the runtime adapter so later analyzer/crop/identity layers
    # can rely on detector/tracker evidence and fail closed when it is missing.
    from pipeline.required_perception_policy import install as install_required_perception

    install_required_perception()

    # Must wrap analyzer._parse_session before chunk/selector runtimes capture
    # it, otherwise MM.SS values are discarded as sub-second fragments first.
    from pipeline.raw_timestamp_recovery import install as install_raw_timestamp_recovery

    install_raw_timestamp_recovery()

    from pipeline.analyzer_score_guard import install as install_analyzer_score_guard

    install_analyzer_score_guard()

    from pipeline.chunk_timeline_runtime import install as install_chunk_timeline_runtime

    install_chunk_timeline_runtime()

    from pipeline.single_athlete_selection_policy import install as install_single_athlete_policy

    install_single_athlete_policy()

    from pipeline.window_policy import install as install_window_policy

    install_window_policy()

    from pipeline.cut_window_guard import install as install_cut_window_guard

    install_cut_window_guard()

    from pipeline.narrative_policy import install as install_narrative_policy

    install_narrative_policy()

    from pipeline.qa_gate_policy import install as install_qa_gate_policy

    install_qa_gate_policy()

    from pipeline.draft_diagnostics import install as install_draft_diagnostics

    install_draft_diagnostics()

    from pipeline.candidate_ledger import install as install_candidate_ledger

    install_candidate_ledger()

    from pipeline.editorial_value_ranker import install as install_editorial_value_ranker

    install_editorial_value_ranker()

    from pipeline.athlete_canonicalization import install as install_athlete_canonicalization

    install_athlete_canonicalization()

    from pipeline.real_identity_gate import install as install_real_identity_gate

    install_real_identity_gate()

    from pipeline.final_duplicate_guard import install as install_final_duplicate_guard

    install_final_duplicate_guard()

    from pipeline.context_qa_gate import install as install_context_qa_gate

    install_context_qa_gate()

    from pipeline.context_qa_long_video import install as install_context_qa_long_video

    install_context_qa_long_video()

    from pipeline.source_evidence_patch import install as install_source_evidence_patch

    install_source_evidence_patch()

    from pipeline.surf_ride_gate import install as install_surf_ride_gate

    install_surf_ride_gate()

    from pipeline.runtime_quality import install as install_runtime_quality

    install_runtime_quality()

    from pipeline.performance_reel_policy import install as install_performance_reel_policy

    install_performance_reel_policy()

    from pipeline.publishable_reel_policy import install as install_publishable_reel_policy

    install_publishable_reel_policy()

    # The product intentionally outputs video without audio. Install after the
    # publishable policy so its canonicalization/spec checks are replaced by the
    # silent contract before the orchestrator captures the editor functions.
    from pipeline.silent_output_policy import install as install_silent_output_policy

    install_silent_output_policy()

    from pipeline.publishable_qa_evidence import install as install_publishable_qa_evidence

    install_publishable_qa_evidence()

    # Install last among editor policies: this replaces artistic crop/zoom defaults
    # with a 4K/30 contain-first renderer and adds strict output-spec gates.
    from pipeline.quality_preserving_framing import install as install_quality_framing

    install_quality_framing()

    from pipeline.selector_candidate_runtime import install as install_selector_candidate_runtime

    install_selector_candidate_runtime()

    from pipeline.teaser_policy_runtime import install as install_teaser_policy_runtime

    install_teaser_policy_runtime()

    from pipeline.identity_failsafe import install as install_identity_failsafe

    install_identity_failsafe()

    from pipeline.cross_source_dedup import install as install_cross_source_dedup

    install_cross_source_dedup()


def install_post_orchestrator_patches() -> None:
    """Install patches that wrap `pipeline.orchestrator` functions directly.

    Call only after `import pipeline.orchestrator` has already executed.
    """
    from pipeline.qa_reedit_window_contract import install as install_qa_reedit_window_contract

    install_qa_reedit_window_contract()

    from pipeline.draft_identity_metadata import install as install_draft_identity_metadata

    install_draft_identity_metadata()
