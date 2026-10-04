#!/usr/bin/env python3
"""Contract for REAL-ATHLETE-001 run-level athlete canonicalization."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from pipeline.athlete_canonicalization import annotate_session_persons, canonicalize_clusters, install


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    # Tracker IDs are source-local and must never merge athletes across files.
    same_numeric_track_different_sources = canonicalize_clusters([
        {"description": "source a surfer", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "a1", "track_id": "7", "source_video": "/tmp/a.mp4"}]}]},
        {"description": "source b surfer", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "b1", "track_id": "7", "source_video": "/tmp/b.mp4"}]}]},
    ])
    assert_true(len(same_numeric_track_different_sources) == 2, "source-local tracker IDs must not merge athletes across videos")

    # Only an explicit externally-established athlete identity may merge sources.
    explicit_identity = canonicalize_clusters([
        {"description": "source a surfer", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "a2", "athlete_id": "customer-athlete-42"}]}]},
        {"description": "source b surfer", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "b2", "athlete_id": "customer-athlete-42"}]}]},
    ])
    assert_true(len(explicit_identity) == 1, "explicit global athlete identity should merge across sources")

    weak = canonicalize_clusters([
        {"description": "surfer in black wetsuit", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "w1", "type": "surf_ride", "start": 1, "end": 10}]}]},
        {"description": "surfer in black swimsuit", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "w2", "type": "surf_ride", "start": 2, "end": 12}]}]},
    ])
    assert_true(len(weak) == 2, "weak visual/text similarity must not merge athletes")
    assert_true(all(c.get("athlete_canonical_evidence_status") == "weak" for c in weak), "weak clusters must be explicit")
    assert_true(len({c.get("athlete_id") for c in weak}) == 2, "weak clusters should still get distinct athlete IDs")

    session = {"persons": [{"id": "person_A", "description": "surfer red board", "events": [{"event_id": "s1"}]}]}
    annotated = annotate_session_persons(session, "/tmp/source.mp4")
    person = annotated["persons"][0]
    assert_true(str(person.get("athlete_id", "")).startswith("ath_"), "person must get athlete_id")
    assert_true(person["events"][0].get("athlete_id") == person.get("athlete_id"), "person event must inherit athlete_id")
    assert_true(person["events"][0].get("person_id") == "person_A", "person_id should be preserved on events")

    fake_analyzer = SimpleNamespace(
        analyze_session=lambda path: {
            "persons": [{"id": "person_B", "description": "surfer blue board", "events": [{"event_id": "p1"}]}]
        }
    )
    fake_identity = SimpleNamespace(
        cluster_clips=lambda clip_analyses: [
            {"description": "surfer in black wetsuit", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "c1", "athlete_id": "global-athlete-42"}]}]},
            {"description": "surfer with dark board", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "c2", "athlete_id": "global-athlete-42"}]}]},
        ]
    )
    sys.modules["pipeline.stages.analyzer"] = fake_analyzer
    sys.modules["pipeline.stages.identity"] = fake_identity

    install()
    assert_true(getattr(fake_analyzer, "_sportreel_athlete_canonicalization_analyzer_installed", False), "analyzer must be patched")
    assert_true(getattr(fake_identity, "_sportreel_athlete_canonicalization_identity_installed", False), "identity must be patched")

    patched_session = fake_analyzer.analyze_session("/tmp/source.mp4")
    patched_person = patched_session["persons"][0]
    assert_true(str(patched_person.get("athlete_id", "")).startswith("ath_"), "patched analyzer must annotate person athlete_id")
    assert_true(patched_person["events"][0].get("athlete_id") == patched_person.get("athlete_id"), "patched analyzer must annotate event athlete_id")

    patched_clusters = fake_identity.cluster_clips([])
    assert_true(len(patched_clusters) == 1, "patched identity must canonicalize same strong athlete evidence")
    assert_true(patched_clusters[0].get("athlete_collection_policy") == "merged_same_athlete", "patched identity must mark duplicate athlete collection policy")

    with open("scripts/run_tracked.py", encoding="utf-8") as handle:
        runner = handle.read()
    with open("pipeline/bootstrap.py", encoding="utf-8") as handle:
        bootstrap = handle.read()
    assert_true("install_pre_orchestrator_patches()" in runner, "tracked runner must use canonical bootstrap")
    assert_true("pipeline.athlete_canonicalization" in bootstrap, "canonical bootstrap must install athlete canonicalization")

    print("athlete canonicalization contract ok")


if __name__ == "__main__":
    main()
