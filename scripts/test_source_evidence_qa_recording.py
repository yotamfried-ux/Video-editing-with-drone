#!/usr/bin/env python3
"""Regression: real source-evidence QA must persist the result used by final QA gate.

No network, videos, Gemini, or production writes: the provider is a deterministic fake.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pipeline.source_evidence_runner as runner
from pipeline.publishable_pending_scope import (
    activate_next_scope, create_pending_scope, release_scope,
)
from pipeline.publishable_qa_evidence import clear_recorded_qa, get_recorded_qa


class FakeResponse:
    text = json.dumps({"content": {}, "defects": [], "engagement_score": 93, "overall": "QA clear"})


class FakeModel:
    def generate_content(self, *_args, **_kwargs):
        return FakeResponse()


class FakeGenAI:
    def GenerativeModel(self, **_kwargs):
        return FakeModel()


class FakeAnalyzer:
    _QA_REEL_PROMPT = "Inspect this reel"
    _QA_REEL_MODEL = "fake"
    genai = FakeGenAI()

    def _check_technical_compliance(self, _path):
        return {"duration": 9, "width": 1080, "height": 1920}, True, []

    def _upload_video(self, path):
        return {"uploaded_test_path": path}

    def _delete_video(self, _handle):
        pass

    def _with_retry(self, fn):
        return fn()

    def _persist_qa_result(self, *_args):
        pass


def main() -> None:
    # A successful source-evidence multimodal call bypasses the base QA function.
    # The final manifest evidence must STILL see the same verdict and path.
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        reel = tmp / "final.mp4"
        source = tmp / "source.mp4"
        reel.write_bytes(b"local test stub")
        source.write_bytes(b"local test source stub")
        original_clips = runner.make_source_clips
        runner.make_source_clips = lambda _context: [str(source)]
        token = create_pending_scope("surfing", "athlete one")
        activated = activate_next_scope("surfing", "athlete one")
        assert token == activated
        try:
            result = runner.with_source_evidence(
                FakeAnalyzer(),
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("valid source-evidence result must not need base QA")),
                str(reel),
                sport="surfing",
                athlete_label="athlete one",
                context={"source_windows": [{"source": str(source)}]},
            )
            assert result["verdict"] == "PASS" and result["source_evidence_visual_uploaded"]
            recorded = get_recorded_qa(str(reel), invocation_token=token)
            assert recorded is not None, "source-evidence QA result bypassed final QA evidence recorder"
            assert recorded == result, "recorded QA did not match final verdict used by the gate"
            # A later failed assessment for the same rendered path must replace
            # the evidence (never inherit an earlier PASS).
            FakeResponse.text = json.dumps({
                "content": {},
                "defects": [{"type": "IDENTITY_MISMATCH", "severity": "critical"}],
                "engagement_score": 34,
                "overall": "Wrong athlete",
            })
            failed = runner.with_source_evidence(
                FakeAnalyzer(),
                lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected fallback")),
                str(reel),
                sport="surfing",
                athlete_label="athlete one",
                context={"source_windows": [{"source": str(source)}]},
            )
            assert failed["verdict"] == "FAIL"
            assert get_recorded_qa(str(reel), invocation_token=token) == failed, (
                "latest explicit QA failure must replace older PASS evidence"
            )
        finally:
            clear_recorded_qa(token)
            release_scope(token)
            runner.make_source_clips = original_clips
    print("Source-evidence final QA evidence regression: PASS")


if __name__ == "__main__":
    main()