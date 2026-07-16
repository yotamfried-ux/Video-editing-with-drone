"""
pipeline/stages/feedback.py — Approval-based editing feedback loop.

Records approved event types AND per-event editing parameters (zoom, slowmo)
from delivered reels, then injects weighted historical patterns into future
Gemini prompts so the system learns both WHAT to select and HOW to edit.

Weighting: 30-day half-life — early sessions (when standards were lower)
fade automatically, so the system re-calibrates as quality improves.
"""

import json
import logging
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

_HALF_LIFE_DAYS = 30   # 50% weight after 30 days → old approvals fade naturally
_MIN_APPROVALS  = 3    # minimum per-sport before injecting (avoids early-approval noise)
_TOP_N          = 6    # inject top-N label×edit combos per sport in prompt


# ── Storage helpers ────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        with open(config.FEEDBACK_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"approvals": []}


def _save(data: dict) -> None:
    tmp = config.FEEDBACK_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, config.FEEDBACK_FILE)


# ── Public API ─────────────────────────────────────────────────────────────

def record_approval(
    sport: str,
    events: list[dict],
    source_quality: dict | None = None,
) -> None:
    """
    Record operator approval of a reel.

    events: list of dicts with at least {"type": str, "edit": {...optional}}
    """
    data = _load()
    entry: dict[str, Any] = {
        "ts":    datetime.now(timezone.utc).isoformat(),
        "sport": sport.lower(),
        "events": [
            {
                "type": str(ev.get("type", "")).lower(),
                "edit": {
                    "zoom":   float(ev.get("edit", {}).get("zoom", 1.0)),
                    "slowmo": bool(ev.get("edit", {}).get("slowmo", False)),
                    "focus":  str(ev.get("edit", {}).get("focus", "peak")),
                },
            }
            for ev in events
            if ev.get("type")
        ],
    }
    if source_quality:
        entry["source_quality"] = source_quality
    data["approvals"].append(entry)
    _save(data)

    labels = [ev["type"] for ev in entry["events"]]
    sport_count = sum(1 for a in data["approvals"] if a.get("sport") == sport.lower())
    logger.info("Feedback recorded: sport=%s labels=%s (total for sport: %d)",
                sport, labels, sport_count)
    print(f"🏷️  Feedback: {sport} — {', '.join(labels)} ({sport_count} total for {sport})")


def _decay_weight(ts_iso: str) -> float:
    try:
        ts = datetime.fromisoformat(ts_iso)
        days_old = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    except Exception:
        days_old = 0.0
    return math.exp(-days_old * math.log(2) / _HALF_LIFE_DAYS)


def _label_edit_scores(sport: str) -> dict[str, float]:
    """
    Returns recency-weighted scores per (label, edit_signature) pair.
    edit_signature is compact: "zoom×1.4+slowmo" or "zoom×1.0".
    """
    data = _load()
    scores: dict[str, float] = {}
    for entry in data["approvals"]:
        if entry.get("sport", "").lower() != sport.lower():
            continue
        w = _decay_weight(entry.get("ts", ""))
        for ev in entry.get("events", []):
            label = ev.get("type", "")
            if not label:
                continue
            edit  = ev.get("edit", {})
            zoom  = float(edit.get("zoom", 1.0))
            sm    = bool(edit.get("slowmo", False))
            sig   = f"zoom×{zoom:.1f}" + ("+slowmo" if sm else "")
            key   = f"{label}({sig})"
            scores[key] = scores.get(key, 0.0) + w
    return scores


def get_all_label_injections() -> str:
    """
    Returns a prompt block for ALL sports with >= _MIN_APPROVALS approvals.
    Returns "" if no sport has enough data yet — no injection until there is signal.
    """
    data = _load()
    sports: dict[str, int] = {}
    for entry in data["approvals"]:
        s = entry.get("sport", "")
        if s:
            sports[s] = sports.get(s, 0) + 1

    lines: list[str] = []
    for sport in sorted(sports):
        if sports[sport] < _MIN_APPROVALS:
            continue
        scores = _label_edit_scores(sport)
        if not scores:
            continue
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:_TOP_N]
        top_str = ", ".join(f"{k} ×{v:.1f}pts" for k, v in top)
        lines.append(f"  {sport}: {top_str}")

    if not lines:
        return ""

    return (
        "\nOPERATOR APPROVAL HISTORY — use to guide both event selection"
        " AND per-event edit decisions:\n"
        + "\n".join(lines)
        + "\nScores are recency-weighted (30-day half-life). "
        "Prefer edit styles with higher scores; they reflect what the operator approves.\n"
    )


# ── QA calibration (ties reel-QA to the approval/performance signal) ─────────

