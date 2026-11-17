#!/usr/bin/env python3
"""Generate docs/production-readiness/PIPELINE-EVIDENCE-MATRIX.md from evaluation/evidence/registry.json.

The registry is the single source of truth; `--check` fails when the committed matrix is out of date.
Status rules enforced here: MEDIA_VERIFIED needs a frame-sequence/overlay/visual evidence item, HOLDOUT_VERIFIED is
rejected while no blind set exists, PRODUCTION_QUALIFIED is rejected without a production run reference.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "evaluation/evidence/registry.json"
OUT = ROOT / "docs/production-readiness/PIPELINE-EVIDENCE-MATRIX.md"
VISUAL = {"frame_sequence", "tracking_overlay", "visual_identity"}


def validate(reg: dict) -> list[str]:
    errs = []
    kinds = {e["id"]: e["kind"] for e in reg["evidence"]}
    for item in reg["fixes"] + reg["gaps"]:
        st = item["status"]
        if st not in reg["statuses"]:
            errs.append(f"{item['id']}: unknown status {st}")
        missing = [e for e in item.get("evidence", []) if e not in kinds]
        if missing:
            errs.append(f"{item['id']}: unknown evidence {missing}")
        if st == "MEDIA_VERIFIED" and not any(kinds.get(e) in VISUAL for e in item.get("evidence", [])):
            errs.append(f"{item['id']}: MEDIA_VERIFIED without visual evidence")
        if st == "HOLDOUT_VERIFIED":
            errs.append(f"{item['id']}: HOLDOUT_VERIFIED needs a blind set, none registered")
        if st == "PRODUCTION_QUALIFIED" and not item.get("production_run"):
            errs.append(f"{item['id']}: PRODUCTION_QUALIFIED without a production run")
    return errs


def render(reg: dict) -> str:
    L = ["# Pipeline evidence matrix", "",
         f"Generated from `evaluation/evidence/registry.json` by `scripts/build_evidence_matrix.py` — do not edit by hand.",
         f"GT: {reg['gt']}. Runs compared: baseline {reg['comparison_runs']['baseline']}, latest {reg['comparison_runs']['latest']}.", "",
         "## Fixes (Gap → root cause → fix → commit → experiment → before/after → evidence → status)", ""]
    for f in reg["fixes"]:
        L += [f"### {f['id']} — {f['title']}", "",
              f"- **Gap:** {f['gap']} · **Classification:** {f['classification']} · **Status:** `{f['status']}`",
              f"- **Root cause:** {f['root_cause']}", f"- **Fix:** {f['change']}", f"- **Commit:** {f['commit']}",
              f"- **Experiments:** {', '.join(f['experiments'])}", f"- **Before:** {f['before']}", f"- **After:** {f['after']}",
              f"- **Evidence:** {', '.join(f['evidence'])}"]
        if f.get("limits"):
            L.append(f"- **Limits:** {f['limits']}")
        L.append("")
    L += ["## Gaps", "", "| ID | Case | Product | Classification | Status | Finding | Next |", "|---|---|---|---|---|---|---|"]
    for g in reg["gaps"]:
        L.append(f"| {g['id']} | {g['case']} | {g['product']} | {g['classification']} | `{g['status']}` | "
                 f"{g['finding']} | {g.get('next') or g.get('fix', '')} |")
    L += ["", "## Primary-athlete scenarios", "", "| ID | Scenario | Result | Status |", "|---|---|---|---|"]
    for p in reg["primary_athlete_scenarios"]:
        L.append(f"| {p['id']} | {p['scenario']} | {p['result']} | `{p['status']}` |")
    L += ["", "## Evidence", "", "| ID | Kind | What | Where |", "|---|---|---|---|"]
    for e in reg["evidence"]:
        L.append(f"| {e['id']} | {e['kind']} | {e['what']} | {e['where']} |")
    L += ["", "## Blockers", ""] + [f"- **{b['id']}** {b['what']}" for b in reg["blockers"]]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    reg = json.loads(REG.read_text())
    errs = validate(reg)
    for e in errs:
        print("INVALID", e)
    text = render(reg)
    if a.check:
        ok = OUT.exists() and OUT.read_text() == text and not errs
        print("matrix up to date" if ok else "matrix out of date or invalid")
        return 0 if ok else 1
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
