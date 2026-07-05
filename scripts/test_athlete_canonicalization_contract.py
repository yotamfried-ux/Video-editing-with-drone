#!/usr/bin/env python3
"""Contract for REAL-ATHLETE-001 run-level athlete canonicalization."""
from __future__ import annotations

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

    install()
    import pipeline.stages.analyzer as analyzer
    import pipeline.stages.identity as identity
    assert_true(getattr(analyzer, "_sportreel_athlete_canonicalization_analyzer_installed", False), "analyzer must be patched")
    assert_true(getattr(identity, "_sportreel_athlete_canonicalization_identity_installed", False), "identity must be patched")

    with open("scripts/run_tracked.py", encoding="utf-8") as handle:
        runner = handle.read()
    assert_true("_install_athlete_canonicalization_runtime()\n\nimport pipeline.orchestrator" in runner, "tracked runner must install athlete canonicalization before orchestrator import")

    print("athlete canonicalization contract ok")


if __name__ == "__main__":
    main()
