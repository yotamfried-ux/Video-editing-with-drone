"""Editorial value ranker — additive, reporting-only (self-learning-loop Phase 6).

Combines pipeline/candidate_ledger.py's existing infer_value_labels() (per-event
value labels) with pipeline/narrative_policy.py's existing quality_score() into
one composite score per candidate, surfaced in the candidate decision ledger for
visibility.

Deliberately scoped the same way PQ-008's `_partition_events` was deferred in this
remediation pass: this module patches pipeline.candidate_ledger.build_candidate_entry
to ADD a score field to each ledger entry. It never touches
pipeline.stages.editor._partition_events, _group_dur, or any live event
selection/partitioning/slowmo behavior. Changing what actually gets selected or how
long a reel runs based on this score is real reel-length/pacing risk that needs a
real pipeline run to validate safely -- exactly the reasoning already recorded for
_partition_events -- and is out of scope here.
"""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_editorial_value_ranker_installed"

# Maps the audit's requested "value categories"
# (docs/audit/self-learning-loop-audit-20260706.md Phase 6: long ride, clean
# takeoff, turn/cutback, fall/recovery, high-five/social moment, strong ending)
# onto pipeline/candidate_ledger.py's existing VALUE_LABELS -- the source of
# truth for the label vocabulary. Two requested categories (clean_takeoff,
# strong_ending) have no reliable existing signal to key off: no analyzer event
# type or keyword term identifies them today, and no invented heuristic here
# would be evidence-based rather than a guess -- left out rather than faked.
CATEGORY_LABELS: dict[str, str] = {
    "long_ride": "FULL_RIDE",
    "turn_cutback": "BIG_TURN",
    "fall_recovery": "FALL",
    "social_moment": "SOCIAL_MOMENT",
    "high_five": "HIGH_FIVE",
    "good_style": "GOOD_STYLE",
}

# Labels that indicate a real product problem with the candidate rather than
# editorial value -- these subtract from the score instead of adding to it.
_NEGATIVE_LABELS = {"BAD_CROP", "WRONG_ATHLETE", "DUPLICATE_ATHLETE", "DUPLICATE_MOMENT", "CUT_TOO_EARLY", "BORING"}
_CATEGORY_BONUS = 1.0
_NEGATIVE_PENALTY = 1.5


def score_editorial_value(event: dict[str, Any]) -> dict[str, Any]:
    """Compute a composite editorial value score for one event/candidate.

    Purely additive metadata -- does not read or write anything selection or
    partitioning depends on.
    """
    from pipeline.candidate_ledger import infer_value_labels
    from pipeline.narrative_policy import quality_score

    labels = infer_value_labels(event)
    base = quality_score(event)
    category_hits = sorted(name for name, label in CATEGORY_LABELS.items() if label in labels)
    bonus = _CATEGORY_BONUS * len(category_hits)
    penalty = _NEGATIVE_PENALTY * sum(1 for label in labels if label in _NEGATIVE_LABELS)
    return {
        "editorial_value_score": round(base + bonus - penalty, 3),
        "editorial_value_categories": category_hits,
    }


def _patch_candidate_ledger(module: Any) -> None:
    if getattr(module, _INSTALLED_FLAG, False):
        return
    original = module.build_candidate_entry

    def build_with_value_score(event: dict[str, Any], index: int, *, draft_name: str, decision: str | None = None, reason: str | None = None) -> dict[str, Any]:
        entry = original(event, index, draft_name=draft_name, decision=decision, reason=reason)
        entry.update(score_editorial_value(event))
        return entry

    module.build_candidate_entry = build_with_value_score
    setattr(module, _INSTALLED_FLAG, True)


def install() -> None:
    module = sys.modules.get("pipeline.candidate_ledger")
    if module is None:
        import pipeline.candidate_ledger as module  # type: ignore[no-redef]
    _patch_candidate_ledger(module)
