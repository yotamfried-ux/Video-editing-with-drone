#!/usr/bin/env python3
"""Score EXP-14-002 (evaluation plane) against GT-v1 and the cycle-14 adjudication / policy items.

Labels (pre-registered, PREREGISTRATION-EXP-14-002.md):
  valid    window frames mostly (>= 50 %) inside a GT include segment of that source
  valid_policy  window covered by an owner-policy / adjudication item (0108 tail: ADJ-14-001, 0094 13.2-22 s:
           ADJ-14-002, 0095 uncatalogued rider: POL-14-001) - treated as valid riding for false-rejection purposes
  invalid  window frames >= 80 % inside GT exclude segments and not covered by any policy item (0155)
Conditions (any -> FAIL, gate stays OFF): >= 1 valid/valid_policy INVALID; any invalid VALID; > 2 valid UNCERTAIN;
pass agreement < 80 %; any row errored or skipped (not scored = not passed).

usage: score_action_validity_experiment.py --result exp14_002.json [--gt FILE] [--adjudications FILE] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402

ADJ = ROOT / "evaluation" / "adjudications" / "cycle14_requests.json"


def label(row: dict, gt: dict, items: list[dict]) -> str:
    member = next(m for m in gt["members"] if m["sha256"] == row["sha"])
    c = member["content"] if isinstance(member["content"], dict) else json.loads(member["content"])
    fps = c["fps_num"] / c["fps_den"]
    a, b = row["window"][0] * fps, row["window"][1] * fps
    span = max(b - a, 1e-9)

    def share(decision):
        return sum(max(0.0, min(b, s["end_frame"]) - max(a, s["start_frame"])) for s in c["segments"]
                   if s["decision"] == decision) / span
    for it in items:
        if it.get("source_sha256") == row["sha"]:
            if "seconds" not in it or min(row["window"][1], it["seconds"][1]) - max(row["window"][0], it["seconds"][0]) > 0.5 * (row["window"][1] - row["window"][0]):
                return "valid_policy"
    if share("include") >= 0.5:
        return "valid"
    if share("exclude") >= 0.8:
        return "invalid"
    return "other"


def score(result: dict, gt: dict, items: list[dict]) -> dict:
    rows, tally, failures = [], Counter(), []
    agree = total = 0
    for r in result["rows"]:
        lab = label(r, gt, items)
        v = r.get("verdict")
        rows.append({"index": r["index"], "kind": r["kind"], "window": r["window"], "label": lab, "verdict": v,
                     "basis": r.get("basis"), "error": r.get("error"), "skip": r.get("skip")})
        tally[(lab, v)] += 1
        passes = [p for p in (r.get("passes") or []) if p]
        if len(passes) >= 2:
            total += 1
            agree += len({p["established_sec"] >= 2.0 for p in passes}) == 1
        if r.get("error") or r.get("skip"):
            failures.append(f"not scored: {r['index']} {r.get('error') or r.get('skip')}")
        if lab in ("valid", "valid_policy") and v == "INVALID":
            failures.append(f"false rejection of a valid ride: {r['index']} {r['window']}")
        if lab == "invalid" and v == "VALID":
            failures.append(f"invalid action passed as VALID: {r['index']} {r['window']}")
    unc_valid = sum(n for (lab, v), n in tally.items() if lab in ("valid", "valid_policy") and v == "UNCERTAIN")
    if unc_valid > 2:
        failures.append(f"{unc_valid} valid windows UNCERTAIN (> 2 withheld-correct reels)")
    agreement = agree / total if total else 0.0
    if agreement < 0.8:
        failures.append(f"pass agreement {agreement:.0%} < 80 %")
    if result.get("dry_run"):
        failures.append("dry run: no model verdicts (coverage/identity evidence only)")
    return {"schema": "sportreel.exp14_002_score.v1", "dry_run": result.get("dry_run"), "spent_usd": result.get("spent_usd"),
            "tally": {f"{k[0]}:{k[1]}": n for k, n in sorted(tally.items(), key=str)}, "pass_agreement": round(agreement, 3),
            "failures": failures, "decision": "PASS" if not failures else "FAIL", "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", type=Path, required=True)
    ap.add_argument("--gt", type=Path, default=sc.DEFAULT_GT)
    ap.add_argument("--adjudications", type=Path, default=ADJ)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    out = score(json.loads(a.result.read_text()), json.loads(a.gt.read_text()),
                json.loads(a.adjudications.read_text())["items"])
    text = json.dumps(out, indent=1)
    if a.out:
        a.out.write_text(text)
    print(text)
    return 0 if out["decision"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
