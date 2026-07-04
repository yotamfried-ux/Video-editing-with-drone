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

    print("Event window contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