def _load_qa_results() -> list[dict]:
    """Read qa_results.jsonl (one JSON object per line). Returns [] if missing."""
    path = getattr(config, "QA_RESULTS_FILE", "qa_results.jsonl")
    rows: list[dict] = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return rows


_QA_TOP_N = 5  # approved patterns to surface in QA calibration hint


def get_qa_calibration_hint(sport: str) -> str:
    """Aggregate, sport-level calibration context for the reel-QA prompt.

    Returns a short hint string (or "" when there is not enough signal yet).
    Intentionally aggregate — conveys approved moment-types + engagement range,
    NOT the editing instructions for the reel under review (independence preserved).
    """
    data = _load()
    approvals = sum(1 for a in data["approvals"] if a.get("sport", "").lower() == sport.lower())
    if approvals < _MIN_APPROVALS:
        return ""

    # Approved event+edit patterns (recency-weighted) — what the operator historically liked.
    label_scores = _label_edit_scores(sport)
    top_patterns: list[str] = []
    if label_scores:
        top = sorted(label_scores.items(), key=lambda x: x[1], reverse=True)[:_QA_TOP_N]
        top_patterns = [k for k, _ in top]

    # Engagement distribution from past QA runs (if available).
    qa_scores = [
        r["engagement_score"] for r in _load_qa_results()
        if r.get("sport", "").lower() == sport.lower()
        and isinstance(r.get("engagement_score"), (int, float))
    ]

    lines: list[str] = [
        f"\nCALIBRATION CONTEXT (operator has approved {approvals} {sport} reel(s)):"
    ]
    if top_patterns:
        lines.append(
            f"  Approved moment-types (most valued first): {', '.join(top_patterns)}."
        )
        lines.append(
            "  When evaluating, check whether the reel contains these kinds of moments."
        )
    if qa_scores:
        med = round(statistics.median(qa_scores))
        lines.append(
            f"  Past {sport} reels scored a median engagement of {med}/100 — calibrate to this scale."
        )
    else:
        lines.append("  Favor qualities present in operator-approved reels.")

    return "\n".join(lines) + "\n"


def suggest_qa_threshold() -> dict:
    """Suggest an engagement-score threshold for QA, advisory/CLI only.

    Prefers REAL performance data (qa_results rows with actual_performance set);
    falls back to the engagement-score distribution when no labeled data exists yet.
    """
    rows = _load_qa_results()
    labeled = [r for r in rows if r.get("actual_performance") is not None]
    current = getattr(config, "QA_ENGAGEMENT_THRESHOLD", 60)

    if labeled:
        # Data-driven: threshold = 25th percentile of engagement among reels that
        # actually performed (real IG/TikTok metrics ingested later).
        scores = sorted(
            r["engagement_score"] for r in labeled
            if isinstance(r.get("engagement_score"), (int, float))
        )
        if scores:
            idx = max(0, int(len(scores) * 0.25) - 1)
            return {"suggested": scores[idx], "method": "actual_performance",
                    "sample": len(scores), "current": current}

    scores = sorted(
        r["engagement_score"] for r in rows
        if isinstance(r.get("engagement_score"), (int, float))
    )
    if not scores:
        return {"suggested": current, "method": "no_data", "sample": 0, "current": current}
    # Provisional: 40th percentile so we flag clearly-weak reels without over-rejecting.
    idx = max(0, int(len(scores) * 0.40) - 1)
    return {"suggested": scores[idx], "method": "distribution_provisional",
            "sample": len(scores), "current": current}


# ── Structured operator feedback (draft_feedback table) ─────────────────────
#
# Complements the binary approve-only loop above with the negative/problem
# labels operators can attach on the Review screen (see
# web-api POST /api/operator/drafts/feedback and
# pipeline/candidate_ledger.py's OPERATOR_FEEDBACK_EVENTS, the source of truth
# for this vocabulary). Read-only from the pipeline's perspective: this module
# never writes draft_feedback rows, only folds them into the same
# recency-weighted prompt-injection mechanism used for approvals.

_STRUCTURED_MIN_FEEDBACK = 3   # avoid over-fitting to a single complaint
_STRUCTURED_TOP_N = 5

# Problem-type feedback events worth surfacing as a "watch out for" hint.
# APPROVE/REJECT/SEND_TO_REEDIT are actions, not problem labels, and are
# already reflected in the approval-based loop above.
_PROBLEM_EVENTS = (
    "WRONG_ATHLETE", "DUPLICATE_ATHLETE", "MULTI_PERSON_CLIP",
    "CUT_TOO_EARLY", "BAD_CROP", "BORING", "MISSING_GOOD_MOMENT",
)

