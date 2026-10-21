#!/usr/bin/env python3
"""Contract for the A/B comparison logic (pure functions; no network)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ab_action_selection as ab  # noqa: E402


def ev(start, end, score=8):
    return {"start": start, "end": end, "score": score}


def session(*events):
    return {"persons": [{"events": [dict(e) for e in events]}]}


def test_iou_and_flatten() -> None:
    assert ab.iou(ev(0, 10), ev(0, 10)) == 1.0
    assert ab.iou(ev(0, 10), ev(10, 20)) == 0.0
    assert abs(ab.iou(ev(0, 10), ev(5, 15)) - 5 / 15) < 1e-9
    assert len(ab.flatten_events({"persons": [{"events": [ev(0, 5), {"bad": 1}]}, {"events": [ev(6, 9)]}]})) == 2


def test_agreement_counts_recall_top_recall_and_extras() -> None:
    reference = [ev(0, 10, 9), ev(20, 30, 7), ev(40, 50, 8)]
    other = [ev(1, 10, 9), ev(40, 50, 6), ev(70, 80, 7)]
    result = ab.agreement(reference, other)
    assert result["recall"] == 2 / 3 and result["top_recall"] == 1.0 and result["extra"] == 1, result


def test_judge_uses_the_control_repeat_noise_floor() -> None:
    reference = [ev(0, 10, 9), ev(20, 30, 8)]
    per_source = {"s": {
        "control_repeat": {**ab.agreement(reference, [ev(0, 10), ev(20, 30)]), "same_person_count": True},
        "good": {**ab.agreement(reference, [ev(0, 10), ev(20, 30)]), "same_person_count": True},
        "lossy": {**ab.agreement(reference, [ev(0, 10)]), "same_person_count": True},
        "persons": {**ab.agreement(reference, [ev(0, 10), ev(20, 30)]), "same_person_count": False},
    }}
    assert ab.judge(per_source, "good")["verdict"] == "PASS"
    assert ab.judge(per_source, "lossy")["verdict"] == "FAIL"
    assert ab.judge(per_source, "persons")["verdict"] == "FAIL", "perfectly stable control but the variant changes athlete counts"
    flaky = {"a": {"control_repeat": {**ab.agreement(reference, reference), "same_person_count": False},
                   "v": {**ab.agreement(reference, reference), "same_person_count": False}},
             "b": {"control_repeat": {**ab.agreement(reference, reference), "same_person_count": True},
                   "v": {**ab.agreement(reference, reference), "same_person_count": True}}}
    assert ab.judge(flaky, "v")["verdict"] == "PASS", "athlete counts the model itself disagrees on are noise, not regression"
    errored = {"s": {**per_source["s"], "boom": {**per_source["s"]["good"], "errored": True}}}
    assert ab.judge(errored, "boom")["verdict"] == "FAIL", "a variant whose Gemini call errored cannot pass"
    noisy = {"s": {"control_repeat": {**ab.agreement(reference, [ev(0, 10)]), "same_person_count": True},
                   "lossy": {**ab.agreement(reference, [ev(0, 10)]), "same_person_count": True}}}
    assert ab.judge(noisy, "lossy")["verdict"] == "PASS", "a variant as good as the model's own noise is not a regression"


def test_timeline_shift_detection() -> None:
    reference = [ev(40, 50), ev(70, 80)]
    relative = [ev(8, 18), ev(38, 48)]          # same actions, times counted from a clip starting at 32s
    assert ab.detect_timeline_shift(reference, relative, 32.0)
    assert not ab.detect_timeline_shift(reference, [ev(40, 50), ev(70, 80)], 32.0)
    assert not ab.detect_timeline_shift([], relative, 32.0) and not ab.detect_timeline_shift(reference, relative, 0.0)


def test_sampling_is_deterministic_and_skips_short_clips() -> None:
    objects = [{"Key": f"processed/{i:02d}.MP4", "Size": 200_000_000} for i in range(24)]
    objects.append({"Key": "processed/clip.mp4", "Size": 5_000_000})
    first = ab.pick_sources(objects, 8, 100_000_000)
    assert first == ab.pick_sources(list(reversed(objects)), 8, 100_000_000)
    assert len(first) == 8 and all("clip" not in o["Key"] for o in first)
    assert len(ab.pick_sources(objects, 0, 100_000_000)) == 24


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS A/B action selection contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
