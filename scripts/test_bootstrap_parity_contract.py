#!/usr/bin/env python3
"""Contract: every real pipeline entrypoint installs the full patch stack.

Regression target: ``pipeline.r2_batch_scope`` (batch/session isolation) was
only ever installed by the root ``sitecustomize.py``, which Python's
automatic ``sitecustomize`` import never actually loads for
``python scripts/run_tracked.py`` (the script's own directory, ``scripts/``,
is what lands on ``sys.path``, not the repository root) -- so batch scoping
was silently inactive in the real GitHub Actions production run despite
being wired elsewhere and reported as closed. ``scripts/run_tracked.py`` now
installs it directly (``_install_r2_batch_scope``, mirroring the root
sitecustomize logic), and this contract proves that.

The local/manual entrypoints ``run.py`` and ``run_surf.py`` -- and
``scripts/reset_and_rerun.py``'s inline pipeline mode -- had an even bigger
gap: they called almost none of the quality/safety patches at all (only
``scripts/run_tracked.py``'s own hand-rolled list had them, and that list is
intentionally left alone here since 11 pre-existing contract tests pin its
exact source text/order). ``pipeline/bootstrap.py`` is the new shared,
canonically-ordered install list for those three entrypoints. This contract
proves each of them calls it (source inspection, since importing them
exercises heavy ML dependencies not available in this test environment) and
exercises the previously-missing ``r2_batch_scope`` conditional install
directly.
"""
from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def forbid(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} must not reintroduce duplicated bootstrap tokens: {present}")


def require_order(label: str, text: str, tokens: list[str]) -> None:
    """Assert each token's first occurrence appears strictly after the previous one's.

    Presence-only checks (``require``) would still pass if a future edit swapped
    two install calls -- exactly the class of silent regression this module's
    docstring warns about (whichever patch installs last becomes the outermost
    wrapper around a shared target function).
    """
    positions = [(token, text.index(token)) for token in tokens]
    for (first, first_pos), (second, second_pos) in zip(positions, positions[1:]):
        if first_pos > second_pos:
            raise SystemExit(f"{label}: {first!r} must precede {second!r}, but does not")


def fake_r2() -> types.SimpleNamespace:
    moves: list[tuple[str, str]] = []
    listed: list[str] = []

    def list_objects(prefix: str) -> list[dict]:
        listed.append(prefix)
        return [{"Key": f"{prefix}clip.mp4"}]

    def move_object(source: str, dest: str) -> None:
        moves.append((source, dest))

    module = types.SimpleNamespace(
        RAW_PREFIX="raw/",
        PROCESSED_PREFIX="processed/",
        list_objects=list_objects,
        move_object=move_object,
        _is_video_key=lambda key: key.endswith(".mp4"),
        _object_to_video=lambda obj: {"key": obj["Key"], "id": obj["Key"], "name": obj["Key"].split("/")[-1]},
        _sportreel_r2_batch_scope_installed=False,
        moves=moves,
        listed=listed,
    )
    sys.modules["integrations.r2_storage"] = module
    return module


def run_r2_batch_scope_via_bootstrap() -> None:
    """The concrete bug: prove pipeline.bootstrap actually installs batch scoping."""
    os.environ["STORAGE_BACKEND"] = "r2"
    os.environ["RAW_BATCH_ID"] = "session two"
    sys.modules.pop("pipeline.bootstrap", None)
    module = fake_r2()
    import pipeline.bootstrap as bootstrap

    bootstrap._install_r2_batch_scope()
    videos = module.get_new_videos()
    if module.listed != ["raw/session_two/"]:
        raise SystemExit(f"bootstrap did not scope R2 listing to the batch id, got {module.listed}")
    if [video["key"] for video in videos] != ["raw/session_two/clip.mp4"]:
        raise SystemExit("bootstrap did not install scoped get_new_videos")

    # Without a batch id, scoping must not install (matches prior behavior).
    del os.environ["RAW_BATCH_ID"]
    sys.modules.pop("pipeline.bootstrap", None)
    module2 = fake_r2()
    import pipeline.bootstrap as bootstrap2

    bootstrap2._install_r2_batch_scope()
    if getattr(module2, "_sportreel_r2_batch_scope_installed", False):
        raise SystemExit("bootstrap must not install batch scoping without a batch id")