_PROBLEM_EVENT_HINTS = {
    "WRONG_ATHLETE": "selecting the wrong athlete",
    "DUPLICATE_ATHLETE": "the same athlete appearing across separate drafts",
    "MULTI_PERSON_CLIP": "another visible person leaking into a single-athlete clip",
    "CUT_TOO_EARLY": "cutting a ride/moment before its natural finish",
    "BAD_CROP": "unacceptable framing/crop",
    "BORING": "low-action or dead-time moments",
    "MISSING_GOOD_MOMENT": "missing a moment the operator considered valuable",
}


def _fetch_structured_feedback() -> list[dict]:
    try:
        from integrations.supabase_uploader import fetch_recent_draft_feedback
        return fetch_recent_draft_feedback()
    except Exception:
        logger.warning("Could not fetch structured draft feedback; skipping prompt injection", exc_info=True)
        return []


def get_negative_feedback_hint() -> str:
    """Recency-weighted summary of recent structured operator complaints.

    Returns "" until there is enough signal (_STRUCTURED_MIN_FEEDBACK rows) or
    if Supabase is unreachable — never blocks or fails the analysis prompt.
    """
    rows = _fetch_structured_feedback()
    if len(rows) < _STRUCTURED_MIN_FEEDBACK:
        return ""

    scores: dict[str, float] = {}
    for row in rows:
        event = str(row.get("feedback_event") or "")
        if event not in _PROBLEM_EVENTS:
            continue
        w = _decay_weight(str(row.get("created_at") or ""))
        scores[event] = scores.get(event, 0.0) + w

    if not scores:
        return ""

    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:_STRUCTURED_TOP_N]
    lines = [f"  - Avoid {_PROBLEM_EVENT_HINTS.get(event, event.lower())} (flagged ×{score:.1f}pts recently)" for event, score in top]
    return (
        "\nRECENT OPERATOR FEEDBACK — avoid repeating these flagged problems:\n"
        + "\n".join(lines)
        + "\nScores are recency-weighted (30-day half-life); higher means more recent/frequent.\n"
    )


def record_operator_note(draft_name: str, note: str) -> None:
    """
    Attach a free-text operator note to a specific draft reel.

    Notes are injected into the Gemini analysis prompt the next time the pipeline
    re-processes the same footage, giving Gemini explicit editorial direction.

    draft_name: the DRAFT_ filename (e.g. "DRAFT_surfer_Coral_Sallas_20260610.mp4")
    note: plain text instruction (e.g. "Bad opening hook — pick a more dramatic first clip")
    """
    path = getattr(config, "OPERATOR_NOTES_FILE", "operator_notes.json")
    try:
        with open(path) as f:
            notes: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        notes = {}
    key = Path(draft_name).stem  # strip extension for robustness
    notes[key] = {
        "note": note,
        "ts":   datetime.now(timezone.utc).isoformat(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    print(f"📝 Note saved for '{key}': {note[:80]}")
    logger.info("Operator note saved: %s", key)


def get_operator_notes(draft_name: str | None = None) -> str:
    """
    Return operator notes as a formatted prompt block.

    If draft_name is given, returns notes specific to that draft; otherwise
    returns all pending notes (for fresh footage with no prior draft name).
    Returns "" when no notes exist.
    """
    path = getattr(config, "OPERATOR_NOTES_FILE", "operator_notes.json")
    try:
        with open(path) as f:
            notes: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    if not notes:
        return ""

    if draft_name:
        key = Path(draft_name).stem
        entry = notes.get(key)
        if not entry:
            return ""
        items = [(key, entry)]
    else:
        items = list(notes.items())

    lines = ["\nOPERATOR EDITING NOTES — apply these instructions for the footage:"]
    for key, entry in items:
        ts  = entry.get("ts", "")[:10]
        txt = entry.get("note", "").strip()
        if txt:
            lines.append(f"  [{ts}] {txt}")
    if len(lines) == 1:
        return ""
    lines.append(
        "These are direct instructions from the operator who reviewed the previous output."
        " Adjust event selection, ordering, and edit parameters accordingly.\n"
    )
    return "\n".join(lines)


def clear_operator_note(draft_name: str) -> bool:
    """Remove the note for a draft after it has been acted on. Returns True if found."""
    path = getattr(config, "OPERATOR_NOTES_FILE", "operator_notes.json")
    try:
        with open(path) as f:
            notes: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    key = Path(draft_name).stem
    if key not in notes:
        return False
    del notes[key]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    logger.info("Operator note cleared: %s", key)
    return True


def get_stats() -> dict:
    """Return summary stats about the feedback database."""
    data = _load()
    sports: dict[str, int] = {}
    last_ts = ""
    for entry in data["approvals"]:
        s = entry.get("sport", "unknown")
        sports[s] = sports.get(s, 0) + 1
        if entry.get("ts", "") > last_ts:
            last_ts = entry["ts"]
    return {
        "total_approvals": len(data["approvals"]),
        "by_sport":        sports,
        "last_approval":   last_ts[:10] if last_ts else "—",
    }
