#!/usr/bin/env python3
"""Regression simulations for production QA failure modes from run 37522019157."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pipeline import source_evidence_runner as runner


def _context():
    return {"source_windows": [{"source": "source.mp4", "source_start": 1, "source_end": 8, "duplicate_evidence": []}]}


class Model:
    calls = 0
    def __init__(self, *args, **kwargs): pass
    def generate_content(self, *args, **kwargs):
        Model.calls += 1
        if Model.calls == 1:
            return SimpleNamespace(text='{"engagement_score": 80, "defects": [}')
        return SimpleNamespace(text='\x60\x60\x60json\n{"engagement_score":80,"defects":[],"overall":"good","content":{}}\n\x60\x60\x60')


def _analyzer():
    return SimpleNamespace(
        _check_technical_compliance=lambda path: ({"duration": 10}, True, []),
        _upload_video=lambda path: "remote:" + path,
        _delete_video=lambda item: None,
        _QA_REEL_PROMPT="judge",
        _QA_REEL_MODEL="fake",
        genai=SimpleNamespace(GenerativeModel=Model),
        _with_retry=lambda fn: fn(),
        _persist_qa_result=lambda *args: None,
    )


def test_malformed_response_retries_without_claiming_upload_failure():
    Model.calls = 0
    original = lambda *a, **k: {"verdict": "FAIL", "defects": [], "overall": "fallback"}
    with patch.object(runner, "make_source_clips", return_value=["clip.mp4"]), patch.object(runner.os, "remove", return_value=None):
        result = runner.with_source_evidence(_analyzer(), original, "reel.mp4", context=_context(), sport="surfing", athlete_label="target")
    assert Model.calls == 2, Model.calls
    assert result["verdict"] == "PASS", result
    assert result["source_evidence_visual_uploaded"] is True


def test_parse_failure_remains_fail_closed_and_is_classified():
    class BadModel(Model):
        def generate_content(self, *args, **kwargs):
            return SimpleNamespace(text="{not json")
    analyzer = _analyzer()
    analyzer.genai = SimpleNamespace(GenerativeModel=BadModel)
    original = lambda *a, **k: {"verdict": "FAIL", "defects": [], "overall": "fallback"}
    with patch.object(runner, "make_source_clips", return_value=["clip.mp4"]), patch.object(runner.os, "remove", return_value=None):
        result = runner.with_source_evidence(analyzer, original, "reel.mp4", context=_context())
    assert result["verdict"] == "FAIL"
    assert result["source_evidence_visual_uploaded"] is True
    assert result["qa_failure_reason"] == "response_parse_failed"
    assert "upload failed" not in result["defects"][-1]["note"].lower()


def test_staged_path_gets_manifest_alias_at_creation():
    import pipeline.publishable_reel_policy as policy
    import pipeline.publishable_runtime_integrity as integrity
    from pipeline.context_qa_long_video import _stage_reel_candidate
    integrity._patch_policy()
    with tempfile.TemporaryDirectory() as d:
        manifest = Path(d) / "manifest.json"
        original = Path(d) / "target.mp4"
        original.write_bytes(b"video")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()
        policy.record_athlete_outcome(
            sport="surfing", athlete_label="target", final_reels=[str(original)],
            events_by_reel={str(original): [{"athlete_id":"a","start":1,"end":8,"type":"ride","score":8,"_src":"source.mp4"}]},
            flagged_paths=set(), specs_getter=lambda p: {"has_audio":True,"duration":7,"width":1080,"height":1920,"aspect":9/16},
        )
        staged = _stage_reel_candidate(str(original), d, 0, "DRAFT_target.mp4")
        payload = json.loads(manifest.read_text())
        aliases = payload["athletes"][0]["parts"][0]["upload_path_aliases"]
        assert os.path.abspath(staged) in aliases


if __name__ == "__main__":
    test_malformed_response_retries_without_claiming_upload_failure()
    test_parse_failure_remains_fail_closed_and_is_classified()
    test_staged_path_gets_manifest_alias_at_creation()
    print("Production QA failure-mode simulations passed")
