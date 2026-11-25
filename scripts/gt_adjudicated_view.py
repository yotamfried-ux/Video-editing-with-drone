#!/usr/bin/env python3
"""Evaluation-plane view of one frozen run: approved-GT metrics UNCHANGED, plus where they rest on contested labels.

The strict scorecard (gt_scorecard.py) scores against the approved GT-v1 labels and stays the release metric. This view
adds, without editing GT:
  * excluded frames broken down by evaluation/adjudications items: under independent adjudication (ADJ-*), owner
    policy cases (POL-*, e.g. an uncatalogued rider), and unadjudicated (true prohibited footage);
  * pixel attribution from primary_athlete_audit.py (GT boxes vs the rendered subject box): a reel is mixed only when
    its frames show more than one GT athlete - time overlap alone is not proof (owner rule, cycle 14b);
  * policy violations: a published reel of an uncatalogued rider (POL-14-001: identity review, never auto-publish).

usage: gt_adjudicated_view.py --diagnostics DIR --pixel-audit AUDIT.json [--adjudications FILE] [--out FILE]
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

DEFAULT_ADJ = ROOT / "evaluation" / "adjudications" / "cycle14_requests.json"


def _gt_rows(gt: dict) -> dict:
    rows = {}
    for m in gt["members"]:
        c = m["content"] if isinstance(m["content"], dict) else json.loads(m["content"])
        rows[m["sha256"]] = {"fps": c["fps_num"] / c["fps_den"], "segments": c.get("segments", [])}
    return rows


def view(diag: Path, audit: dict, adjudications: dict, gt: dict) -> dict:
    card = sc.evaluate(gt, json.loads((diag / "publishable_reel_manifest.json").read_text()),
                       json.loads((diag / "predictions.v1.json").read_text()))
    parts, _ = sc.rendered_windows(json.loads((diag / "publishable_reel_manifest.json").read_text()),
                                   json.loads((diag / "predictions.v1.json").read_text()))
    rows = _gt_rows(gt)
    items = adjudications.get("items", [])
    breakdown: Counter = Counter()
    for part in parts:
        for w in part["windows"]:
            row = rows.get(w["sha"])
            if not row:
                continue
            a, b = int(round(w["a_sec"] * row["fps"])), int(round(w["b_sec"] * row["fps"]))
            for seg in row["segments"]:
                if seg.get("decision") != "exclude":
                    continue
                lo, hi = max(a, int(seg["start_frame"])), min(b, int(seg["end_frame"]))
                if hi <= lo:
                    continue
                owner = next((it["id"] for it in items if it.get("source_sha256") == w["sha"]
                              and (("frames" in it and min(hi, it["frames"][1]) > max(lo, it["frames"][0]))
                                   or ("frames" not in it))), None)
                breakdown[owner or "unadjudicated"] += hi - lo
    pixel_mixed = [r["output_id"] for r in audit.get("reels", []) if r.get("mixed")]
    pol = {it["source_sha256"] for it in items if it["id"].startswith("POL")}
    published = {p["key"] for p in parts if p["publishable"]}
    uncatalogued_published = []
    for r in audit.get("reels", []):
        for shot in r.get("shots", []):
            if shot.get("source_sha256") in pol and shot.get("verdict") == "WRONG_PERSON":
                key = next((p["key"] for p in parts if p["publishable"] and any(w["sha"] == shot["source_sha256"]
                                                                                for w in p["windows"])), None)
                if key in published:
                    uncatalogued_published.append(r["output_id"])
    m = card["metrics"]
    return {"schema": "sportreel.gt_adjudicated_view.v1", "approved_gt_metrics": m,
            "excluded_frames_breakdown": dict(breakdown),
            "excluded_frames_unadjudicated": breakdown.get("unadjudicated", 0),
            "mixed_reels_time_overlap": m["mixed_reels"], "mixed_reels_pixel": len(pixel_mixed),
            "pixel_mixed_reel_ids": pixel_mixed,
            "published_uncatalogued_rider_reels": sorted(set(uncatalogued_published)),
            "note": "approved_gt_metrics are the release metric; breakdowns only show which numbers rest on contested labels"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", type=Path, required=True)
    ap.add_argument("--pixel-audit", type=Path, required=True)
    ap.add_argument("--adjudications", type=Path, default=DEFAULT_ADJ)
    ap.add_argument("--gt", type=Path, default=sc.DEFAULT_GT)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    out = view(a.diagnostics, json.loads(a.pixel_audit.read_text()), json.loads(a.adjudications.read_text()),
               json.loads(a.gt.read_text()))
    text = json.dumps(out, indent=1)
    if a.out:
        a.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
