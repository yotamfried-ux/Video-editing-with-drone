"""Helpers for QA state normalization."""
from __future__ import annotations

_UNGRADED_TEXT = {"qa skipped", "qa unavailable"}


def _ungraded(qa):
    """True when QA never produced a real grade (skipped/unavailable), as opposed to a graded FAIL."""
    text = str(qa.get("overall", "")).strip().lower()
    return qa.get("verdict") not in {"PASS", "FAIL"} or text in _UNGRADED_TEXT


def needs_review(qa):
    text = str(qa.get("overall", "")).strip().lower()
    return qa.get("qa_review_required") is True or (qa.get("verdict") == "PASS" and text in _UNGRADED_TEXT)


def mark_review_required(qa, reason="qa_result_unavailable"):
    if not needs_review(qa):
        return qa
    defects = list(qa.get("defects", []) or [])
    if _ungraded(qa):
        defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": reason})
        return {**qa, "verdict": "FAIL", "qa_review_required": True, "overall": reason, "engagement_score": 0, "defects": defects}
    # A real graded result flagged for review (e.g. critical source-evidence defects): keep the
    # model's score, summary and defects so operators see why it failed; only force FAIL.
    if not any(str(d.get("type", "")).upper() == "QA_REVIEW_REQUIRED" for d in defects if isinstance(d, dict)):
        defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": "critical QA defects require operator review"})
    return {**qa, "verdict": "FAIL", "qa_review_required": True, "defects": defects}