def main() -> int:
    bootstrap = read("pipeline/bootstrap.py")
    run_tracked = read("scripts/run_tracked.py")
    run_py = read("run.py")
    run_surf = read("run_surf.py")
    reset_and_rerun = read("scripts/reset_and_rerun.py")

    for text in [bootstrap, run_tracked, run_py, run_surf, reset_and_rerun, read("scripts/test_bootstrap_parity_contract.py")]:
        ast.parse(text)

    # Order matters here: whichever patch installs last becomes the outermost
    # wrapper around any target function it shares with an earlier patch (see
    # pipeline/bootstrap.py's module docstring). Keep this as one list so the
    # presence check and the order check can never drift apart.
    canonical_pre_orchestrator_patches = [
        "pipeline.perception.runtime",
        "pipeline.raw_timestamp_recovery",
        "pipeline.analyzer_score_guard",
        "pipeline.chunk_timeline_runtime",
        "pipeline.single_athlete_selection_policy",
        "pipeline.window_policy",
        "pipeline.cut_window_guard",
        "pipeline.narrative_policy",
        "pipeline.qa_gate_policy",
        "pipeline.draft_diagnostics",
        "pipeline.candidate_ledger",
        "pipeline.athlete_canonicalization",
        "pipeline.real_identity_gate",
        "pipeline.final_duplicate_guard",
        "pipeline.context_qa_gate",
        "pipeline.context_qa_long_video",
        "pipeline.source_evidence_patch",
        "pipeline.surf_ride_gate",
        "pipeline.runtime_quality",
        "pipeline.selector_candidate_runtime",
        "pipeline.teaser_policy_runtime",
        "pipeline.identity_failsafe",
        "pipeline.cross_source_dedup",
    ]
    canonical_post_orchestrator_patches = [
        "pipeline.qa_reedit_window_contract",
        "pipeline.draft_identity_metadata",
    ]

    require(
        "pipeline/bootstrap.py canonical patch list",
        bootstrap,
        [
            "def install_pre_orchestrator_patches",
            "def install_post_orchestrator_patches",
            "_install_storage_backend_alias",
            "_install_r2_batch_scope",
            *canonical_pre_orchestrator_patches,
            *canonical_post_orchestrator_patches,
        ],
    )

    # Scope the order checks to each function's own body -- the module
    # docstring above them names several patch modules as prose examples
    # (e.g. "pipeline.identity_failsafe"), which would otherwise be mistaken
    # for the real (later) install call and produce false-positive ordering
    # violations.
    pre_patches_start = bootstrap.index("def install_pre_orchestrator_patches")
    post_patches_start = bootstrap.index("def install_post_orchestrator_patches")
    if not pre_patches_start < post_patches_start:
        raise SystemExit("pipeline/bootstrap.py: install_pre_orchestrator_patches must be defined before install_post_orchestrator_patches")
    pre_patches_body = bootstrap[pre_patches_start:post_patches_start]
    post_patches_body = bootstrap[post_patches_start:]

    require_order(
        "pipeline/bootstrap.py pre-orchestrator patch order",
        pre_patches_body,
        canonical_pre_orchestrator_patches,
    )
    require_order(
        "pipeline/bootstrap.py post-orchestrator patch order",
        post_patches_body,
        canonical_post_orchestrator_patches,
    )
    # raw_timestamp_recovery must wrap analyzer._parse_session before the
    # chunk/selector runtimes capture it (see pipeline/raw_timestamp_recovery.py
    # and pipeline/selector_candidate_runtime.py's own comments to this effect).
    require_order(
        "pipeline/bootstrap.py timestamp recovery must precede chunk/selector capture",
        pre_patches_body,
        ["pipeline.raw_timestamp_recovery", "pipeline.chunk_timeline_runtime", "pipeline.selector_candidate_runtime"],
    )

    require(
        "scripts/run_tracked.py installs r2 batch scope",
        run_tracked,
        [
            "def _install_r2_batch_scope() -> None:",
            "from pipeline.r2_batch_scope import install",
            "_install_storage_backend_alias()\n_install_r2_batch_scope()\n_install_perception_runtime()",
        ],
    )

    require(
        "run.py uses shared bootstrap",
        run_py,
        ["from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches", "install_pre_orchestrator_patches()", "install_post_orchestrator_patches()"],
    )

    require(
        "run_surf.py uses shared bootstrap",
        run_surf,
        ["from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches", "install_pre_orchestrator_patches()", "install_post_orchestrator_patches()", "enable_surf_editor_policy()"],
    )

    require(
        "scripts/reset_and_rerun.py inline pipeline path uses shared bootstrap",
        reset_and_rerun,
        ["from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches", "install_pre_orchestrator_patches()", "install_post_orchestrator_patches()"],
    )
    forbid(
        "scripts/reset_and_rerun.py must not keep the old duplicated alias helper",
        reset_and_rerun,
        ["_install_storage_backend_alias_for_inline_pipeline"],
    )

    run_r2_batch_scope_via_bootstrap()
    print("Bootstrap parity contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
