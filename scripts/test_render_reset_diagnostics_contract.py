#!/usr/bin/env python3
"""Contract: faster render preset, parallel verified Reset copy, and log-readable run diagnostics."""
from __future__ import annotations

import importlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_contain_backdrop_blur_runs_on_a_downscaled_copy() -> None:
    source = (ROOT / "pipeline" / "quality_preserving_framing.py").read_text()
    assert "gblur=sigma=30:steps=2" not in source, "the full-resolution 4K blur must not come back"
    assert "_BG_DOWNSCALE = 8" in source and "gblur=sigma={30 / _BG_DOWNSCALE:g}" in source


def test_render_uses_the_fast_preset_for_cut_and_compile_and_can_be_overridden() -> None:
    os.environ.pop("X264_PRESET", None)
    import pipeline.quality_preserving_framing as framing
    framing = importlib.reload(framing)
    assert framing.RENDER_X264_PRESET == "medium"
    source = (ROOT / "pipeline" / "quality_preserving_framing.py").read_text()
    assert '"-preset", RENDER_X264_PRESET' in source and "editor.X264_PRESET = RENDER_X264_PRESET" in source
    assert '"slow"' not in source.split("def install")[1] and '"-preset", "slow"' not in source
    assert 'editor.CLIP_CRF = "12"' in source and 'editor.REEL_CRF = "14"' in source, "CRF (the quality knob) must not change"
    os.environ["X264_PRESET"] = "slow"
    try:
        assert importlib.reload(framing).RENDER_X264_PRESET == "slow"
    finally:
        os.environ.pop("X264_PRESET", None)
        importlib.reload(framing)


class FakeR2:
    RAW_PREFIX, PROCESSED_PREFIX = "raw/", "processed/"

    def __init__(self, names: list[str], fail: str | None = None) -> None:
        self.names, self.fail = names, fail
        self.copied: list[str] = []
        self.deleted: list[str] = []
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def list_objects(self, prefix: str):
        return [{"Key": f"{self.PROCESSED_PREFIX}{n}"} for n in self.names]

    @staticmethod
    def _is_video_key(key: str) -> bool:
        return key.endswith(".mp4")

    @staticmethod
    def _head(key: str):
        return None

    def copy_object_verified(self, source: str, dest: str) -> str:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.15)
        with self.lock:
            self.active -= 1
        if self.fail and self.fail in source:
            raise RuntimeError("verification failed")
        with self.lock:
            self.copied.append(source)
        return "copied"

    def delete_object(self, key: str) -> None:
        self.deleted.append(key)


def _run_restore(fake: FakeR2):
    sys.modules["integrations.r2_storage"] = fake  # type: ignore[assignment]
    sys.modules["integrations.source_uploads"] = types.SimpleNamespace(
        get_source_upload=lambda key: {"status": "verified"}, rekey_source_upload=lambda *a, **k: None)
    import reset_and_rerun
    with redirect_stdout(io.StringIO()):
        return reset_and_rerun._restore_r2_sources_to_raw()


def test_reset_copies_in_parallel_and_deletes_only_after_every_copy_verified() -> None:
    fake = FakeR2([f"s{i}.mp4" for i in range(12)])
    start = time.monotonic()
    assert _run_restore(fake) == 12
    elapsed = time.monotonic() - start
    assert fake.peak > 1 and elapsed < 12 * 0.15 * 0.6, (fake.peak, elapsed)
    assert sorted(fake.deleted) == sorted(fake.copied) and len(fake.deleted) == 12


def test_one_failed_verification_deletes_nothing() -> None:
    fake = FakeR2([f"s{i}.mp4" for i in range(8)], fail="s3.mp4")
    try:
        _run_restore(fake)
    except RuntimeError as exc:
        assert "processed/ was not touched" in str(exc), exc
    else:
        raise AssertionError("a failed verification must abort the reset")
    assert fake.deleted == [], fake.deleted


