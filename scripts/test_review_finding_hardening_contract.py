#!/usr/bin/env python3
"""Regression tests for final automated-review findings."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def assert_silent_technical_qa() -> None:
    import pipeline.stages as stages
    from pipeline.silent_qa_policy import install

    state = {
        "has_audio": False,
        "issues": ["no audio track"],
    }

    def original(_path: str):
        specs = {
            "has_audio": state["has_audio"],
            "duration": 30.0,
            "width": 1080,
            "height": 1920,
            "aspect": 1080 / 1920,
        }
        return specs, not state["issues"], list(state["issues"])

    fake_analyzer = types.SimpleNamespace(_check_technical_compliance=original)
    original_analyzer = getattr(stages, "analyzer", None)
    stages.analyzer = fake_analyzer
    try:
        install()
        specs, passed, issues = fake_analyzer._check_technical_compliance("silent.mp4")
        if specs["has_audio"] is not False or not passed or issues:
            raise SystemExit(f"valid silent file failed deterministic QA: {passed}, {issues}")

        state["has_audio"] = True
        state["issues"] = []
        _specs, passed, issues = fake_analyzer._check_technical_compliance("audio.mp4")
        if passed or "unexpected audio track" not in issues:
            raise SystemExit("audio-bearing file passed silent deterministic QA")

        state["has_audio"] = None
        _specs, passed, issues = fake_analyzer._check_technical_compliance("unknown.mp4")
        if passed or "audio stream state could not prove silence" not in issues:
            raise SystemExit("unknown audio state did not fail closed in QA")
    finally:
        if original_analyzer is None:
            delattr(stages, "analyzer")
        else:
            stages.analyzer = original_analyzer


def _raw_session(*, person_id: str, include_centrality: bool) -> str:
    event = {
        "type": "wave_catch",
        "start": 10.0,
        "end": 28.0,
        "score": 8,
        "description": "Another surfer enters the same wave while the target remains central.",
        "multiple_active_subjects": True,
        "competing_active_subjects": True,
    }
    if include_centrality:
        event.update({
            "primary_actor_clear": True,
            "primary_actor_confidence": 0.9,
            "identity_continuity": "stable",
        })
    return json.dumps({
        "activity": "surfing",
        "persons": [{
            "id": person_id,
            "description": "target surfer",
            "events": [event],
        }],
    })


def assert_parent_identity_before_filtering() -> None:
    import pipeline.single_athlete_selection_policy as selection
    from pipeline.primary_actor_parent_identity import install

    install()

    retained = json.loads(
        selection.rewrite_raw_selection_json(
            _raw_session(person_id="person_A", include_centrality=True)
        )
    )["persons"][0]["events"]
    if len(retained) != 1:
        raise SystemExit("parent person identity was not available before crowded-event filtering")
    if retained[0].get("person_id") != "person_A":
        raise SystemExit("retained event did not preserve its parent person identity")

    no_parent = json.loads(
        selection.rewrite_raw_selection_json(
            _raw_session(person_id="", include_centrality=True)
        )
    )["persons"][0]["events"]
    if no_parent:
        raise SystemExit("crowded event without any target identity did not fail closed")

    no_centrality = json.loads(
        selection.rewrite_raw_selection_json(
            _raw_session(person_id="person_A", include_centrality=False)
        )
    )["persons"][0]["events"]
    if no_centrality:
        raise SystemExit("parent ID alone bypassed positive centrality requirements")


def assert_source_wiring() -> None:
    qa = (ROOT / "pipeline/silent_qa_policy.py").read_text(encoding="utf-8")
    parent = (ROOT / "pipeline/primary_actor_parent_identity.py").read_text(encoding="utf-8")
    install_chain = (ROOT / "pipeline/publishable_qa_evidence.py").read_text(encoding="utf-8")
    required = {
        "silent QA": (qa, ["unexpected audio track", "audio stream state could not prove silence", "no audio track"]),
        "parent identity": (parent, ["event[\"person_id\"] = person_id", "primary_actor_id(event)", "rewrite_raw_selection_json"]),
        "install chain": (install_chain, ["install_parent_identity()", "install_silent_qa()"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} missing review-fix tokens: {missing}")


def main() -> int:
    assert_silent_technical_qa()
    assert_parent_identity_before_filtering()
    assert_source_wiring()
    print("Final review finding hardening checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
