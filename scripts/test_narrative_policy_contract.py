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
    boot = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    for token in ["def quality_score", "def choose_climax", "_disable_teaser", "cut_clip_without_unqualified_teaser", "evidence_penalty"]:
        if token not in text:
            raise SystemExit(f"missing token: {token}")
    if "pipeline.narrative_policy" not in boot:
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

    # The reel closes on a clip whose action ends inside its recording when it ties with the best clip.
    # Run 42891165218: payoff and loopability were the weak dimensions on every failed reel, and 19 of 22
    # findings were a ride still going when the camera stopped.
    from pipeline import complete_action_window_policy as window_policy

    lengths = {"camera_cut.mp4": 20.0, "resolved.mp4": 12.0, "resolved_weaker.mp4": 12.0}
    original_duration = window_policy._recording_duration
    window_policy._recording_duration = lambda path: lengths.get(str(path))
    try:
        camera_cut = {**ev("camera_cut", 8), "_src": "camera_cut.mp4", "start": 2.0, "end": 18.8}   # 1.2 s left
        resolved = {**ev("resolved", 8), "_src": "resolved.mp4", "start": 0.0, "end": 5.0}           # 7.0 s left
        weaker = {**ev("resolved_weaker", 6), "_src": "resolved_weaker.mp4", "start": 0.0, "end": 5.0}
        if window_policy.ends_with_recording(camera_cut) is not True or window_policy.ends_with_recording(resolved) is not False:
            raise SystemExit("ends_with_recording must follow the recording-end tail rule")
        if window_policy.ends_with_recording({**camera_cut, "_src": "unknown.mp4"}) is not None:
            raise SystemExit("an unknown recording length is not evidence either way")
        if choose_climax([camera_cut, resolved]) is not resolved:
            raise SystemExit("of two equally rated clips the one whose action resolves must close the reel")
        tied_order = order_events([camera_cut, resolved])
        if tied_order[0] is not camera_cut or tied_order[-1] is not resolved:
            raise SystemExit("the camera-cut clip opens the reel, the resolved one closes it")
        if choose_climax([camera_cut, weaker]) is not camera_cut:
            raise SystemExit("a clearly better clip stays the climax even when the camera cut its ending")
        if choose_climax([resolved, weaker]) is not resolved:
            raise SystemExit("with no camera-cut best clip the order is unchanged")
    finally:
        window_policy._recording_duration = original_duration

    print("Narrative policy contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
