#!/usr/bin/env python3
"""Gate C replay (cycle 10): re-score stored runs under FIX-PQ-10-001 (model-only visual consensus never makes a
multi-source reel publishable) without re-running the pipeline.

For every part of a stored run's publishable_reel_manifest.json whose identity basis is
`identity_gate_pass_with_image_evidence` across more than one source, the candidate policy withholds the part
(publishable=False). Owner-approved operator_review evidence would still pass; none exists in the stored runs.
Parts without per-event qualification inputs (legacy manifests) are reported as NOT_REPLAYABLE, never guessed.

usage: identity_policy_replay.py DIAG_DIR [DIAG_DIR...] --gt GT.json --out OUT.json
Prints baseline vs candidate scorecard metrics per run (scripts/gt_scorecard.py, same GT, same method).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as gs  # noqa: E402

KEYS = ("rides_full_selected", "rides_ge95_selected", "missing_seconds_total", "excluded_frames_selected", "nonride_windows",
        "mixed_reels", "split_athletes", "published", "published_correct", "published_wrong_identity",
        "published_nonride", "correct_reels_withheld", "reels")


def apply_policy(manifest: dict) -> tuple[dict, list[dict]]:
    out = copy.deepcopy(manifest)
    changed = []
    for arow in out.get("athletes") or []:
        for part in arow.get("parts") or []:
            qi = part.get("qualification_inputs") or {}
            ident = qi.get("identity") or {}
            events = qi.get("events") or []
            if not events:
                changed.append({"athlete_key": arow.get("athlete_key"), "result": "NOT_REPLAYABLE"})
                continue
            sources = {e.get("source_sha256") for e in events}
            if ident.get("basis") == "identity_gate_pass_with_image_evidence" and len(sources) > 1:
                if part.get("publishable") is True:
                    changed.append({"athlete_key": arow.get("athlete_key"), "result": "WITHHELD",
                                    "sources": sorted(s[:12] for s in sources if s)})
                part["publishable"] = False
    return out, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--gt", type=Path, default=gs.DEFAULT_GT)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    gt = gs._load(a.gt)
    report = []
    for d in a.dirs:
        manifest = gs._load(d / "publishable_reel_manifest.json")
        pred = d / "predictions.v1.json"
        predictions = gs._load(pred) if pred.exists() else None
        base = gs.evaluate(gt, manifest, predictions)["metrics"]
        cand_manifest, changed = apply_policy(manifest)
        cand = gs.evaluate(gt, cand_manifest, predictions)["metrics"]
        row = {"run": str(d), "run_id": manifest.get("pipeline_run_id"), "changed_parts": changed,
               "baseline": {k: base.get(k) for k in KEYS}, "candidate": {k: cand.get(k) for k in KEYS}}
        report.append(row)
        print(f"== {d} (run {row['run_id']}): {sum(1 for c in changed if c['result'] == 'WITHHELD')} part(s) withheld, "
              f"{sum(1 for c in changed if c['result'] == 'NOT_REPLAYABLE')} not replayable")
        for k in KEYS:
            if base.get(k) != cand.get(k):
                print(f"   {k}: {base.get(k)} -> {cand.get(k)}")
    if a.out:
        a.out.write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
