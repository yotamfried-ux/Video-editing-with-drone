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
from datetime import datetime, timezone
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
