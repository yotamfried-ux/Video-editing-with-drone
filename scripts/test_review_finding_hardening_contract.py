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


def assert_failed_audio_probe_is_unknown() -> None:
    original_config = sys.modules.get("config")
    original_ffmpeg = sys.modules.pop("integrations.ffmpeg", None)
    sys.modules["config"] = types.ModuleType("config")
    try:
        import integrations.ffmpeg as ffmpeg
        from pipeline.silent_output_policy import silent_social_ready_issues

        original_run = ffmpeg.subprocess.run
        original_source_info = ffmpeg.get_source_info
        original_duration = ffmpeg.get_duration
        try:
            ffmpeg.get_source_info = lambda _path: {"width": 1080, "height": 1920}
            ffmpeg.get_duration = lambda _path: 30.0

            def timed_out(*_args, **_kwargs):
                raise ffmpeg.subprocess.TimeoutExpired(cmd="ffprobe", timeout=15)

            ffmpeg.subprocess.run = timed_out
            specs = ffmpeg.get_reel_specs("probe-timeout.mp4")
        finally:
            ffmpeg.subprocess.run = original_run
            ffmpeg.get_source_info = original_source_info
            ffmpeg.get_duration = original_duration
    finally:
        sys.modules.pop("integrations.ffmpeg", None)
        if original_ffmpeg is not None:
            sys.modules["integrations.ffmpeg"] = original_ffmpeg
        if original_config is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = original_config

    if specs.get("has_audio") is not None:
        raise SystemExit(f"failed audio probe was recorded as proven silence: {specs}")
    if "audio_state_unknown" not in silent_social_ready_issues(specs):
        raise SystemExit("unknown audio state did not block publishability")


def assert_complete_action_window_persists_to_qa() -> None:
    import pipeline.stages as stages
    from pipeline.complete_action_window_policy import install, normalize_complete_action_event
    from pipeline.subject_gate_policy import effective_cut_window

    event = {
        "event_id": "wave_full",
        "performance_reel_contract": "all_usable_waves_per_athlete_v1",
        "type": "wave_catch",
        "start": 10.0,
        "end": 50.0,
        "score": 8,
        "_cap_dur": 15.0,
        "_single_clip_cap": True,
        "_is_climax": False,
    }
    normalized = normalize_complete_action_event(event)
    if effective_cut_window(normalized) != (10.0, 50.0):
        raise SystemExit(f"complete action remained capped before render: {normalized}")

    fake_editor = types.SimpleNamespace(
        cut_clip=lambda *_args, **_kwargs: "clip.mp4",
        _events_with_rendered_timeline=lambda events, _paths, _transitions=None: list(events),
    )
    original_editor = getattr(stages, "editor", None)
    stages.editor = fake_editor
    try:
        install()
        persisted = fake_editor._events_with_rendered_timeline(
            [event],
            ["wave_full.mp4"],
            ["cut"],
        )[0]
    finally:
        if original_editor is None:
            delattr(stages, "editor")
        else:
            stages.editor = original_editor

    if effective_cut_window(persisted) != (10.0, 50.0):
        raise SystemExit(f"QA evidence did not preserve the rendered action window: {persisted}")
    if persisted.get("complete_action_window_preserved") is not True:
        raise SystemExit("QA evidence lacks explicit complete-action preservation")


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


def assert_storage_authority_identity() -> None:
    """Operator listing and approval must bind authority to the storage object only."""
    r2 = (ROOT / "integrations/r2_storage.py").read_text(encoding="utf-8")
    helper = (ROOT / "web-api/src/lib/draft-publishability.ts").read_text(encoding="utf-8")
    listing = (ROOT / "web-api/src/app/api/operator/drafts/route.ts").read_text(encoding="utf-8")
    approval = (ROOT / "web-api/src/lib/operator-draft-approve.ts").read_text(encoding="utf-8")
    migration = (ROOT / "supabase/migrations/20260717_draft_publishability_authority.sql").read_text(encoding="utf-8")

    required = {
        "R2 immutable upload identity": (r2, [
            "return the canonical immutable R2 object key",
            "upload_object(draft_path, key, \"video/mp4\")",
            "return key",
        ]),
        "authority object lookup": (helper, [
            ".in('storage_object_id', objectIds)",
            "authorities.get(input.storageObjectId)",
            "authority.draft_name !== input.draftName",
        ]),
        "operator listing object lookup": (listing, [
            "authorities.get(draft.id)",
        ]),
        "operator approval object lookup": (approval, [
            "storageObjectId: fileId",
            "draftName: fileName",
        ]),
        "authority schema": (migration, [
            "storage_object_id text primary key",
            "draft_name text not null,",
        ]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} missing immutable identity tokens: {missing}")

    forbidden = {
        "authority filename query": (helper, [".in('draft_name'", "`name:${"]),
        "operator filename fallback": (listing, ["authorities.get(`name:"]),
        "globally unique draft name": (migration, ["draft_name text not null unique"]),
    }
    for label, (source, tokens) in forbidden.items():
        present = [token for token in tokens if token in source]
        if present:
            raise SystemExit(f"{label} survived: {present}")


def assert_source_wiring() -> None:
    qa = (ROOT / "pipeline/silent_qa_policy.py").read_text(encoding="utf-8")
    parent = (ROOT / "pipeline/primary_actor_parent_identity.py").read_text(encoding="utf-8")
    install_chain = (ROOT / "pipeline/publishable_qa_evidence.py").read_text(encoding="utf-8")
    required = {
        "silent QA": (qa, ["unexpected audio track", "audio stream state could not prove silence", "no audio track"]),
        "parent identity": (parent, ['event["person_id"] = person_id', "primary_actor_id(event)", "rewrite_raw_selection_json"]),
        "install chain": (install_chain, ["install_parent_identity()", "install_silent_qa()"]),
    }
    for label, (source, tokens) in required.items():
        missing = [token for token in tokens if token not in source]
        if missing:
            raise SystemExit(f"{label} missing review-fix tokens: {missing}")


def main() -> int:
    assert_silent_technical_qa()
    assert_failed_audio_probe_is_unknown()
    assert_complete_action_window_persists_to_qa()
    assert_parent_identity_before_filtering()
    assert_storage_authority_identity()
    assert_source_wiring()
    print("Final review finding hardening checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
