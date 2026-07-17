#!/usr/bin/env python3
"""Regression contract for coverage-first per-athlete performance reels."""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pipeline/performance_reel_policy.py"
sys.path.insert(0, str(ROOT))


def load_policy():
    spec = importlib.util.spec_from_file_location("performance_reel_policy_contract", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load performance_reel_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(index: int, start: float, end: float, score: int = 7, **extra):
    return {
        "event_id": f"wave-{index}",
        "type": "surf_ride",
        "sport": "surfing",
        "start": start,
        "end": end,
        "score": score,
        "description": f"complete readable wave {index}",
        "_src": "session.mp4",
        **extra,
    }


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise SystemExit(f"missing active function {name}")


def _assert_import_and_call(function: ast.FunctionDef, module: str, called_name: str) -> None:
    imports = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.ImportFrom) and node.module == module
    ]
    if not imports:
        raise SystemExit(f"{function.name} does not import {module}")
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == called_name
    ]
    if not calls:
        raise SystemExit(f"{function.name} does not call {called_name}()")


def _assert_module_level_call(tree: ast.Module, called_name: str) -> None:
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == called_name
        ):
            return
    raise SystemExit(f"module does not actively call {called_name}()")


def _exercise_install(policy: Any) -> None:
    """Install against stubs so incompatible monkeypatches fail the contract."""
    import pipeline

    module_names = [
        "pipeline.analyzer_score_guard",
        "pipeline.runtime_quality",
        "pipeline.stages",
        "pipeline.stages.analyzer",
        "pipeline.stages.feedback",
        "pipeline.stages.editor",
        "pipeline.final_duplicate_guard",
        "pipeline.qa_gate_policy",
        "pipeline.orchestrator",
    ]
    saved_modules = {name: sys.modules.get(name) for name in module_names}
    saved_attrs = {
        name: getattr(pipeline, name, None)
        for name in ("analyzer_score_guard", "runtime_quality", "qa_gate_policy")
    }

    analyzer_guard = types.ModuleType("pipeline.analyzer_score_guard")
    analyzer_guard.filter_events = lambda events, activity="": list(events)
    analyzer_guard.filter_session_result = lambda result: result
    analyzer_guard.filter_single_result = lambda result: result

    runtime_quality = types.ModuleType("pipeline.runtime_quality")
    runtime_quality._normalize_event_crop = lambda item: dict(item)
    runtime_quality._safe_remove = lambda path: None
    runtime_quality._score = lambda item: int(item.get("score", 0))
    runtime_quality._extract_identity_thumbnail = lambda *_args: None

    stages = types.ModuleType("pipeline.stages")
    stages.__path__ = []
    analyzer = types.ModuleType("pipeline.stages.analyzer")
    analyzer._IDENTITY_PROMPT = "base prompt"
    analyzer.get_negative_feedback_hint = lambda: "old"
    feedback = types.ModuleType("pipeline.stages.feedback")
    feedback.get_negative_feedback_hint = lambda: "old"
    editor = types.ModuleType("pipeline.stages.editor")
    editor.XFADE_DUR = 0.25
    editor._partition_events = lambda events, _slowmo, _max=85.0: [
        [{**item, "original_non_surf_partitioner": True} for item in events]
    ]
    stages.analyzer = analyzer
    stages.feedback = feedback
    stages.editor = editor

    duplicate_guard = types.ModuleType("pipeline.final_duplicate_guard")
    duplicate_guard.remove_duplicate_events = lambda events: list(events)

    qa_policy = types.ModuleType("pipeline.qa_gate_policy")
    qa_policy.build_final_qa_diagnostics = (
        lambda _qa, *, retry_count, reel_path="", was_flagged=False: (
            {"retry_count": retry_count},
            False,
        )
    )
    qa_policy._patch_orchestrator = lambda _orchestrator: None

    try:
        for module in (
            analyzer_guard,
            runtime_quality,
            stages,
            analyzer,
            feedback,
            editor,
            duplicate_guard,
            qa_policy,
        ):
            sys.modules[module.__name__] = module
        sys.modules.pop("pipeline.orchestrator", None)
        pipeline.analyzer_score_guard = analyzer_guard
        pipeline.runtime_quality = runtime_quality
        pipeline.qa_gate_policy = qa_policy

        policy.install()

        if "EVERY DISTINCT WAVE RIDE" not in analyzer._IDENTITY_PROMPT:
            raise SystemExit("policy install did not update the analyzer prompt")
        if feedback.get_negative_feedback_hint() != "":
            raise SystemExit("policy install did not disable button-taxonomy prompt injection")

        non_surf = {"type": "goal", "sport": "football", "start": 0, "end": 8, "score": 9}
        delegated = editor._partition_events([non_surf], False, 85.0)
        if not delegated[0][0].get("original_non_surf_partitioner"):
            raise SystemExit("installed policy did not delegate non-surf partitioning")

        surf_parts = editor._partition_events([event(30, 0, 18, 8)], False, 89.0)
        if surf_parts[0][0].get("performance_reel_contract") != "all_usable_waves_per_athlete_v1":
            raise SystemExit("installed policy did not activate surf performance packing")

        diagnostics, blocked = qa_policy.build_final_qa_diagnostics(
            {"verdict": "FAIL"},
            retry_count=0,
        )
        if not blocked or diagnostics.get("decision") != "blocked_review_required":
            raise SystemExit("installed policy did not block a final QA failure")
    finally:
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, value in saved_attrs.items():
            if value is None:
                try:
                    delattr(pipeline, name)
                except AttributeError:
                    pass
            else:
                setattr(pipeline, name, value)


