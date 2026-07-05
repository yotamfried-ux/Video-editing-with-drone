"""Helpers for QA state normalization."""
from __future__ import annotations

def needs_review(qa):
    text = str(qa.get("overall", "")).strip().lower()
    return qa.get("qa_review_required") is True or (qa.get("verdict") == "PASS" and text in {"qa skipped", "qa unavailable"})

def mark_review_required(qa, reason="qa_result_unavailable"):
    if not needs_review(qa):
        return qa
    defects = list(qa.get("defects", []) or [])
    defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "minor", "note": reason})
    return {**qa, "verdict": "FAIL", "qa_review_required": True, "overall": reason, "engagement_score": 0, "defects": defects}
