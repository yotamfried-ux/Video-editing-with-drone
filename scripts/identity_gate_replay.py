#!/usr/bin/env python3
"""Frozen replay of the cycle-4 identity policy on the stored manifests (evaluation only, no model, no media).

Policy replayed: a part whose events come from >= 2 source files is publishable only with pairwise-consensus evidence.
Frozen artifacts predate that evidence, so every such part is REVIEW (withheld) until a verification run re-creates
it. Everything else is unchanged. The result is scored with the strict scorecard against both comparator baselines.

usage: identity_gate_replay.py --diagnostics DIR --baseline FILE [--out FILE]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402


def apply_policy(manifest: dict, predictions: dict | None) -> tuple[dict, list[str]]:
    out, withheld = copy.deepcopy(manifest), []
    parts, _ = sc.rendered_windows(manifest, predictions)
    multi = {p["key"] for p in parts if len({w["sha"] for w in p["windows"]}) >= 2}
    for arow in out.get("athletes") or []:
        for part in arow.get("parts") or []:
            key = f"{arow.get('athlete_key')}#{part.get('part_index')}"
            has_v3 = ((part.get("qualification_inputs") or {}).get("identity") or {}).get("evidence_method") == "pairwise_consensus"
            if key in multi and not has_v3 and part.get("publishable") is True:
                part["publishable"] = False
                withheld.append(key)
    return out, withheld


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    gt = json.loads(sc.DEFAULT_GT.read_text(encoding="utf-8"))
    manifest = json.loads((args.diagnostics / "publishable_reel_manifest.json").read_text(encoding="utf-8"))
    pred_path = args.diagnostics / "predictions.v1.json"
    predictions = json.loads(pred_path.read_text(encoding="utf-8")) if pred_path.exists() else None
    before = sc.evaluate(gt, manifest, predictions)["metrics"]
    replayed, withheld = apply_policy(manifest, predictions)
    after = sc.evaluate(gt, replayed, predictions)["metrics"]
    keys = ("published", "published_correct", "published_wrong_identity", "published_nonride", "correct_reels_withheld",
            "rides_recalled_published_full", "mixed_reels", "split_athletes")
    report = {"parts_withheld_by_policy": len(withheld), "before": {k: before[k] for k in keys}, "after": {k: after[k] for k in keys}}
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
