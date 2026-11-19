#!/usr/bin/env python3
"""Contracts of the strict GT scorecard (PQ-07/08/16/21/36). Each case names the defect of the draft checker it prevents.

S1  A ride covered 50-95 % is ANY/50 but not 95/FULL; the missing seconds are reported.
S2  Overlapping windows never count a frame twice (union), and the overlap is reported as duplicate frames.
S3  One excluded frame is counted (union per source); a reel with it is not correct.
S4  A +0.6 s start error is over tolerance and the ride is not FULL; +0.4 s is FULL.
S5  A window without source sha / interval is BLOCKED and its reel is never 'correct'.
S6  compare(): a missing or None protected metric is an error (exit 2), not a skip; a worse value is a regression.
S7  Legacy action_lineage: a basename that maps to two source hashes is BLOCKED.
S8  A published correct reel with a FULL ride recalls it; a withheld one does not; withheld-correct is counted.
S9  Two athletes in one reel => mixed; one athlete in two reels => split.
S10 Inference never reads the GT (no pipeline/, integrations/ or stages/ file names evaluation/ground_truth).
S11 The frozen GT is the owner's v1: 24 sources, 13 athletes (unchanged, read-only).
S12 An absolute release gate vetoes existing P0 defects even if baseline comparison is green.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402

FAILURES: list[str] = []
FPS = 60000 / 1001


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)


def gt(rides=(("A", 0, 600),), excludes=((700, 800),), sha="s1"):
    segs = [{"decision": "include", "athlete_id": a, "start_frame": s, "end_frame": e} for a, s, e in rides]
    segs += [{"decision": "exclude", "start_frame": s, "end_frame": e} for s, e in excludes]
    return {"dataset_id": "t", "digest": "d", "members": [{"sha256": sha, "content": {
        "fps_num": 60000, "fps_den": 1001, "segments": segs}}]}


def manifest(reels):
    """reels: list of (publishable, [(sha, a_sec, b_sec) or None-for-missing])"""
    rows = []
    for i, (pub, wins) in enumerate(reels):
        evs = [{"event_uid": f"e{i}{j}", "source_sha256": w[0] if w else None,
                "source_frame_range_sec": [w[1], w[2]] if w else None} for j, w in enumerate(wins)]
        rows.append({"athlete_key": f"k{i}", "parts": [{"part_index": 1, "publishable": pub,
                                                        "qualification_inputs": {"events": evs}}]})
    return {"pipeline_run_id": "r", "athletes": rows}


def sec(frames: int) -> float:
    return frames / FPS


def run(g, reels):
    return sc.evaluate(g, manifest(reels))


def s1():
    m = run(gt(), [(True, [("s1", 0, sec(350))])])["metrics"]          # 58 % of the ride
    check(m["rides_any_selected"] == 1 and m["rides_ge50_selected"] == 1, "S1 ANY/50 expected")
    check(m["rides_ge95_selected"] == 0 and m["rides_full_selected"] == 0, "S1 58 % must not be 95/FULL")
    check(m["missing_seconds_total"] > 4, "S1 missing seconds must be reported")


def s2():
    m = run(gt(), [(True, [("s1", 0, sec(400)), ("s1", sec(200), sec(600))])])["metrics"]
    check(m["duplicate_ride_frames"] >= 190, f"S2 overlap must be reported as duplicate: {m['duplicate_ride_frames']}")
    check(m["rides_full_selected"] == 1, "S2 union of the two windows covers the whole ride exactly once")


def s3():
    r = run(gt(), [(True, [("s1", 0, sec(601 + 100 + 1))])])           # reaches frame 702: 2 excluded frames
    check(r["metrics"]["excluded_frames_selected"] == 2, f"S3 excluded: {r['metrics']['excluded_frames_selected']}")
    check(r["reels"][0]["correct"] is False, "S3 reel with excluded frames is not correct")


def s4():
    late = run(gt(), [(True, [("s1", sec(36), sec(600))])])["metrics"]   # +0.6 s start
    ok = run(gt(), [(True, [("s1", sec(24), sec(600))])])["metrics"]     # +0.4 s start
    check(late["boundary_over_tolerance"] >= 1 and late["rides_full_selected"] == 0, "S4 +0.6 s must fail FULL")
    check(ok["rides_full_selected"] == 1, "S4 +0.4 s must remain FULL")


def s5():
    r = run(gt(), [(True, [("s1", 0, sec(600)), None])])
    check(r["metrics"]["blocked_windows"] == 1, "S5 missing lineage must be blocked")
    check(r["reels"][0]["correct"] is False, "S5 a reel with blocked lineage is never correct")


def s6():
    base = {k: 1 for k in sc.PROTECTED}
    cur = dict(base)
    del cur["published_correct"]
    check(any("published_correct" in e for e in sc.compare(cur, base)[1]), "S6 missing metric must be an error")
    cur = dict(base, boundary_max_error_sec=None)
    check(any("boundary_max_error_sec" in e for e in sc.compare(cur, base)[1]), "S6 None metric must be an error")
    cur = dict(base, excluded_frames_selected=2)
    check(any("excluded_frames_selected" in e for e in sc.compare(cur, base)[0]), "S6 excluded +1 regression")
    cur = dict(base, published_correct=0)
    check(any("published_correct" in e for e in sc.compare(cur, base)[0]), "S6 fewer correct regression")
    check(sc.compare(dict(base), base) == ([], []), "S6 equal run is clean")


def s7():
    man = {"athletes": [{"athlete_key": "k", "action_lineage": ["/x/a.MP4|0.0|9.0|surf_ride"],
                         "parts": [{"part_index": 1, "publishable": True, "qualification_inputs": {}}]}]}
    pred = {"sources": [{"source_video": "a.MP4", "source_sha256": "s1"}, {"source_video": "a.MP4", "source_sha256": "s2"}]}
    r = sc.evaluate(gt(), man, pred)
    check(r["metrics"]["blocked_windows"] == 1, "S7 ambiguous basename must be blocked")
    pred["sources"].pop()
    check(sc.evaluate(gt(), man, pred)["metrics"]["blocked_windows"] == 0, "S7 unique basename maps")


def s8():
    full = [("s1", 0, sec(600))]
    m = run(gt(), [(True, full)])["metrics"]
    check(m["rides_recalled_published_full"] == 1 and m["published_correct"] == 1, "S8 published full recalled")
    m = run(gt(), [(False, full)])["metrics"]
    check(m["rides_recalled_published_full"] == 0 and m["correct_reels_withheld"] == 1, "S8 withheld not recalled, counted")


def s9():
    g = gt(rides=(("A", 0, 300), ("B", 400, 650)), excludes=())
    m = run(g, [(True, [("s1", 0, sec(300)), ("s1", sec(400), sec(650))])])["metrics"]
    check(m["mixed_reels"] == 1 and m["published_wrong_identity"] == 1, "S9 two athletes in one reel is mixed")
    m = run(g, [(True, [("s1", 0, sec(300))]), (True, [("s1", sec(10), sec(290))])])["metrics"]
    check(m["split_athletes"] == 1, "S9 one athlete in two reels is split")


def s10():
    hits = []
    for folder in ("pipeline", "integrations", "stages"):
        for f in (ROOT / folder).rglob("*.py"):
            if "evaluation/ground_truth" in f.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(f.relative_to(ROOT)))
    check(not hits, f"S10 inference code reads the GT: {hits}")


def s11():
    data = json.loads(sc.DEFAULT_GT.read_text(encoding="utf-8"))
    truth = sc.load_gt(data)
    athletes = {r["athlete_id"] for t in truth.values() for r in t["rides"]}
    check(len(truth) == 24 and len(athletes) == 13, f"S11 GT-v1 sources/athletes: {len(truth)}/{len(athletes)}")
    check(data.get("digest") == "b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9", "S11 GT digest changed")


def s12():
    """S12: absolute release gate refuses unchanged P0 defects despite a green baseline diff."""
    g = run(gt(excludes=()), [(True, [("s1", 0, sec(600))])])["metrics"]
    failures, errors = sc.absolute_release_gate(g)
    check(not failures and not errors, f"S12 clean known cohort: {failures}, {errors}")
    for key in ("excluded_frames_selected", "nonride_windows", "duplicate_ride_frames",
                "mixed_reels", "split_athletes", "published_wrong_identity",
                "published_nonride", "wrong_actor_reels", "blocked_windows",
                "unknown_source_windows", "boundary_over_tolerance", "correct_reels_withheld"):
        bad = dict(g, **{key: 1})
        failures, errors = sc.absolute_release_gate(bad)
        check(bool(failures) and not errors, f"S12 must veto {key}=1")
    for key in ("gt_rides", "rides_full_selected", "rides_recalled_published_full",
                "boundary_max_error_sec", "excluded_frames_selected"):
        bad = dict(g)
        del bad[key]
        failures, errors = sc.absolute_release_gate(bad)
        check(bool(errors), f"S12 missing {key} must fail closed")
    bad = dict(g, rides_full_selected=0)
    check(bool(sc.absolute_release_gate(bad)[0]), "S12 incomplete ride veto")
    bad = dict(g, boundary_max_error_sec=0.6)
    check(bool(sc.absolute_release_gate(bad)[0]), "S12 late/early cut veto")
    # A no-change baseline comparison is not an absolute release approval.
    bad = dict(g, excluded_frames_selected=1)
    check(sc.compare(bad, bad) == ([], []) and bool(sc.absolute_release_gate(bad)[0]),
          "S12 no-regression cannot certify existing excluded footage")

for case in (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12):
    try:
        case()
    except Exception as exc:  # a crash is a failure, never a pass
        FAILURES.append(f"{case.__name__} crashed: {exc!r}")
if FAILURES:
    print("\n".join(f"FAIL {f}" for f in FAILURES))
    sys.exit(1)
print("gt scorecard contract: all cases passed")
