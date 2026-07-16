#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.window_policy import resolve_window

    late_start = {"type": "cutback", "start": 12, "end": 20, "score": 8, "setup_start": 10, "peak_time": 16, "outcome_end": 20}
    out = resolve_window(late_start, 60)
    if not out or out["start"] > 10 or out["final_cut_start"] > 10:
        raise SystemExit("late-start event must preserve setup")
    if out["window_validation_status"] not in ("adjusted", "valid"):
        raise SystemExit("late-start event missing validation status")

    early_end = {"type": "snap", "start": 10, "end": 18, "score": 8, "peak_time": 16, "outcome_end": 21}
    out = resolve_window(early_end, 60)
    if not out or out["end"] < 21 or out["final_cut_end"] < 21:
        raise SystemExit("early-end event must preserve outcome")

    capped = {"type": "wave_catch", "start": 0, "end": 24, "score": 7, "setup_start": 10, "peak_time": 15, "outcome_end": 20}
    out = resolve_window(capped, 60)
    if not out or out["end"] - out["start"] > 11.01:
        raise SystemExit("normal capped event must be <= 11s")
    if not (out["start"] <= 15 <= out["end"] and out["end"] >= 20):
        raise SystemExit("duration cap removed peak or outcome")
    if "cap_preserved_action" not in out["cut_adjustment_reason"]:
        raise SystemExit("cap adjustment reason missing")

    too_long = {"type": "carve", "start": 0, "end": 30, "score": 7, "setup_start": 0, "peak_time": 14, "outcome_end": 20}
    if resolve_window(too_long, 60) is not None:
        raise SystemExit("action window that exceeds cap must not produce a normal clip")

    empty = {"type": "paddle", "start": 8, "end": 20, "score": 6, "empty_window": True}
    if resolve_window(empty, 60) is not None:
        raise SystemExit("empty window must be dropped")
    legacy_empty = {"type": "paddle", "start": 8, "end": 20, "score": 6, "".join(["dead", "_time_only"]): True}
    if resolve_window(legacy_empty, 60) is not None:
        raise SystemExit("legacy empty marker must be dropped")

    no_phase = {"type": "highlight", "start": 0, "end": 20, "score": 7}
    out = resolve_window(no_phase, 60)
    if not out or out["end"] - out["start"] > 11.01:
        raise SystemExit("no-phase long window should still be capped")
    for key in ["original_start", "original_end", "final_cut_start", "final_cut_end", "cut_adjustment_reason", "window_validation_status", "window_validation_reason"]:
        if key not in out:
            raise SystemExit(f"missing metadata field: {key}")

    # Teaser windows must not be taken from empty padding: analyzer.py pads a
    # short real event out to its minimum clip duration by pushing `end`
    # forward, which can leave dead time between the real outcome and the
    # padded end. A teaser/preview sampled near the tail of the resolved
    # window must land on real content, not that padding.
    padded_short_event = {"type": "snap", "start": 20, "end": 32, "score": 8, "outcome_end": 24}
    out = resolve_window(padded_short_event, 60)
    if not out:
        raise SystemExit("padded short event should still resolve to a window")
    if out["end"] > 24 + 1.51:
        raise SystemExit("teaser window was not trimmed back from empty padding after outcome_end")
    if "outcome_trim" not in out["cut_adjustment_reason"]:
        raise SystemExit("outcome_trim adjustment reason missing for a padded window")

    # A window whose real content already runs right up to end (no padding
    # to trim) must not be shortened just because outcome_end is present.
    no_padding_event = {"type": "snap", "start": 20, "end": 28, "score": 8, "outcome_end": 27}
    out = resolve_window(no_padding_event, 60)
    if not out or out["end"] < 27:
        raise SystemExit("window without meaningful padding must not be trimmed past outcome_end")

    # Raw timestamps (pre-clamp) must be tracked distinctly from the
    # pre-existing original_start/original_end (post-clamp, pre-phase-adjust).
    near_boundary = {"type": "wave_catch", "start": -3, "end": 5, "score": 7}
    out = resolve_window(near_boundary, 60)
    if not out or out.get("raw_start") != -3.0:
        raise SystemExit("raw_start must preserve the pre-clamp timestamp")
    if out["original_start"] == out["raw_start"]:
        raise SystemExit("original_start should reflect the post-clamp value, distinct from raw_start here")

    # An outcome_end that is inconsistent with (earlier than) peak_time must
    # never produce a window that excludes the peak moment -- either the
    # event is rejected outright (None) or, if resolved, peak stays inside
    # [final_cut_start, final_cut_end]. This is a real bug the outcome_trim
    # addition above exposed: trimming the tail toward a stale/wrong
    # outcome_end previously could cut the peak itself out of frame.
    conflicting_evidence = {"type": "aerial", "start": 0, "end": 5, "score": 8, "peak_time": 20, "outcome_end": 10}
    out = resolve_window(conflicting_evidence, 60)
    if out is not None and not (out["final_cut_start"] <= 20 <= out["final_cut_end"]):
        raise SystemExit("conflicting peak/outcome evidence produced a window that excludes the peak")

    print("Event window contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
