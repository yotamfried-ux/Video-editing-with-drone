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
    # Strong evidence: two clusters with the same track_id are the same athlete and
    # should become one collection/cluster, preventing duplicate standalone drafts.
    clusters = [
        {
            "description": "surfer in black wetsuit",
            "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "a1", "track_id": "trk-7", "type": "surf_ride", "start": 1, "end": 10}]}],
        },
        {
            "description": "surfer with dark board",
            "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "b1", "track_id": "trk-7", "type": "surf_ride", "start": 20, "end": 35}]}],
        },
    ]
    merged = canonicalize_clusters(clusters)
    assert_true(len(merged) == 1, f"same track should merge to one athlete cluster, got {len(merged)}")
    athlete_id = merged[0].get("athlete_id")
    assert_true(str(athlete_id).startswith("ath_"), "merged cluster must expose stable athlete_id")
    assert_true(merged[0].get("athlete_collection_policy") == "merged_same_athlete", "merged duplicate athlete must be marked as collection")
    events = [event for app in merged[0]["appearances"] for event in app["events"]]
    assert_true({event.get("athlete_id") for event in events} == {athlete_id}, "all merged events must share athlete_id")
    assert_true(any(event.get("athlete_duplicate_group") for event in events), "merged duplicates must expose duplicate group evidence")

    # Weak evidence: similar descriptions without track/athlete evidence must NOT be guessed together.
    weak = canonicalize_clusters([
        {"description": "surfer in black wetsuit", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "w1", "type": "surf_ride", "start": 1, "end": 10}]}]},
        {"description": "surfer in black swimsuit", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "w2", "type": "surf_ride", "start": 2, "end": 12}]}]},
    ])
    assert_true(len(weak) == 2, "weak visual/text similarity must not merge athletes")
    assert_true(all(c.get("athlete_canonical_evidence_status") == "weak" for c in weak), "weak clusters must be explicit")
    assert_true(len({c.get("athlete_id") for c in weak}) == 2, "weak clusters should still get distinct athlete IDs")

    # Long-video/session path: persons and events get IDs before orchestrator loops over people.
    session = {"persons": [{"id": "person_A", "description": "surfer red board", "events": [{"event_id": "s1"}]}]}
    annotated = annotate_session_persons(session, "/tmp/source.mp4")
    person = annotated["persons"][0]
    assert_true(str(person.get("athlete_id", "")).startswith("ath_"), "person must get athlete_id")
    assert_true(person["events"][0].get("athlete_id") == person.get("athlete_id"), "person event must inherit athlete_id")
    assert_true(person["events"][0].get("person_id") == "person_A", "person_id should be preserved on events")

    # Runtime install path: verify patching without importing the real analyzer/identity modules
    # because those modules pull production-only API/dependency setup that is not part of this contract.
    fake_analyzer = SimpleNamespace(
        analyze_session=lambda path: {
            "persons": [{"id": "person_B", "description": "surfer blue board", "events": [{"event_id": "p1"}]}]
        }
    )
    fake_identity = SimpleNamespace(
        cluster_clips=lambda clip_analyses: [
            {"description": "surfer in black wetsuit", "appearances": [{"path": "/tmp/a.mp4", "events": [{"event_id": "c1", "track_id": "trk-42"}]}]},
            {"description": "surfer with dark board", "appearances": [{"path": "/tmp/b.mp4", "events": [{"event_id": "c2", "track_id": "trk-42"}]}]},
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
    assert_true("_install_athlete_canonicalization_runtime()\n\nimport pipeline.orchestrator" in runner, "tracked runner must install athlete canonicalization before orchestrator import")

    print("athlete canonicalization contract ok")


if __name__ == "__main__":
    main()
