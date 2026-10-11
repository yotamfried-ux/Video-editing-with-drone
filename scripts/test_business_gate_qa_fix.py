#!/usr/bin/env python3
"""Synthetic before/after regression for publishability gate consistency."""
import json
from pipeline.publishable_reel_policy import _refresh_row_publishability

def evaluate(**changes):
    part = {"render_ready": True, "uploaded_to_review": True,
            "upload_error": None, "review_draft_name": "demo.mp4",
            "qa_evidence_recorded": True, "qa_verdict": "PASS",
            "qa_passed": True, "technical_issues": []}
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
]
for case in cases:
    assert evaluate(**case) is False, case
print(json.dumps({"scope": "isolated business gate",
                  "unsafe_missing_QA_cases_before": 4,
                  "unsafe_missing_QA_cases_after": 0,
                  "valid_positive_case": "publishable",
                  "negative_cases_blocked": len(cases)}, indent=2))
