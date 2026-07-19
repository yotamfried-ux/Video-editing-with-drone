#!/usr/bin/env python3
"""Regression tests for publishable runtime integrity interactions."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def specs() -> dict[str, Any]:
    return {
        "has_audio": False,
        "duration": 36.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def event() -> dict[str, Any]:
    return {
        "athlete_id": "surfer_target",
        "event_id": "wave-1",
        "type": "wave_catch",
        "sport": "surfing",
        "start": 10.0,
        "end": 46.0,
        "score": 8,
        "_src": "session.mp4",
        "performance_reel_contract": "all_usable_waves_per_athlete_v1",
        "_cap_dur": 15.0,
    }


def assert_fail_closed_and_staged_alias() -> None:
    import pipeline.publishable_reel_policy as policy
    import pipeline.silent_output_policy as silent
    import pipeline.publishable_runtime_integrity as integrity

    policy.social_ready_issues = silent.silent_social_ready_issues
    integrity._patch_policy()

    with tempfile.TemporaryDirectory(prefix="sportreel-runtime-integrity-") as directory:
        tmp = Path(directory)
        manifest = tmp / "manifest.json"
        original = str(tmp / "target.mp4")
        staged = str(tmp / "target.draft-candidate-001.mp4")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()
        inspect_calls = 0

        def inspect(_path: str) -> dict[str, Any]:
            nonlocal inspect_calls
            inspect_calls += 1
            return specs()

        row = policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="target surfer",
            final_reels=[original],
            events_by_reel={original: [event()]},
            flagged_paths=set(),
            specs_getter=inspect,
        )
        if inspect_calls != 1:
            raise SystemExit(f"unexpected final media inspection count: {inspect_calls}")

        part = row["parts"][0]
        if part.get("qa_evidence_recorded") is not False:
            raise SystemExit("new Part did not start without explicit QA evidence")
        if part.get("qa_passed") is not False or part.get("render_ready") is not False:
            raise SystemExit("new Part was inferred as QA-passed from an empty flagged set")
        if "missing_final_qa_evidence" not in part.get("technical_issues", []):
            raise SystemExit("missing QA evidence was not persisted fail-closed")
        if part.get("has_audio") is not False:
            raise SystemExit("tri-state audio evidence did not preserve proven silence")

        if not policy.register_staged_upload_path(original, staged):
            raise SystemExit("staged upload alias could not be attached")
        if not policy.mark_upload_result(staged, "DRAFT_target.mp4"):
            raise SystemExit("staged upload path did not reconcile to the original Part")

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        stored = payload["athletes"][0]["parts"][0]
        if stored.get("uploaded_to_review") is not True:
            raise SystemExit("staged upload success was not recorded")
        if stored.get("uploaded_local_path") != os.path.abspath(staged):
            raise SystemExit("manifest did not retain the actual staged upload path")
        if os.path.abspath(staged) not in stored.get("upload_path_aliases", []):
            raise SystemExit("staged alias evidence was lost")
        if stored.get("publishable") is True:
            raise SystemExit("upload without explicit QA evidence became publishable")


def assert_qa_scope_has_one_owner() -> None:
    """Runtime integrity must not replace the canonical invocation-scoped store."""
    import pipeline.publishable_pending_scope as pending
    import pipeline.publishable_qa_evidence as evidence
    import pipeline.publishable_runtime_integrity as integrity

    pending.install()
    original_record = evidence.record_qa_result
    original_consume = evidence.consume_recorded_qa
    integrity.install()
    if evidence.record_qa_result is not original_record:
        raise SystemExit("runtime integrity replaced canonical QA recording")
    if evidence.consume_recorded_qa is not original_consume:
        raise SystemExit("runtime integrity replaced canonical atomic QA consumption")

    token_one = "integrity_scope_one"
    token_two = "integrity_scope_two"
    path = "/tmp/shared-name.mp4"
    evidence.record_qa_result(path, {"verdict": "PASS", "overall": "PASS"}, invocation_token=token_one)
    evidence.record_qa_result(path, {"verdict": "FAIL", "overall": "FAIL"}, invocation_token=token_two)
    consumed = evidence.consume_recorded_qa(token_one)
    if consumed.get(os.path.abspath(path), {}).get("verdict") != "PASS":
        raise SystemExit("canonical QA invocation did not consume its own evidence")
    remaining = evidence.get_recorded_qa(path, invocation_token=token_two)
    if remaining is None or remaining.get("verdict") != "FAIL":
        raise SystemExit("consuming one QA invocation contaminated another")
    evidence.clear_recorded_qa(token_two)


def assert_complete_action_window() -> None:
    from pipeline.complete_action_window_policy import install
    import pipeline.stages as stages

    captured: list[dict[str, Any]] = []

    def original_cut(
        video_path: str,
        selected: dict[str, Any],
        index: int,
        slowmo: bool = False,
        sport: str = "",
        source_info: dict[str, Any] | None = None,
        session_peak: int = 10,
        target_fps: int | None = None,
    ) -> str:
        captured.append(dict(selected))
        return "clip.mp4"

    fake_editor = types.SimpleNamespace(cut_clip=original_cut)
    original_editor = getattr(stages, "editor", None)
    stages.editor = fake_editor
    try:
        install()
        result = fake_editor.cut_clip("source.mp4", event(), 1)
    finally:
        if original_editor is None:
            delattr(stages, "editor")
        else:
            stages.editor = original_editor

    if result != "clip.mp4" or not captured:
        raise SystemExit("complete-action cut wrapper did not call the renderer")
    selected = captured[0]
    if "_cap_dur" in selected:
        raise SystemExit("historical 15-second cap survived on a complete surf ride")
    if selected.get("_is_climax") is not True:
        raise SystemExit("complete ride was not protected from the non-climax cap")
    if (selected.get("start"), selected.get("end")) != (10.0, 46.0):
        raise SystemExit("complete-action policy changed the ride boundaries")


def assert_source_contract() -> None:
    integrity = (ROOT / "pipeline/publishable_runtime_integrity.py").read_text(encoding="utf-8")
    complete = (ROOT / "pipeline/complete_action_window_policy.py").read_text(encoding="utf-8")
    qa = (ROOT / "pipeline/publishable_qa_evidence.py").read_text(encoding="utf-8")
    pending = (ROOT / "pipeline/publishable_pending_scope.py").read_text(encoding="utf-8")
    required = {
        "runtime integrity": [
            "register_staged_upload_path",
            "upload_path_aliases",
            "qa_evidence_recorded",
            "stage_with_manifest_alias",
            "_inspect_once",
            "must not replace those functions",
        ],
        "complete action": [
            "all_usable_waves_per_athlete_v1",
            'effective.pop("_cap_dur", None)',
            'effective["_is_climax"] = True',
        ],
        "QA evidence": [
            "_QA_RESULTS_BY_INVOCATION",
            "consume_recorded_qa",
            "activate_next_scope",
        ],
        "pending scope": [
            "contextvars.ContextVar",
            "uuid.uuid4",
            "create_pending_scope",
        ],
        "install chain": ["pipeline.publishable_runtime_integrity"],
    }
    sources = {
        "runtime integrity": integrity,
        "complete action": complete,
        "QA evidence": qa,
        "pending scope": pending,
        "install chain": qa,
    }
    for label, tokens in required.items():
        missing = [token for token in tokens if token not in sources[label]]
        if missing:
            raise SystemExit(f"{label} missing contract tokens: {missing}")
    forbidden = ["def _patch_qa_evidence_scope", "_QA_TOKEN", "_QA_RESULTS ="]
    present = [token for token in forbidden if token in integrity]
    if present:
        raise SystemExit(f"runtime integrity still owns a divergent QA scope: {present}")


def main() -> int:
    assert_fail_closed_and_staged_alias()
    assert_qa_scope_has_one_owner()
    assert_complete_action_window()
    assert_source_contract()
    print("Publishable runtime integrity contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
