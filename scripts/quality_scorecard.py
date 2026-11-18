#!/usr/bin/env python3
"""Cycle 11 quality scorecard (PA-16, PQ-36): one table that does not rely on the time-overlap 'mixed' metric.

Combines, for one run's diagnostics:
  * scripts/gt_scorecard.py (GT-v1 segments): FULL / >=95 % rides, missing include seconds, excluded frames,
    publishable / correct, split athletes, the legacy time-attributed `mixed_reels`
  * scripts/primary_athlete_audit.py output (GT BOXES vs the rendered crop path): VISIBLE mixed reels, wrong-actor
    frames (crop showing another GT athlete or an uncatalogued person instead of the primary), identity switches
and adds, from the rendered windows against GT-v1:
  * non_gt_seconds: rendered seconds inside no include and no exclude segment (waiting, gaps, tails)
  * incorrect_starts / incorrect_ends: rides whose start / end error exceeds the 0.5 s tolerance
  * qa_false_pass: publishable but not correct; qa_false_reject: correct but not publishable (withheld)
  * cycle 12 (PA-01 policy, docs/production-readiness/UNCATALOGUED-PERSON-POLICY.md): reels of a person who is in no
    GT-v1 include segment are reported apart - publishable_non_gt_person (time attribution finds no GT athlete) and
    non_gt_person_reels_audited (crop follows a person with no GT box: no GT athlete shown). They are NEVER counted
    as a GT success; qa_false_pass_gt_cohort excludes them so the GT-cohort QA error is visible on its own. The
    legacy qa_false_pass is unchanged for comparability. Whether such a reel shows a VALID action of the new person
    needs its own evidence (viewed MP4), recorded in the evidence registry, not inferred here.

usage: quality_scorecard.py --diagnostics DIR --audit AUDIT.json [--gt GT.json] [--out OUT.json]
The GT boxes behind the audit are private (never committed); this script reads only the audit's aggregates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as gs  # noqa: E402


def non_gt_seconds(gt: dict, manifest: dict, predictions: dict | None) -> float:
    truth = gs.load_gt(gt)
    parts, _ = gs.rendered_windows(manifest, predictions)
    by_src: dict[str, list[tuple[int, int]]] = {}
    for p in parts:
        for w in p["windows"]:
            src = truth.get(w["sha"])
            if src:
                fps = src["fps"]
                by_src.setdefault(w["sha"], []).append((int(round(w["a_sec"] * fps)), int(round(w["b_sec"] * fps))))
    total = 0.0
    for sha, spans in by_src.items():
        src = truth[sha]
        u = gs._union(spans)
        covered = gs._union([(r["start_frame"], r["end_frame"]) for r in src["rides"]] + list(src["excludes"]))
        inside = sum(gs._len(gs._clip(u, a, b)) for a, b in covered)
        total += (gs._len(u) - inside) / src["fps"]
    return round(total, 2)


def build(diagnostics: Path, audit: dict, gt: dict) -> dict:
    manifest = gs._load(diagnostics / "publishable_reel_manifest.json")
    pred_path = diagnostics / "predictions.v1.json"
    predictions = gs._load(pred_path) if pred_path.exists() else None
    report = gs.evaluate(gt, manifest, predictions)
    m = report["metrics"]
    wrong_actor = switches = visible_mixed = 0
    for reel in audit.get("reels", []):
        visible_mixed += int(bool(reel.get("mixed")))
        for shot in reel.get("shots", []):
            labels = shot.get("subject_labels") or {}
            primary = shot.get("primary_gt_athlete")
            wrong_actor += sum(v for k, v in labels.items()
                               if k not in ("no_subject", "no_gt_box") and k != primary)
            switches += int(shot.get("identity_switches") or 0)
    non_gt_audited = sum(1 for reel in audit.get("reels", []) if reel.get("shots") and not reel.get("gt_athletes_shown")
                         and all(not s.get("primary_gt_athlete") and not s.get("other_gt_athletes_in_crop")
                                 for s in reel["shots"]))
    rides = report["rides"]
    tol = gs.BOUNDARY_TOLERANCE_SEC
    parts = report["reels"]
    non_gt_published = sum(1 for p in parts if p.get("publishable") and not p.get("athletes"))
    return {
        "run_id": report.get("run_id"), "gt_digest": report.get("gt_digest"),
        "full_rides": m["rides_full_selected"], "ge95_rides": m["rides_ge95_selected"], "gt_rides": m["gt_rides"],
        "missing_include_seconds": m["missing_seconds_total"],
        "excluded_frames": m["excluded_frames_selected"],
        "non_gt_seconds": non_gt_seconds(gt, manifest, predictions),
        "incorrect_starts": sum(1 for r in rides if (r.get("start_error_sec") or 0) > tol),
        "incorrect_ends": sum(1 for r in rides if (r.get("end_error_sec") or 0) > tol),
        "wrong_actor_frames_audited": wrong_actor, "identity_switches": switches,
        "visible_mixed_reels": visible_mixed, "time_attributed_mixed_reels": m["mixed_reels"],
        "split_athletes": m["split_athletes"], "duplicate_ride_frames": m["duplicate_ride_frames"],
        "reels": m["reels"], "publishable": m["published"], "publishable_correct": m["published_correct"],
        "qa_false_pass": m["published"] - m["published_correct"],
        "qa_false_reject": m["correct_reels_withheld"],
        "publishable_non_gt_person": non_gt_published,
        "non_gt_person_reels_audited": non_gt_audited,
        "qa_false_pass_gt_cohort": m["published"] - m["published_correct"] - non_gt_published,
        "publishable_wrong_identity": m["published_wrong_identity"],
        "correct_reels": sum(1 for p in parts if p.get("correct")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--audit", required=True, type=Path)
    ap.add_argument("--gt", type=Path, default=gs.DEFAULT_GT)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    row = build(a.diagnostics, json.loads(a.audit.read_text()), gs._load(a.gt))
    if a.out:
        a.out.write_text(json.dumps(row, indent=1))
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
