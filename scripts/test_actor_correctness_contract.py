#!/usr/bin/env python3
"""actor_correctness: right surfer vs a different person, unverifiable windows, GT interpolation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import actor_correctness as ac  # noqa: E402

SHA = "s" * 64
GT = {SHA: {"fps": 60, "tracks": [
    {"athlete_id": "A", "points": [[f, 0.10 + 0.4 * f / 60, 0.10, 0.20, 0.20] for f in range(0, 61, 6)]},   # keyframes ~every 6 frames, like the real GT
    {"athlete_id": "B", "points": [[f, 0.70, 0.70, 0.20, 0.20] for f in range(0, 61, 6)]}]}}


def preds(track_boxes, frames=(0, 60)):
    samples = [{"src_frame": f, "bbox": dict(zip("xywh", b))} for f, b in track_boxes]
    ev = {"decision": "selected", "start_frame": frames[0], "end_frame": frames[1],
          "outputs": [{"track_id": "7", "event_id": "e", "output_id": "o", "mode": "tracked_crop"}]}
    return {"sources": [{"source_sha256": SHA, "source_video": "v.mp4", "tracks": [{"track_id": "7", "samples": samples}], "events": [ev]}]}


def test_person_inside_the_gt_box_is_the_right_athlete_even_when_much_smaller() -> None:
    small = [(f, (0.12 + 0.4 * f / 60, 0.13, 0.04, 0.06)) for f in range(0, 61, 6)]      # IoU ~0.06, containment 1.0
    row = ac.check(preds(small), GT)[0]
    assert row["followed_ok"] and row["followed_athlete"] == "A", row


def test_other_person_is_not_following_the_athlete() -> None:
    elsewhere = [(f, (0.72, 0.72, 0.04, 0.06)) for f in range(0, 61, 6)]
    row = ac.check(preds(elsewhere), GT)[0]
    assert row["followed_athlete"] == "B" and row["followed_ok"], row                       # followed B, not A
    nowhere = [(f, (0.0, 0.9, 0.04, 0.06)) for f in range(0, 61, 6)]
    row = ac.check(preds(nowhere), GT)[0]
    assert not row["followed_ok"] and row["median_containment"] == 0.0, row


def test_too_few_overlapping_frames_is_unverifiable_not_a_verdict() -> None:
    row = ac.check(preds([(0, (0.12, 0.13, 0.04, 0.06))]), GT)[0]
    assert row["followed_athlete"] is None and not row["followed_ok"] and row["compared_frames"] < ac.MIN_FRAMES, row


def test_interpolation_and_gap_limit() -> None:
    pts = [[0, 0.0, 0.0, 0.1, 0.1], [20, 0.4, 0.0, 0.1, 0.1], [200, 0.5, 0.0, 0.1, 0.1]]
    assert abs(ac.interp(pts, 10)[0] - 0.2) < 1e-9
    assert ac.interp(pts, 100) is None                 # keyframes 180 frames apart: no guess


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"PASS actor correctness contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
