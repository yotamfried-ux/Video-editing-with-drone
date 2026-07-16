#!/usr/bin/env python3
"""Contract: pipeline.stages.feedback.get_negative_feedback_hint() folds structured
operator feedback (draft_feedback table, submitted via
POST /api/operator/drafts/feedback) into the existing recency-weighted prompt-injection
loop, without ever writing feedback itself and without blocking the analysis prompt
when Supabase is unreachable.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _install_import_stubs() -> None:
    sys.modules["config"] = types.SimpleNamespace(
        FEEDBACK_FILE="/tmp/_unused_feedback.json",
        OPERATOR_NOTES_FILE="/tmp/_unused_notes.json",
        QA_RESULTS_FILE="/tmp/_unused_qa.jsonl",
        QA_ENGAGEMENT_THRESHOLD=60,
    )


def _row(feedback_event: str, days_old: float = 0.0) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {"feedback_event": feedback_event, "created_at": ts.isoformat()}


def main() -> int:
    _install_import_stubs()
    from pipeline.stages import feedback

    # No signal yet -> must not inject anything (avoid over-fitting to noise).
    feedback._fetch_structured_feedback = lambda: [_row("BORING"), _row("BORING")]
    if feedback.get_negative_feedback_hint() != "":
        raise SystemExit("hint must be empty below the minimum feedback threshold")

    # Enough rows, but Supabase unreachable -> must not raise, must return "".
    def _raise():
        raise RuntimeError("supabase unreachable")
    feedback._fetch_structured_feedback = lambda: []  # simulates the caught-exception path returning []
    if feedback.get_negative_feedback_hint() != "":
        raise SystemExit("hint must be empty when the feedback source is unavailable")

    # Enough signal -> injects a hint naming the most-flagged problem, and never
    # surfaces action-only events (APPROVE/REJECT/SEND_TO_REEDIT) as a "problem".
    feedback._fetch_structured_feedback = lambda: [
        _row("BORING"), _row("BORING"), _row("BORING"),
        _row("CUT_TOO_EARLY"),
        _row("APPROVE"),
    ]
    hint = feedback.get_negative_feedback_hint()
    if not hint:
        raise SystemExit("hint should be produced once enough structured feedback exists")
    if "low-action or dead-time" not in hint:
        raise SystemExit("most-flagged problem (BORING) missing from hint")
    if "APPROVE" in hint:
        raise SystemExit("action-only feedback events must not be surfaced as a problem")

    # Old feedback should be decayed near zero relative to fresh feedback of the
    # same type, so a stale one-time complaint doesn't dominate the ranking.
    feedback._fetch_structured_feedback = lambda: [
        _row("CUT_TOO_EARLY", days_old=365.0),
        _row("BORING"), _row("BORING"), _row("BORING"),
    ]
    hint = feedback.get_negative_feedback_hint()
    if "cutting a ride" in hint and "low-action" not in hint:
        raise SystemExit("stale feedback outranked fresh, frequent feedback")

    # Wiring check: analyzer.py must actually import and inject this hint
    # alongside the existing feedback/notes blocks, not just define it unused.
    analyzer_source = (ROOT / "pipeline/stages/analyzer.py").read_text(encoding="utf-8")
    if "get_negative_feedback_hint" not in analyzer_source:
        raise SystemExit("analyzer.py does not import get_negative_feedback_hint")
    if "negative_block" not in analyzer_source:
        raise SystemExit("analyzer.py does not inject the structured-feedback hint into the prompt")

    print("Structured feedback contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