def main() -> int:
    policy = load_policy()

    readable_low_score = event(1, 0, 12, score=4)
    failed_takeoff = event(
        2,
        20,
        23,
        score=4,
        ride_completed=False,
        hard_reject_reason="failed_takeoff",
        description="falls immediately during a failed takeoff",
    )
    high_score_failed_takeoff = event(
        3,
        30,
        34,
        score=8,
        ride_completed=False,
        hard_reject_reason="no_ride_established",
        description="misses the wave and never stands",
    )
    non_surf = {"type": "walk", "sport": "football", "score": 4, "start": 0, "end": 8}
    if not policy.keep_event_for_performance_reel(readable_low_score, "surfing"):
        raise SystemExit("readable low-score surf ride was incorrectly discarded")
    if policy.keep_event_for_performance_reel(failed_takeoff, "surfing"):
        raise SystemExit("explicit failed takeoff was incorrectly preserved")
    if policy.keep_event_for_performance_reel(high_score_failed_takeoff, "surfing"):
        raise SystemExit("high score bypassed explicit no-ride evidence")
    if policy.keep_event_for_performance_reel(non_surf, "football"):
        raise SystemExit("generic low-score non-surf event bypassed the existing quality floor")

    waves = [
        event(1, 0, 18, 8),
        event(2, 30, 48, 7),
        event(3, 60, 78, 9),
        event(4, 90, 108, 7),
        event(5, 120, 138, 8),
        event(6, 150, 168, 6),
    ]
    parts = policy.partition_complete_performance_reels(
        waves,
        slowmo_capable=False,
        target_max=89.0,
        xfade_dur=0.25,
    )
    flattened = [item for part in parts for item in part]
    ids = [item["event_id"] for item in flattened]
    if ids != [f"wave-{index}" for index in range(1, 7)]:
        raise SystemExit(f"waves were reordered, duplicated, or discarded: {ids}")
    if len(parts) != 2:
        raise SystemExit(f"six 18-second waves should split into two reels, got {len(parts)}")
    for part_index, part in enumerate(parts, start=1):
        estimated = float(part[0]["performance_reel_estimated_part_duration"])
        if estimated > 89.0:
            raise SystemExit(f"part {part_index} exceeds the safe budget: {estimated}")
        if any(item["performance_reel_part"] != part_index for item in part):
            raise SystemExit("part metadata does not match packing result")
        if any(item["performance_reel_total_wave_count"] != 6 for item in part):
            raise SystemExit("total wave coverage metadata is incomplete")

    try:
        policy.partition_complete_performance_reels(
            [event(99, 0, 95, 9)],
            slowmo_capable=False,
            target_max=89.0,
        )
    except policy.PerformanceReelPackingError as exc:
        if "performance_reel_packing_blocked" not in str(exc):
            raise SystemExit("impossible packing failed without an actionable reason") from exc
    else:
        raise SystemExit("a standalone ride longer than the reel ceiling was emitted")

    from pipeline.final_duplicate_guard import remove_duplicate_events

    duplicate_across_boundary = [
        event(10, 0, 44, 8, event_fingerprint="same-wave"),
        event(11, 50, 94, 7),
        event(12, 100, 144, 9, event_fingerprint="same-wave"),
    ]
    deduplicated = remove_duplicate_events(duplicate_across_boundary)
    duplicate_parts = policy.partition_complete_performance_reels(
        deduplicated,
        slowmo_capable=False,
        target_max=89.0,
    )
    duplicate_ids = [item["event_id"] for part in duplicate_parts for item in part]
    if len(duplicate_ids) != 2 or len(set(duplicate_ids)) != 2:
        raise SystemExit(f"duplicate wave crossed a reel boundary: {duplicate_ids}")

    defects = [
        {"type": "DEAD_TIME", "severity": "critical"},
        {"type": "LOW_QUALITY", "severity": "critical"},
        {"type": "BAD_FIRST_CLIP", "severity": "critical"},
        {"type": "IDENTITY_MISMATCH", "severity": "critical"},
        {"type": "PREMATURE_CUT", "severity": "critical"},
    ]
    filtered_types = {item["type"] for item in policy._filter_surf_qa_defects(defects)}
    if filtered_types != {"IDENTITY_MISMATCH", "PREMATURE_CUT"}:
        raise SystemExit(f"QA deletion policy retained the wrong defects: {filtered_types}")

    policy_source = POLICY_PATH.read_text(encoding="utf-8")
    run_tracked_source = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    bootstrap_source = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    sitecustomize_source = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    review = (ROOT / "mobile/src/app/(operator)/review.tsx").read_text(encoding="utf-8")

    policy_tree = ast.parse(policy_source)
    run_tracked_tree = ast.parse(run_tracked_source)
    bootstrap_tree = ast.parse(bootstrap_source)
    ast.parse(sitecustomize_source)

    required_policy_tokens = [
        "EVERY DISTINCT WAVE RIDE",
        "MAX_PERFORMANCE_REEL_SEC = 89.0",
        "PerformanceReelPackingError",
        "performance_reel_total_wave_count",
        "QA_FAIL: Reel did not pass final quality review.",
        "remove_duplicate_events(event_list)",
        "if not _surf_events(event_list)",
        "if surf_event and is_explicit_failed_takeoff",
    ]
    missing = [token for token in required_policy_tokens if token not in policy_source]
    if missing:
        raise SystemExit(f"performance policy is missing contract tokens: {missing}")

    for token in (
        "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
        "install_pre_orchestrator_patches()",
        "install_post_orchestrator_patches()",
    ):
        if token not in run_tracked_source:
            raise SystemExit(f"production runner missing canonical bootstrap token: {token}")
    if "_install_performance_reel_policy_runtime" in run_tracked_source:
        raise SystemExit("production runner reintroduced a divergent performance-policy installer")

    bootstrap_helper = _function(bootstrap_tree, "install_pre_orchestrator_patches")
    _assert_import_and_call(
        bootstrap_helper,
        "pipeline.performance_reel_policy",
        "install_performance_reel_policy",
    )
    if "pipeline.performance_reel_policy" in sitecustomize_source:
        raise SystemExit("required performance policy must not remain in fail-silent sitecustomize")

    forbidden_review_tokens = [
        "FEEDBACK_FLAGS",
        "DraftFeedbackResponse",
        "OperatorFeedbackEvent",
        "submitFlag",
        "Feedback recorded",
    ]
    present = [token for token in forbidden_review_tokens if token in review]
    if present:
        raise SystemExit(f"button-based feedback UI is still present: {present}")
    for required in [
        "Performance reels waiting for review",
        "QA passed · ready to review",
        "Send QA notes to re-edit",
    ]:
        if required not in review:
            raise SystemExit(f"review screen missing clear product status: {required}")

    if not isinstance(policy_tree, ast.Module):
        raise SystemExit("policy source did not parse as a module")
    _exercise_install(policy)

    print("Performance reel policy contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
