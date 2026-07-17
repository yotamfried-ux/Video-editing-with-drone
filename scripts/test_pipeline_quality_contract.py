#!/usr/bin/env python3
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def run_identity_runtime_contract() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/test_identity_failsafe_contract.py")],
        check=True,
    )


def run_cross_source_dedup_contract() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/test_cross_source_dedup_contract.py")],
        check=True,
    )


def main() -> int:
    runtime = _read("pipeline/runtime_quality.py")
    performance_policy = _read("pipeline/performance_reel_policy.py")
    identity_failsafe = _read("pipeline/identity_failsafe.py")
    cross_source_dedup = _read("pipeline/cross_source_dedup.py")
    perception_runtime = _read("pipeline/perception/runtime.py")
    event_fingerprint = _read("pipeline/perception/event_fingerprint.py")
    athlete_canonicalization = _read("pipeline/athlete_canonicalization.py")
    primary_actor_policy = _read("pipeline/primary_actor_policy.py")
    multi_person_gate = _read("pipeline/multi_person_clip_gate.py")
    subject_gate = _read("pipeline/subject_gate_policy.py")
    context_qa_long_video = _read("pipeline/context_qa_long_video.py")
    raw_timestamp_recovery = _read("pipeline/raw_timestamp_recovery.py")
    run_tracked = _read("scripts/run_tracked.py")
    sitecustomize = _read("scripts/sitecustomize.py")
    workflow = _read(".github/workflows/operator-smoke-check.yml")

    for source in (
        runtime,
        performance_policy,
        identity_failsafe,
        cross_source_dedup,
        perception_runtime,
        event_fingerprint,
        athlete_canonicalization,
        primary_actor_policy,
        multi_person_gate,
        subject_gate,
        context_qa_long_video,
        raw_timestamp_recovery,
        run_tracked,
        sitecustomize,
    ):
        ast.parse(source)

    require_tokens(
        "runtime quality hardening",
        runtime,
        [
            "_MIN_KEEP_SCORE = 6",
            "if _score(ev) >= _MIN_KEEP_SCORE",
            "_IDENTITY_THUMB_SIZE = 640",
            "identity_thumb_",
            "crop_x",
            "crop_y",
            "crop={_IDENTITY_THUMB_SIZE}:{_IDENTITY_THUMB_SIZE}:",
            "original = analyzer.analyze_session",
            "analyzer.analyze_session = hardened_analyze_session",
            "_sportreel_quality_runtime_installed",
        ],
    )
    require_no_tokens(
        "runtime quality hardening",
        runtime,
        ["best_score >= 5", "score >= 5", "include their top 2"],
    )

    require_tokens(
        "performance reel coverage policy",
        performance_policy,
        [
            "EVERY DISTINCT WAVE RIDE",
            "MAX_PERFORMANCE_REEL_SEC = 89.0",
            "PerformanceReelPackingError",
            "if surf_event and is_explicit_failed_takeoff",
            "if not _surf_events(event_list)",
            "remove_duplicate_events(event_list)",
            "performance_reel_total_wave_count",
            "QA_FAIL: Reel did not pass final quality review.",
        ],
    )

    require_tokens(
        "perception runtime enrichment",
        perception_runtime,
        [
            "SPORTREEL_PERCEPTION_SIDECAR_DIR",
            "SPORTREEL_PERCEPTION_COMMAND",
            "SPORTREEL_REQUIRE_PERCEPTION",
            "sidecar_output_path",
            "ensure_sidecar_for_video",
            "validate_sidecar",
            "subprocess.run",
            "load_sidecar_detections",
            "enrich_session_with_sidecar",
            "source_window_track_ids",
            "visible_track_ids",
            "perception_evidence_status",
            "tracker_sidecar",
            "ensure_sidecar_for_video(video_path)",
            "analyzer.analyze_session = analyze_with_perception_sidecar",
        ],
    )

    require_tokens(
        "identity failsafe hardening",
        identity_failsafe,
        [
            "def _cluster_has_perception_evidence",
            "medium confidence without bbox perception evidence",
            "missing thumbnails for identity verification",
            "identity verifier error",
            "_sportreel_identity_failsafe_installed",
            "identity._build_clusters_from_data = _wrap_build_clusters(identity)",
            "identity._verify_multi_clusters = _wrap_verify_multi_clusters(identity)",
        ],
    )
    require_no_tokens(
        "identity failsafe hardening",
        identity_failsafe,
        [
            "keeping as-is",
            "verified.append(cluster)\n            continue\n\n            uploaded: list = []",
        ],
    )

    require_tokens(
        "cross-source dedup hardening",
        cross_source_dedup,
        [
            "deduplicate_cross_source_events",
            "_sportreel_cross_source_dedup_installed",
            "editor._partition_events = partition_with_event_filter",
        ],
    )
    require_tokens(
        "event fingerprinting",
        event_fingerprint,
        [
            "def event_fingerprint",
            "def event_quality_score",
            "def deduplicate_cross_source_events",
            "event_fingerprint",
            "bbox_trajectory_hash",
            "thumbnail_hash",
            "dedup_dropped_duplicates",
        ],
    )
    require_tokens(
        "athlete canonicalization",
        athlete_canonicalization,
        [
            "def canonicalize_clusters",
            "def annotate_session_persons",
            "athlete_id",
            "athlete_canonical_evidence_status",
            "DUPLICATE_ATHLETE",
            "identity.cluster_clips = cluster_with_athlete_ids",
            "analyzer.analyze_session = analyze_with_athlete_ids",
        ],
    )

    require_tokens(
        "primary actor policy",
        primary_actor_policy,
        [
            "def classify_primary_actor",
            "def ambiguity_reasons",
            "def merge_gate_defect_into_qa",
            "blocked_review_required",
            "qa_review_required",
            "approval_blocked_reasons",
            "PRIMARY_ACTOR_UNCLEAR",
            "PRIMARY_ACTOR_OCCLUDED",
            "IDENTITY_SWITCH",
            "background_people_allowed",
            "primary_actor_not_reliably_followable",
        ],
    )
    require_tokens(
        "multi-person primary actor gate",
        multi_person_gate,
        [
            "def annotate_multi_person_events",
            "def has_multi_person_defect",
            "classify_primary_actor",
            "merge_gate_defect_into_qa",
            "default_defect_type=IDENTITY_UNCERTAIN_DEFECT",
            "allowed_primary_actor_clear",
            "background_people_allowed",
            "allowed_social_moment",
        ],
    )
    require_no_tokens(
        "multi-person primary actor gate",
        multi_person_gate,
        ["extra_visible_subject_in_single_athlete_draft", "def _merge_qa_gate"],
    )
    require_tokens(
        "subject continuity gate",
        subject_gate,
        [
            "def annotate_subject_events",
            "def has_subject_isolation_defect",
            "subject_isolation_gate",
            "primary_track_dominance_ratio",
            "primary_track_continuity_ratio",
            "load_sidecar_detections",
            "classify_primary_actor",
            "merge_gate_defect_into_qa",
            "default_defect_type=DEFECT_TYPE",
            "background_people_allowed",
            "PRIMARY_ACTOR_UNCLEAR",
        ],
    )
    require_no_tokens(
        "subject continuity gate",
        subject_gate,
        [
            "low_primary_track_dominance",
            "source window contains multiple significant canonical tracks",
            "def _merge_qa_gate",
        ],
    )
    require_tokens(
        "long-video subject gate coverage",
        context_qa_long_video,
        [
            "annotate_subject_events",
            "has_subject_isolation_defect",
            "_annotate_subject_gates",
            "_has_subject_gate_defect",
            "flagged_set.add(reel)",
            "QA-FLAGGED",
        ],
    )

    require_tokens(
        "raw timestamp recovery",
        raw_timestamp_recovery,
        [
            "def recover_event_timestamp",
            "def recover_raw_session_payload",
            "def annotate_parsed_session",
            "def enrich_selector_payload",
            "minute_second",
            "analyzer._parse_session = parse_with_timestamp_recovery",
        ],
    )

    require_tokens(
        "tracked runner quality install",
        run_tracked,
        [
            "def _install_perception_runtime()",
            "from pipeline.perception.runtime import install",
            "def _install_pipeline_quality_runtime()",
            "from pipeline.runtime_quality import install",
            "def _install_performance_reel_policy_runtime()",
            "from pipeline.performance_reel_policy import install",
            "def _install_raw_timestamp_recovery()",
            "from pipeline.raw_timestamp_recovery import install",
            "def _install_identity_failsafe_runtime()",
            "from pipeline.identity_failsafe import install",
            "def _install_cross_source_dedup_runtime()",
            "from pipeline.cross_source_dedup import install",
            "def _install_draft_diagnostics_runtime()",
            "from pipeline.draft_diagnostics import install",
            "def _install_candidate_ledger_runtime()",
            "from pipeline.candidate_ledger import install",
            "def _install_athlete_canonicalization_runtime()",
            "from pipeline.athlete_canonicalization import install",
            "_install_perception_runtime()\n_install_pipeline_quality_runtime()\n_install_performance_reel_policy_runtime()\n_install_raw_timestamp_recovery()\n_install_chunk_timeline_runtime()\n_install_selector_candidate_runtime()",
            "_install_identity_failsafe_runtime()",
            "_install_cross_source_dedup_runtime()",
            "_install_draft_diagnostics_runtime()",
            "_install_candidate_ledger_runtime()",
            "_install_athlete_canonicalization_runtime()\n\nimport pipeline.orchestrator as _orchestrator",
        ],
    )
    require_tokens(
        "script bootstrap timestamp install",
        sitecustomize,
        [
            "def _install_perception_runtime()",
            "from pipeline.perception.runtime import install",
            "def _install_raw_timestamp_recovery()",
            "from pipeline.raw_timestamp_recovery import install",
            "_install_perception_runtime()\n_install_raw_timestamp_recovery()\n_install_analyzer_score_guard()\n_install_chunk_timeline_runtime()",
        ],
    )
    require_no_tokens(
        "fail-silent script bootstrap",
        sitecustomize,
        ["pipeline.performance_reel_policy"],
    )

    require_tokens(
        "operator smoke workflow quality coverage",
        workflow,
        [
            "pipeline/runtime_quality.py",
            "pipeline/stages/analyzer.py",
            "pipeline/stages/identity.py",
            "pipeline/cross_source_dedup.py",
            "pipeline/primary_actor_policy.py",
            "pipeline/multi_person_clip_gate.py",
            "pipeline/context_qa_long_video.py",
            "pipeline/perception/**",
            "pipeline/perception/event_fingerprint.py",
            "scripts/build_athlete_coverage_report.py",
            "scripts/test_athlete_coverage_report_contract.py",
            "scripts/test_pipeline_quality_contract.py",
            "scripts/test_cross_source_dedup_contract.py",
            "scripts/test_multi_person_clip_gate_contract.py",
            "Validate Pipeline quality contract",
            "Validate Cross-source dedup contract",
            "Validate Primary actor continuity gate contract",
            "Validate Athlete coverage report contract",
        ],
    )

    run_identity_runtime_contract()
    run_cross_source_dedup_contract()
    print("Pipeline quality hardening contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
