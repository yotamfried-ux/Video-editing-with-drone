#!/usr/bin/env python3
"""Moving a part to REVIEW changes nothing but its publishable flag (no ride, window, event or reel is dropped or re-cut).

P1  apply_policy flips `publishable` only for multi-source parts without owner/consensus evidence; every other field, event and
    window is byte-identical; single-source parts and already-withheld parts are untouched.
P2  The strict scorecard's selection / window metrics are identical before and after (only publishing metrics may change).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402
import identity_gate_replay as rp  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def part(idx, shas, publishable=True, evidence=None):
    events = [{"event_uid": f"e{idx}{i}", "source_sha256": s, "source_frame_range_sec": [0.0, 5.0],
               "interval": {"rendered_window": [0.0, 5.0]}, "actor_track_uid": f"{s}#1"} for i, s in enumerate(shas)]
    ident = {"verdict": "MATCH"}
    if evidence:
        ident["evidence_method"] = evidence
    return {"athlete_key": f"k{idx}", "parts": [{"part_index": 1, "publishable": publishable, "foo": idx,
                                                "qualification_inputs": {"events": events, "identity": ident}}]}


def main():
    gt = {"dataset_id": "t", "digest": "d", "members": [
        {"sha256": s, "content": {"fps_num": 60, "fps_den": 1, "segments": [
            {"decision": "include", "athlete_id": "A", "start_frame": 0, "end_frame": 300}]}} for s in ("s1", "s2")]}
    man = {"pipeline_run_id": "r", "athletes": [part(1, ["s1"]), part(2, ["s1", "s2"]), part(3, ["s1", "s2"], evidence="pairwise_consensus"),
                                                  part(4, ["s1", "s2"], publishable=False)]}
    out, withheld = rp.apply_policy(man, None)
    check(len(withheld) == 1 and withheld[0].startswith("k2#"), f"P1 only the unverified multi-source part: {withheld}")
    diffs = [(i, k) for i, (x, y) in enumerate(zip(man["athletes"], out["athletes"]))
             for k in x["parts"][0] if x["parts"][0][k] != y["parts"][0].get(k)]
    check(diffs == [(1, "publishable")], f"P1 only the publishable flag may change: {diffs}")
    a, b = sc.evaluate(gt, man)["metrics"], sc.evaluate(gt, out)["metrics"]
    same = ("rides_any_selected", "rides_full_selected", "missing_seconds_total", "duplicate_ride_frames", "nonride_windows",
            "excluded_frames_selected", "reels", "blocked_windows")
    check(all(a[k] == b[k] for k in same), f"P2 selection metrics changed: {[(k, a[k], b[k]) for k in same if a[k] != b[k]]}")
    check(b["published"] == a["published"] - 1, "P2 exactly one reel moves to REVIEW")


main()
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("identity gate replay contract: all cases passed")
