#!/usr/bin/env python3
"""Measure the pipeline's athlete identity against the operator's catalog, layer by layer.

Runs OUTSIDE the pipeline (the pipeline never imports this file and never sees ground truth). Inputs:

  trace  the run's identity trace: ``identity_trace.json``, or a job log containing the ``IDTRACE_JSON`` line
  gt     catalog export: {"athletes": {id: label}, "sources": [{name, split, owner, segments: [{start_sec, end_sec, athlete}]}]}

Each detected person is attributed to the catalog athlete whose included segments overlap the person's event windows
the most, in the same source video; a person that overlaps no included segment is "unattributed" (a bystander, or
an event outside what the operator catalogued) and is left out of the identity scores but counted.

Per layer (model -> post_process -> compile) it reports B-cubed precision (are a person's cluster-mates the same
athlete?) and recall (are the athlete's appearances in the person's cluster?), how many clusters each athlete is
spread over, which clusters mix athletes, and, for every pair of persons, the layer where a correct merge was
undone or a wrong merge was made. Tune on train/validation only; the test split stays out of the GT file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

LAYERS = ("model", "post_process", "compile")
_DJI = re.compile(r"DJI_\d+_\d+")


def load_trace(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "IDTRACE_JSON " in text:
        line = next(l for l in reversed(text.splitlines()) if "IDTRACE_JSON " in l)
        return json.loads(line.split("IDTRACE_JSON ", 1)[1])
    return json.loads(text)


def _source_id(name: str) -> str:
    m = _DJI.search(name or "")
    return m.group(0) if m else Path(name or "").name


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def attribute(trace: dict[str, Any], gt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """person key -> {athlete|None, source, split, overlap_sec}; persons from sources not in the GT file are skipped."""
    by_source = {_source_id(s["name"]): s for s in gt.get("sources", [])}
    out: dict[str, dict[str, Any]] = {}
    for key, person in trace.get("persons", {}).items():
        src = by_source.get(_source_id(person.get("source") or key.split("::")[0]))
        if src is None:
            continue
        scores: dict[str, float] = defaultdict(float)
        for w in person.get("windows", []):
            if w[0] is None or w[1] is None:
                continue
            for seg in src.get("segments", []):
                scores[seg["athlete"]] += _overlap((w[0], w[1]), (float(seg["start_sec"]), float(seg["end_sec"])))
        best = max(scores.items(), key=lambda kv: (kv[1], kv[0]), default=(None, 0.0))
        out[key] = {"athlete": best[0] if best[1] > 0 else None, "source": src["name"], "split": src.get("split"),
                    "overlap_sec": round(best[1], 2)}
    return out


def _assignment(trace: dict[str, Any], layer: str) -> dict[str, int]:
    return {k: row["cluster"] for row in trace.get("layers", {}).get(layer, []) for k in row.get("members", [])}


def bcubed(truth: dict[str, str], pred: dict[str, int]) -> tuple[float, float]:
    keys = [k for k in truth if k in pred]
    if not keys:
        return 0.0, 0.0
    p = r = 0.0
    for k in keys:
        same_pred = [j for j in keys if pred[j] == pred[k]]
        same_truth = [j for j in keys if truth[j] == truth[k]]
        both = sum(1 for j in same_pred if truth[j] == truth[k])
        p += both / len(same_pred)
        r += both / len(same_truth)
    return p / len(keys), r / len(keys)


def evaluate(trace: dict[str, Any], gt: dict[str, Any]) -> dict[str, Any]:
    attr = attribute(trace, gt)
    labels = gt.get("athletes", {})
    truth = {k: v["athlete"] for k, v in attr.items() if v["athlete"]}
    report: dict[str, Any] = {
        "persons_in_gt_sources": len(attr),
        "attributed_persons": len(truth),
        "unattributed_persons": sorted(k for k, v in attr.items() if not v["athlete"]),
        "gt_athletes": len(set(truth.values())),
        "layers": {},
    }
    # catalogued athletes / sources the pipeline never produced a person for
    seen_sources = {_source_id(v["source"]) for v in attr.values()}
    report["gt_sources_without_pipeline_person"] = sorted(
        s["name"] for s in gt.get("sources", []) if s.get("segments") and _source_id(s["name"]) not in seen_sources)
    assignments = {layer: _assignment(trace, layer) for layer in LAYERS if layer in trace.get("layers", {})}
    for layer, pred in assignments.items():
        p, r = bcubed(truth, pred)
        clusters_per_athlete: dict[str, set[int]] = defaultdict(set)
        athletes_per_cluster: dict[int, set[str]] = defaultdict(set)
        missing = [k for k in truth if k not in pred]
        for k, a in truth.items():
            if k in pred:
                clusters_per_athlete[a].add(pred[k])
                athletes_per_cluster[pred[k]].add(a)
        report["layers"][layer] = {
            "bcubed_precision": round(p, 3), "bcubed_recall": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "clusters": len(set(pred.values())),
            "fragmented_athletes": {labels.get(a, a): len(c) for a, c in sorted(clusters_per_athlete.items()) if len(c) > 1},
            "mixed_clusters": {str(c): sorted(labels.get(a, a) for a in ath) for c, ath in sorted(athletes_per_cluster.items()) if len(ath) > 1},
            "attributed_persons_missing_here": missing,
        }
    # pair history: where a same-athlete pair got separated, or a different-athlete pair got joined
    events = []
    keys = sorted(truth)
    for a, b in combinations(keys, 2):
        same = truth[a] == truth[b]
        history = [(layer, assignments[layer].get(a) is not None and assignments[layer].get(a) == assignments[layer].get(b))
                   for layer in assignments]
        if not history:
            continue
        final_ok = history[-1][1] == same
        if final_ok:
            continue
        first_wrong = next(layer for layer, together in history if together != same)
        events.append({"pair": [a, b], "athlete": labels.get(truth[a], truth[a]) if same else
                       [labels.get(truth[a], truth[a]), labels.get(truth[b], truth[b])],
                       "error": "missed_merge" if same else "false_merge", "first_wrong_layer": first_wrong,
                       "history": {layer: together for layer, together in history}})
    report["pair_errors"] = events
    report["pair_error_counts"] = {
        f"{e}@{layer}": sum(1 for x in events if x["error"] == e and x["first_wrong_layer"] == layer)
        for e in ("missed_merge", "false_merge") for layer in assignments
    }
    report["evidence_kinds"] = dict(sorted(
        {kind: sum(1 for p in trace.get("persons", {}).values() if (p.get("evidence") or {}).get("kind") == kind)
         for kind in {(p.get("evidence") or {}).get("kind") for p in trace.get("persons", {}).values()}}.items(),
        key=lambda kv: str(kv[0])))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trace", type=Path)
    ap.add_argument("gt", type=Path)
    ap.add_argument("--splits", default="train,validation")
    args = ap.parse_args()
    gt = json.loads(args.gt.read_text(encoding="utf-8"))
    splits = set(args.splits.split(","))
    if "test" in splits:
        print("refusing: the test split is held out of identity tuning", file=sys.stderr)
        return 2
    gt = {**gt, "sources": [s for s in gt.get("sources", []) if s.get("split") in splits]}
    print(json.dumps(evaluate(load_trace(args.trace), gt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
