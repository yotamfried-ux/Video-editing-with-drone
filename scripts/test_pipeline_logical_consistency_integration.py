#!/usr/bin/env python3
"""Cross-layer SportReel contract harness.

This is intentionally one integration invocation rather than a collection of source
presence checks. It drives the same business concepts through the real policy helpers
and then verifies the authoritative API/status boundaries that complete the run.

Official engineering basis:
  docs/audit/cross-layer-logical-consistency-test-basis-20260717.md
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def scenario(name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        print(f"PASS {name}")
    except Exception as exc:  # noqa: BLE001 - aggregate every contract violation
        FAILURES.append(f"{name}: {exc}")
        print(f"FAIL {name}: {exc}")


def assert_official_basis() -> None:
    path = ROOT / "docs/audit/cross-layer-logical-consistency-test-basis-20260717.md"
    text = path.read_text(encoding="utf-8")
    for domain in (
        "docs.aws.amazon.com",
        "cloud.google.com",
        "learn.microsoft.com",
        "docs.github.com",
    ):
        if domain not in text:
            raise AssertionError(f"official reference missing: {domain}")


def _fake_install_module(name: str, calls: list[str]) -> None:
    module = types.ModuleType(name)

    def install() -> None:
        calls.append(name)

    module.install = install  # type: ignore[attr-defined]
    sys.modules[name] = module


def assert_canonical_production_bootstrap() -> None:
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    usercustomize = (ROOT / "scripts/usercustomize.py").read_text(encoding="utf-8")
    required = (
        "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
        "install_pre_orchestrator_patches()",
        "install_post_orchestrator_patches()",
    )
    missing = [token for token in required if token not in run_tracked]
    if missing:
        raise AssertionError(f"production entrypoint does not use canonical bootstrap: {missing}")
    if "def _install_performance_reel_policy_runtime" in run_tracked:
        raise AssertionError("production entrypoint still owns a divergent manual patch stack")
    if "except Exception" in usercustomize or "from pipeline." in usercustomize:
        raise AssertionError("usercustomize still installs product-critical patches fail-silently")
    if "from pipeline." in sitecustomize or "except Exception" in sitecustomize:
        raise AssertionError("sitecustomize still installs product-critical patches fail-silently")

    import pipeline.bootstrap as bootstrap

    expected_pre = [
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
        "pipeline.silent_output_policy",
        "pipeline.publishable_qa_evidence",
        "pipeline.selector_candidate_runtime",
        "pipeline.teaser_policy_runtime",
        "pipeline.identity_failsafe",
        "pipeline.cross_source_dedup",
    ]
    expected_post = [
        "pipeline.qa_reedit_window_contract",
        "pipeline.draft_identity_metadata",
    ]
    calls: list[str] = []
    previous = {name: sys.modules.get(name) for name in [*expected_pre, *expected_post]}
    old_backend = os.environ.get("STORAGE_BACKEND")
    old_batch = os.environ.pop("RAW_BATCH_ID", None)
    os.environ["STORAGE_BACKEND"] = "drive"
    try:
        for name in [*expected_pre, *expected_post]:
            _fake_install_module(name, calls)
        bootstrap.install_pre_orchestrator_patches()
        bootstrap.install_post_orchestrator_patches()
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if old_backend is None:
            os.environ.pop("STORAGE_BACKEND", None)
        else:
            os.environ["STORAGE_BACKEND"] = old_backend
        if old_batch is not None:
            os.environ["RAW_BATCH_ID"] = old_batch
    if calls != [*expected_pre, *expected_post]:
        raise AssertionError(f"actual bootstrap order diverged: {calls}")


def assert_focused_window_requires_new_evidence() -> None:
    from pipeline.primary_actor_policy import classify_primary_actor, normalize_focused_subwindow_evidence

    ambiguous = {
        "person_id": "person_A",
        "primary_actor_clear": False,
        "primary_actor_confidence": 0.2,
        "identity_continuity": "uncertain",
        "competing_active_subjects": True,
        "target_occluded_at_key_moment": True,
        "description": "The target becomes unclear in the wide window.",
    }
    focused = normalize_focused_subwindow_evidence(ambiguous)
    if focused.get("primary_actor_clear") is True:
        raise AssertionError("focused rescue manufactured primary_actor_clear=true")
    if str(focused.get("identity_continuity") or "").lower() in {"stable", "continuous"}:
        raise AssertionError("focused rescue manufactured stable identity continuity")
    confidence = focused.get("primary_actor_confidence")
    if isinstance(confidence, (int, float)) and confidence > 0.2:
        raise AssertionError("focused rescue increased confidence without new evidence")
    classification = classify_primary_actor(focused, visible_subject_count=2)
    if classification.get("decision") != "review_required":
        raise AssertionError("focused window passed before scoped continuity evidence was evaluated")


def assert_detected_athlete_accountability() -> None:
    import pipeline.performance_reel_policy as policy

    fn = getattr(policy, "filter_session_result_for_performance_reel", None)
    if not callable(fn):
        raise AssertionError("coverage-first session filter is not an exported/testable contract")
    result = fn({
        "activity": "surfing",
        "persons": [
            {
                "id": "person_rejected",
                "description": "surfer with failed takeoff",
                "no_output_reason": "no_complete_action",
                "events": [{
                    "type": "wave_catch",
                    "start": 0,
                    "end": 4,
                    "score": 4,
                    "hard_reject_reason": "failed_takeoff",
                    "ride_completed": False,
                }],
            },
            {
                "id": "person_selected",
                "description": "surfer with complete ride",
                "events": [{
                    "type": "wave_catch",
                    "start": 10,
                    "end": 30,
                    "score": 7,
                    "ride_completed": True,
                }],
            },
        ],
    })
    people = {person["id"]: person for person in result.get("persons", [])}
    if set(people) != {"person_rejected", "person_selected"}:
        raise AssertionError(f"detected athlete disappeared before accountability: {sorted(people)}")
    rejected = people["person_rejected"]
    if rejected.get("events") != [] or not rejected.get("no_output_reason"):
        raise AssertionError("rejected athlete lacks explicit no-output evidence")
    registry = result.get("detected_athlete_registry")
    if not isinstance(registry, list) or {row.get("person_id") for row in registry} != set(people):
        raise AssertionError("detected-athlete registry is incomplete")


def _wave(event_id: str, start: float, end: float) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "person_id": "person_A",
        "athlete_id": "athlete_A",
        "sport": "surfing",
        "type": "wave_catch",
        "start": start,
        "end": end,
        "score": 7,
        "ride_completed": True,
        "performance_reel_contract": "all_usable_waves_per_athlete_v1",
        "edit": {"slowmo": False},
    }


def assert_rendered_duration_budget_and_no_hidden_duplicate() -> None:
    import pipeline.performance_reel_policy as policy

    reserve = getattr(policy, "RENDERED_TIMELINE_RESERVED_SECONDS", None)
    if not isinstance(reserve, (int, float)) or reserve < 2.5:
        raise AssertionError("partition budget does not reserve the rendered timeline additions")
    groups = policy.partition_complete_performance_reels(
        [_wave("wave_1", 0, 44), _wave("wave_2", 50, 94)],
        slowmo_capable=False,
        target_max=89.0,
    )
    if len(groups) != 2:
        raise AssertionError("near-limit whole waves were not repartitioned before rendering")
    should_prepend = getattr(policy, "should_prepend_teaser", None)
    if not callable(should_prepend):
        raise AssertionError("performance-reel teaser policy is not explicit")
    if should_prepend(groups[0]):
        raise AssertionError("performance reel visually duplicates a wave through a hidden teaser")


def assert_qa_maps_actual_rendered_timeline() -> None:
    import pipeline.orchestrator as orchestrator

    mapper = getattr(orchestrator, "_event_index_for_qa_defect", None)
    if not callable(mapper):
        raise AssertionError("QA repair has no rendered-timeline/event-id mapper")
    events = [
        {**_wave("wave_1", 0, 30), "rendered_timeline_start": 0.0, "rendered_timeline_end": 20.0},
        {**_wave("wave_2", 40, 70), "rendered_timeline_start": 19.75, "rendered_timeline_end": 42.0},
    ]
    if mapper(events, {"event_id": "wave_2", "at_seconds": 4.0}) != 1:
        raise AssertionError("event_id did not take precedence over an approximate timestamp")
    if mapper(events, {"at_seconds": 30.0}) != 1:
        raise AssertionError("QA timestamp was not mapped through actual rendered offsets")


def assert_one_immutable_media_snapshot() -> None:
    import pipeline.publishable_reel_policy as policy

    signature = inspect.signature(policy.record_athlete_outcome)
    if "specs_by_path" not in signature.parameters:
        raise AssertionError("manifest recorder cannot accept one immutable media-spec snapshot")
    with tempfile.TemporaryDirectory() as td:
        manifest = Path(td) / "manifest.json"
        reel = str(Path(td) / "part.mp4")
        old = os.environ.get("PUBLISHABLE_REEL_MANIFEST_FILE")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        try:
            policy.reset_manifest()
            calls = 0

            def forbidden_inspection(_path: str) -> dict[str, Any]:
                nonlocal calls
                calls += 1
                raise AssertionError("immutable snapshot was ignored and media was inspected again")

            snapshot = {
                reel: {
                    "duration": 30.0,
                    "width": 1080,
                    "height": 1920,
                    "aspect": 1080 / 1920,
                    "has_audio": False,
                },
            }
            row = policy.record_athlete_outcome(
                sport="surfing",
                athlete_label="target surfer",
                final_reels=[reel],
                events_by_reel={reel: [_wave("wave_1", 0, 20)]},
                flagged_paths=set(),
                specs_getter=forbidden_inspection,
                specs_by_path=snapshot,
            )
            if calls:
                raise AssertionError(f"media was inspected {calls} extra time(s)")
            part = row["parts"][0]
            if part.get("media_specs_revision") is None or part.get("duration") != 30.0:
                raise AssertionError("manifest did not preserve the immutable media snapshot")
        finally:
            if old is None:
                os.environ.pop("PUBLISHABLE_REEL_MANIFEST_FILE", None)
            else:
                os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = old


def assert_selection_is_not_mislabeled_as_draft() -> None:
    from scripts.build_athlete_coverage_report import build_report

    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "ledger.json"
        ledger.write_text(json.dumps({
            "candidates": [{
                "candidate_id": "candidate_1",
                "person_id": "person_A",
                "athlete_id": "athlete_A",
                "source_video": "source.mp4",
                "person_description": "target surfer",
                "score": 8,
                "selected": True,
                "discarded": False,
                "source_window": {"start": 0, "end": 20, "duration": 20},
                "final_source_window": {"start": 0, "end": 20, "duration": 20},
            }],
        }), encoding="utf-8")
        report = build_report(ledger)
        outcome = report["athletes"][0]["final_outcome"]
        if outcome != "selected_for_render":
            raise AssertionError(f"selector state was mislabeled as {outcome!r}")


def assert_operator_uses_authoritative_publishability() -> None:
    helper_path = ROOT / "web-api/src/lib/draft-publishability.ts"
    if not helper_path.exists():
        raise AssertionError("server-side draft publishability authority is missing")
    helper = helper_path.read_text(encoding="utf-8")
    listing = (ROOT / "web-api/src/app/api/operator/drafts/route.ts").read_text(encoding="utf-8")
    approval = (ROOT / "web-api/src/lib/operator-draft-approve.ts").read_text(encoding="utf-8")
    for token in ("draft_publishability", "storage_object_id", "qa_verdict", "publishable"):
        if token not in helper:
            raise AssertionError(f"authoritative publishability helper lacks {token}")
    if "loadAuthoritativeDraftPublishability" not in listing:
        raise AssertionError("draft listing does not read authoritative publishability")
    if "requireAuthoritativeDraftPublishability" not in approval:
        raise AssertionError("approval endpoint does not require positive server-side publishability")
    if "body.review_required" in approval or "body.qa_review_required" in approval:
        raise AssertionError("approval still trusts client-supplied QA state")


def assert_terminal_state_has_durable_retry_and_readback() -> None:
    import scripts.record_publishable_business_gate_status as status

    for name in ("write_status_outbox", "verify_terminal_state"):
        if not callable(getattr(status, name, None)):
            raise AssertionError(f"terminal convergence helper missing: {name}")
    with tempfile.TemporaryDirectory() as td:
        outbox = Path(td) / "terminal-status-outbox.json"
        writes: list[dict[str, Any]] = []

        def marker(**fields: Any) -> None:
            writes.append(fields)

        changed = status.record_gate_failure(
            {"passed": False, "errors": ["coverage failed"]},
            result_path="gate.json",
            marker=marker,
            reader=lambda: {"status": "failed", "stage": "publishable_business_gate_failed"},
            outbox_path=outbox,
        )
        if not changed or len(writes) != 1 or outbox.exists():
            raise AssertionError("verified terminal write did not converge cleanly")

        def broken_marker(**_fields: Any) -> None:
            raise RuntimeError("database unavailable")

        try:
            status.record_gate_failure(
                {"passed": False, "errors": ["coverage failed"]},
                result_path="gate.json",
                marker=broken_marker,
                reader=lambda: {},
                outbox_path=outbox,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("failed durable status write did not fail closed")
        if not outbox.exists():
            raise AssertionError("failed terminal update did not leave a durable retry record")


def main() -> int:
    scenario("official engineering basis", assert_official_basis)
    scenario("canonical production bootstrap", assert_canonical_production_bootstrap)
    scenario("focused window requires new identity evidence", assert_focused_window_requires_new_evidence)
    scenario("detected athlete remains accountable", assert_detected_athlete_accountability)
    scenario("rendered duration budget and no hidden duplicate", assert_rendered_duration_budget_and_no_hidden_duplicate)
    scenario("QA maps actual rendered timeline", assert_qa_maps_actual_rendered_timeline)
    scenario("one immutable media snapshot", assert_one_immutable_media_snapshot)
    scenario("selection is not mislabeled as draft", assert_selection_is_not_mislabeled_as_draft)
    scenario("operator uses authoritative publishability", assert_operator_uses_authoritative_publishability)
    scenario("terminal state has durable retry and readback", assert_terminal_state_has_durable_retry_and_readback)

    if FAILURES:
        print("\nCross-layer logical consistency contract failed:")
        for failure in FAILURES:
            print(f"- {failure}")
        return 1
    print("\nCross-layer logical consistency contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
