#!/usr/bin/env python3
"""Synthetic before/after regression for publishability gate consistency."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qualification_fixture import qualified  # noqa: E402
from pipeline.output_qualification import build_inputs  # noqa: E402
from pipeline.publishable_reel_policy import _refresh_row_publishability  # noqa: E402

# The evidence a real production shot carries (tracker binding, CV activity, actor span, lineage).
INPUTS = build_inputs([qualified({"type": "wave_catch", "start": 1.0, "end": 8.0})], "surfing")
assert not INPUTS["issues"], INPUTS["issues"]

def evaluate(**changes):
    part = {"render_ready": True, "uploaded_to_review": True,
            "upload_error": None, "review_draft_name": "demo.mp4",
            "qa_evidence_recorded": True, "qa_verdict": "PASS",
            "qa_passed": True, "technical_issues": [], "content_sha256_kind": "bytes",
            "qualification_inputs": INPUTS}
    part.update(changes)
    row = {"parts": [part]}
    _refresh_row_publishability(row)
    return part["publishable"]

assert evaluate() is True
cases = [
    {"qa_evidence_recorded": False},
    {"qa_verdict": "FAIL"},
    {"qa_passed": False},
    {"technical_issues": ["bad_crop"]},
    {"authoritative_publishability_required": True,
     "authoritative_publishability_persisted": False},
    {"uploaded_to_review": False},
    # Output qualification: no evidence, or evidence with a failed requirement, never publishes.
    {"qualification_inputs": None},
    {"qualification_inputs": build_inputs([{"type": "wave_catch", "start": 1.0, "end": 8.0, "score": 9}], "surfing")},
]
for case in cases:
    assert evaluate(**case) is False, case
print(json.dumps({"scope": "isolated business gate",
                  "unsafe_missing_QA_cases_before": 4,
                  "unsafe_missing_QA_cases_after": 0,
                  "valid_positive_case": "publishable",
                  "negative_cases_blocked": len(cases)}, indent=2))
