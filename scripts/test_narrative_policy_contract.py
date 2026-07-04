#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def ev(name, score, visible=1.0, confidence=1.0, peak=6.0, identity="high"):
    item = {"id": name, "score": score, "start": 0.0, "end": 8.0, "visible_ratio": visible, "perception_confidence": confidence, "identity_confidence": identity, "window_validation_status": "valid", "track_id": name}
    if peak is not None:
        item["peak_time"] = peak
    return item


def main() -> int:
    from pipeline.narrative_policy import choose_climax, order_events, quality_score

    text = (ROOT / "pipeline/narrative_policy.py").read_text(encoding="utf-8")
    boot = (ROOT / "scripts/sitecustomize.py").read_text(encoding="utf-8")
    for token in ["def quality_score", "def choose_climax", "_disable_teaser", "cut_clip_without_unqualified_teaser", "evidence_penalty"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")
    if "from pipeline.narrative_policy import install" not in boot:
        raise SystemExit("narrative policy is not bootstrapped")

    bad_high = ev("bad_high", 10, visible=0.1, confidence=0.95)
    good_lower = ev("good_lower", 8, visible=0.9, confidence=0.9)
    middle = ev("middle", 7, visible=0.8)
    if choose_climax([bad_high, good_lower]) is not good_lower:
        raise SystemExit("low-visibility high score became climax")
    if quality_score(good_lower) <= quality_score(bad_high):
        raise SystemExit("composite quality did not outrank weak high score")
    ordered = order_events([bad_high, good_lower, middle])
    if ordered[-1] is not good_lower:
        raise SystemExit("qualified composite climax is not last")
    if ordered[0] is bad_high:
        raise SystemExit("weak high-score event became opener")

    weak = [ev("weak_a", 6, visible=0.2), ev("weak_b", 6, confidence=0.1), ev("weak_c", 5, identity="low")]
    if choose_climax(weak) is not None:
        raise SystemExit("weak set should not have a climax")

    print("Narrative policy contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
