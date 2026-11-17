#!/usr/bin/env python3
"""Contracts of the identity pair experiment's decision rules and metrics (no model, no media).

I1  Production semantics: only an explicit boolean same_person confirms; {} / missing / string is REVIEW.
I2  A single MATCH needs >= 2 specific features, no contradiction, not generic-only; NO_MATCH needs a cited contradiction.
I3  Consensus: any disagreement between the two image orders, or any doubt, is REVIEW (never an automatic merge).
I4  score_pairs counts false merges / false splits / review, ignores un-evaluated pairs, reports the hard-negative subset.
I5  The athlete split is deterministic, disjoint, and never mixes splits inside a pair set; same-source pairs are excluded.
I6  Budget: no model call once the cap is reached.
I7  The experiment never writes media: no file output other than the JSON result.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import identity_pair_experiment as ex  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def i1():
    check(ex.m0_decision({"same_person": True}) == "MATCH", "I1 true")
    check(ex.m0_decision({"same_person": False}) == "NO_MATCH", "I1 false")
    for bad in ({}, None, {"same_person": "true"}, {"same_person": None}):
        check(ex.m0_decision(bad) == "REVIEW", f"I1 {bad!r} must be REVIEW")


def i2():
    good = {"verdict": "MATCH", "matching_features": ["red board with white stripe", "blue rash guard"],
            "contradicting_features": [], "generic_only": False}
    check(ex.single_verdict(good) == "MATCH", "I2 two specific features")
    check(ex.single_verdict(dict(good, matching_features=["pink board"])) == "REVIEW", "I2 one feature")
    check(ex.single_verdict(dict(good, contradicting_features=["different shorts"])) == "REVIEW", "I2 MATCH with contradiction")
    check(ex.single_verdict(dict(good, generic_only=True)) == "REVIEW", "I2 generic only")
    check(ex.single_verdict({"verdict": "NO_MATCH", "contradicting_features": []}) == "REVIEW", "I2 NO_MATCH without evidence")
    check(ex.single_verdict({"verdict": "NO_MATCH", "contradicting_features": ["board colour"]}) == "NO_MATCH", "I2 NO_MATCH with evidence")
    check(ex.single_verdict("x") == "REVIEW" and ex.single_verdict({"verdict": "maybe"}) == "REVIEW", "I2 garbage")


def i3():
    m = {"verdict": "MATCH", "matching_features": ["a", "b"], "contradicting_features": []}
    n = {"verdict": "NO_MATCH", "contradicting_features": ["c"]}
    check(ex.consensus(m, m) == "MATCH" and ex.consensus(n, n) == "NO_MATCH", "I3 agreement")
    check(ex.consensus(m, n) == "REVIEW" and ex.consensus(n, m) == "REVIEW", "I3 disagreement")
    check(ex.consensus(m, None) == "REVIEW", "I3 missing second order")
    # the production verdict on a lookalike pair would be MATCH; the consensus rule must not auto-merge generic matches
    generic = {"verdict": "MATCH", "matching_features": ["pink board", "dark shorts"], "contradicting_features": [],
               "generic_only": True}
    check(ex.consensus(generic, generic) == "REVIEW", "I3 generic lookalike must be REVIEW")


def i4():
    rows = [{"same": True, "hard": False, "X": "MATCH"}, {"same": True, "hard": False, "X": "NO_MATCH"},
            {"same": True, "hard": False, "X": "REVIEW"}, {"same": False, "hard": True, "X": "MATCH"},
            {"same": False, "hard": True, "X": "REVIEW"}, {"same": False, "hard": False, "X": "NO_MATCH"},
            {"same": False, "hard": False, "X": None}]
    r = ex.score_pairs(rows, "X")
    a, h = r["all"], r["hard_negatives"]
    check((a["pairs"], a["false_merges"], a["false_splits"], a["review_positive"], a["review_negative"]) == (6, 1, 1, 1, 1), f"I4 {a}")
    check((h["pairs"], h["false_merges"]) == (2, 1), f"I4 hard {h}")
    check(ex.wilson_upper(0, 18) is not None and ex.wilson_upper(0, 0) is None, "I4 wilson")


def i5():
    ids = [f"ath{i}" for i in range(13)]
    dev, hold = ex.athlete_split(ids)
    check(len(hold) == ex.HOLDOUT_ATHLETES and not (dev & hold) and dev | hold == set(ids), "I5 split")
    check(ex.athlete_split(list(reversed(ids))) == (dev, hold), "I5 deterministic")
    apps = [{"source_sha256": s, "track_id": "1", "athlete_id": a} for s, a in
            (("s1", "a"), ("s2", "a"), ("s2", "b"), ("s3", "b"), ("s4", "c"))]
    pairs = ex.make_pairs(apps, {"a", "b"}, "dev", {})
    used = {k for p in pairs for k in (p["i"], p["j"])}
    check(4 not in used, "I5 athlete outside the split used")
    check(all(apps[p["i"]]["source_sha256"] != apps[p["j"]]["source_sha256"] for p in pairs), "I5 same-source pair")
    check(sum(p["same"] for p in pairs) == 2, "I5 positives")


def i6():
    b = ex.Budget(0.001)
    check(b.can(), "I6 initially can")

    class U:
        prompt_token_count, candidates_token_count, thoughts_token_count = 10000, 100, 0
    b.add(U())
    check(not b.can() and ex.ask(None, None, b, "p", []) is None, "I6 stops at cap")


def i7():
    src = (ROOT / "scripts" / "identity_pair_experiment.py").read_text(encoding="utf-8")
    # clusters mode must hand the production verifier a thumbnail PATH: the only media write goes to the job's temp dir
    check(src.count("write_bytes") == 1 and 'thumb = os.path.join(tmp, f"{sha[:12]}_{track}.jpg")' in src
          and ".save(" in src and "BytesIO" in src, "I7 images stay in memory / the job temp dir")
    check(src.count("write_text") == 2, "I7 only the two JSON results (pairs, clusters) are written")
    check("media_in_result" in src, "I7 flag")


def i8():
    good = [{"t": 1.0, "w": 150, "conf": 0.8}, {"t": 3.0, "w": 160, "conf": 0.7}, {"t": 5.5, "w": 140, "conf": 0.9}]
    q = ex.crop_quality(good)
    check(q["distinct_times"] and q["min_gap_sec"] == 2.0 and q["span_sec"] == 4.5 and q["median_target_width_px"] == 150, f"I8 {q}")
    bad = ex.crop_quality([{"t": 1.0, "w": 20, "conf": 0.3}, {"t": 1.0, "w": 22, "conf": 0.4}])
    check(not bad["distinct_times"] and bad["median_target_width_px"] <= 22, f"I8 duplicate times must be visible: {bad}")
    check(ex.crop_quality([])["n"] == 0, "I8 empty")


for case in (i1, i2, i3, i4, i5, i6, i7, i8):
    try:
        case()
    except Exception as exc:
        FAILURES.append(f"{case.__name__} crashed: {exc!r}")
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("identity pair experiment contract: all cases passed")
