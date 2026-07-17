#!/usr/bin/env python3
"""Contract: every real pipeline entrypoint installs the full patch stack."""
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
        _object_to_video=lambda obj: {
            "key": obj["Key"],
            "id": obj["Key"],
            "name": obj["Key"].split("/")[-1],
        },
        _sportreel_r2_batch_scope_installed=False,
        moves=moves,
        listed=listed,
    )
    sys.modules["integrations.r2_storage"] = module
    return module


def run_r2_batch_scope_via_bootstrap() -> None:
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

    for text in [
        bootstrap,
        run_tracked,
        run_py,
        run_surf,
        reset_and_rerun,
        read("scripts/test_bootstrap_parity_contract.py"),
    ]:
        ast.parse(text)

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
        "pipeline.editorial_value_ranker",
        "pipeline.athlete_canonicalization",
        "pipeline.real_identity_gate",
        "pipeline.final_duplicate_guard",
        "pipeline.context_qa_gate",
        "pipeline.context_qa_long_video",
        "pipeline.source_evidence_patch",
        "pipeline.surf_ride_gate",
        "pipeline.runtime_quality",
        "pipeline.performance_reel_policy",
        "pipeline.publishable_reel_policy",
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

    pre_start = bootstrap.index("def install_pre_orchestrator_patches")
    post_start = bootstrap.index("def install_post_orchestrator_patches")
    if not pre_start < post_start:
        raise SystemExit(
            "pipeline/bootstrap.py: install_pre_orchestrator_patches must be defined before install_post_orchestrator_patches"
        )
    pre_body = bootstrap[pre_start:post_start]
    post_body = bootstrap[post_start:]
    require_order(
        "pipeline/bootstrap.py pre-orchestrator patch order",
        pre_body,
        canonical_pre_orchestrator_patches,
    )
    require_order(
        "pipeline/bootstrap.py post-orchestrator patch order",
        post_body,
        canonical_post_orchestrator_patches,
    )
    require_order(
        "pipeline/bootstrap.py timestamp recovery must precede chunk/selector capture",
        pre_body,
        [
            "pipeline.raw_timestamp_recovery",
            "pipeline.chunk_timeline_runtime",
            "pipeline.selector_candidate_runtime",
        ],
    )
    require_order(
        "pipeline/bootstrap.py product policy layering",
        pre_body,
        [
            "pipeline.performance_reel_policy",
            "pipeline.publishable_reel_policy",
            "pipeline.selector_candidate_runtime",
        ],
    )

    require(
        "scripts/run_tracked.py installs required production policies",
        run_tracked,
        [
            "def _install_r2_batch_scope() -> None:",
            "from pipeline.r2_batch_scope import install",
            "def _install_performance_reel_policy_runtime() -> None:",
            "from pipeline.performance_reel_policy import install",
            "def _install_publishable_reel_policy_runtime() -> None:",
            "from pipeline.publishable_reel_policy import install",
            "_install_pipeline_quality_runtime()\n_install_performance_reel_policy_runtime()\n_install_publishable_reel_policy_runtime()\n_install_raw_timestamp_recovery()",
            "_install_storage_backend_alias()\n_install_r2_batch_scope()\n_install_perception_runtime()",
        ],
    )

    require(
        "run.py uses shared bootstrap",
        run_py,
        [
            "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
            "install_pre_orchestrator_patches()",
            "install_post_orchestrator_patches()",
        ],
    )
    require(
        "run_surf.py uses shared bootstrap",
        run_surf,
        [
            "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
            "install_pre_orchestrator_patches()",
            "install_post_orchestrator_patches()",
            "enable_surf_editor_policy()",
        ],
    )
    require(
        "scripts/reset_and_rerun.py inline pipeline path uses shared bootstrap",
        reset_and_rerun,
        [
            "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
            "install_pre_orchestrator_patches()",
            "install_post_orchestrator_patches()",
        ],
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