def test_run_diagnostics_digest_is_readable_bounded_and_never_fails() -> None:
    import print_run_diagnostics as diag
    with tempfile.TemporaryDirectory() as tmp:
        debug = Path(tmp) / "pipeline-debug"
        debug.mkdir()
        (debug / "stage_timings.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"stage": "render_reels", "seconds": 300.0, "athlete": "a"}, {"stage": "render_reels", "seconds": 100.0},
            {"stage": "qa_gate", "seconds": 40.0}]) + "\nnot json\n")
        (debug / "llm_cost_calls.jsonl").write_text(json.dumps(
            {"label": "analyzer.x", "model": "gemini-2.5-pro", "prompt_tokens": 10, "thinking_tokens": 2, "cost_usd": 0.5}) + "\n")
        (debug / "candidate_decision_ledger.json").write_text(json.dumps({
            "selected_count": 1, "discarded_count": 1, "unmatched_selector_selected_count": 1,
            "candidates": [
                {"selected": True, "draft_name": "D1", "source_video": "a.MP4", "person_id": "person_A",
                 "source_window": {"start": 1, "end": 9}, "event_type": "ride", "athlete_id": "ath_1", "matched_via_window_overlap": True},
                {"discarded": True, "discard_cause": "selected_by_selector_not_emitted_as_draft", "source_video": "b.MP4",
                 "person_id": "person_B", "source_window": {"start": 5, "end": 15}}]}))
        (debug / "athlete_coverage_report.json").write_text(json.dumps({
            "summary": {"athlete_accountability_rate": 0.5},
            "athletes": [{"athlete_cluster_id": "b.MP4::person_B", "candidate_action_count": 1, "selected_action_count": 0,
                          "coverage_requirement_met": False, "no_output_reason": "unresolved_selection_path"}]}))
        (debug / "framing_decisions.jsonl").write_text(json.dumps(
            {"mode": "contain", "reason": "default", "athlete_height_ratio": 0.08}) + "\n")
        (debug / "publishable_reel_gate_result.json").write_text(json.dumps({"passed": False, "errors": ["x: Part 1 did not pass final QA"] * 3}))
        (debug / "run_quality_report.json").write_text(json.dumps({
            "status": "fail",
            "alerts": [{"metric": "bbox_out_of_bounds_rate", "severity": "hard_block", "reason": "one or more detections have invalid bboxes"}],
            "bug_classifications": [{"code": "BUG_MIXED_SUBJECT_LIKELY", "evidence": "1 mixed-subject source-window(s)"}],
            "mixed_subject_likely_windows": [{"draft": "DRAFT_a.mp4", "primary_track_id": "7", "primary_track_dominance_ratio": 0.4}]
        }))
        os.environ["TMP_DIR"] = tmp
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                assert diag.main() == 0
            text = buffer.getvalue()
        finally:
            os.environ.pop("TMP_DIR", None)
    for needle in ("render_reels", "400", "analyzer.x", "selected_by_selector_not_emitted_as_draft", "[overlap-matched]",
                   "unresolved clusters: 1", "modes: contain=1", "3 × Part 1 did not pass final QA",
                   "status=fail alerts=1 bugs=1", "bbox_out_of_bounds_rate", "BUG_MIXED_SUBJECT_LIKELY",
                   "violations (1 mixed-subject):", "DRAFT_a.mp4", "primary_track=7"):
        assert needle in text, (needle, text)
    with tempfile.TemporaryDirectory() as empty:           # nothing written at all: still exit 0
        os.environ["TMP_DIR"] = empty
        try:
            with redirect_stdout(io.StringIO()):
                assert diag.main() == 0
        finally:
            os.environ.pop("TMP_DIR", None)


def test_workflow_prints_diagnostics_even_when_the_run_fails() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pipeline-run.yml").read_text()
    block = workflow[workflow.index("Print run diagnostics to the job log"):]
    block = block.split("- name:")[1] if block.count("- name:") > 1 else block
    head = workflow[workflow.index("Print run diagnostics to the job log") - 30:workflow.index("scripts/print_run_diagnostics.py") + 40]
    assert "if: always()" in head and "continue-on-error: true" in head, head


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS render/reset/diagnostics contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
