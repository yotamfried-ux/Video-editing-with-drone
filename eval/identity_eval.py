"""
eval/identity_eval.py — measurable gate for identity-clustering quality.

Runs the REAL merge logic (pipeline.clustering.union_find_merge) on labeled
fixtures with a precomputed CLIP similarity matrix and a confirmation oracle, so
the contamination metric is reproducible without torch/Gemini/live data.

Metrics (pairwise):
  precision = same-cluster pairs that are truly the same athlete / all same-cluster pairs
              → the contamination metric; a false merge (someone else's clip in a
                reel) is the product's worst failure.
  recall    = truly-same pairs that were grouped together / all truly-same pairs
              → guards against over-splitting one athlete into many reels.

Compares against eval/baseline.json (recorded from the pre-gate threshold-only
behavior). Usage:
  python eval/identity_eval.py              # evaluate current (gated) config
  python eval/identity_eval.py --baseline   # (re)write baseline from threshold-only
"""

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.clustering import union_find_merge

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_GLOB = os.path.join(_HERE, "fixtures", "*.json")
BASELINE = os.path.join(_HERE, "baseline.json")
LAST = os.path.join(_HERE, "last_eval.json")

# Defaults mirror config but are kept literal here so the eval doesn't require the
# env vars config.settings demands at import.
MERGE_THRESHOLD = 0.78
HIGH_CONF = 0.88
# Simulated accuracy of the Gemini "same person?" confirmation (1.0 = perfect).
ORACLE_ACCURACY = float(os.getenv("EVAL_ORACLE_ACCURACY", "1.0"))


def _pairwise_metrics(items, groups):
    cluster_of = {}
    for gi, g in enumerate(groups):
        for idx in g:
            cluster_of[idx] = gi
    n = len(items)
    same_pred = same_true = true_pos = 0
    for i in range(n):
        for j in range(i + 1, n):
            pred_same = cluster_of[i] == cluster_of[j]
            truth_same = items[i]["true_athlete"] == items[j]["true_athlete"]
            if pred_same:
                same_pred += 1
            if truth_same:
                same_true += 1
            if pred_same and truth_same:
                true_pos += 1
    precision = true_pos / same_pred if same_pred else 1.0
    recall = true_pos / same_true if same_true else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _make_confirm(items):
    # Oracle: ground-truth same-athlete, optionally degraded to simulate Gemini error.
    def confirm(i, j):
        truth = items[i]["true_athlete"] == items[j]["true_athlete"]
        if ORACLE_ACCURACY >= 1.0:
            return truth
        import random
        return truth if random.random() < ORACLE_ACCURACY else (not truth)
    return confirm


def _eval_fixture(fx, *, gated):
    items = fx["items"]
    sim = fx["sim_matrix"]
    clip_idx = [it["clip_index"] for it in items]
    if gated:
        groups = union_find_merge(sim, clip_idx, merge_threshold=MERGE_THRESHOLD,
                                  high_conf=HIGH_CONF, confirm_fn=_make_confirm(items))
    else:
        # Pre-gate behavior: everything >= threshold merges directly (high_conf at
        # the threshold means the confirm callback is never consulted).
        groups = union_find_merge(sim, clip_idx, merge_threshold=MERGE_THRESHOLD,
                                  high_conf=MERGE_THRESHOLD, confirm_fn=lambda i, j: True)
    return _pairwise_metrics(items, groups)


def run(gated=True):
    results = {}
    for path in sorted(glob.glob(FIXTURE_GLOB)):
        name = os.path.basename(path)
        with open(path) as f:
            fx = json.load(f)
        results[name] = _eval_fixture(fx, gated=gated)
    return results


def _aggregate(results):
    if not results:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    keys = ("precision", "recall", "f1")
    return {k: round(sum(r[k] for r in results.values()) / len(results), 4) for k in keys}


def main():
    write_baseline = "--baseline" in sys.argv
    gated = not write_baseline  # baseline captures the OLD threshold-only behavior
    results = run(gated=gated)
    agg = _aggregate(results)

    print(f"\n📊 Identity eval ({'threshold-only baseline' if write_baseline else 'gated'})")
    for name, r in results.items():
        print(f"  {name}: precision={r['precision']} recall={r['recall']} f1={r['f1']}")
    print(f"  AGGREGATE: precision={agg['precision']} recall={agg['recall']} f1={agg['f1']}")

    with open(LAST, "w") as f:
        json.dump({"gated": gated, "fixtures": results, "aggregate": agg}, f, indent=2)

    if write_baseline:
        with open(BASELINE, "w") as f:
            json.dump({"aggregate": agg, "fixtures": results}, f, indent=2)
        print(f"  ✅ baseline written to {BASELINE}")
        return 0

    if not os.path.exists(BASELINE):
        print("  ⚠️ no baseline.json — run with --baseline first")
        return 0
    with open(BASELINE) as f:
        base = json.load(f)["aggregate"]
    # Gate: precision must not regress; recall within a small tolerance.
    prec_ok = agg["precision"] >= base["precision"] - 1e-9
    recall_ok = agg["recall"] >= base["recall"] - 0.05
    print(f"  baseline: precision={base['precision']} recall={base['recall']}")
    if prec_ok and recall_ok:
        print("  ✅ gate PASS (precision held/improved, recall within tolerance)")
        return 0
    print("  ❌ gate FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
