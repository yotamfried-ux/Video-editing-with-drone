#!/usr/bin/env python3
"""Product-level comparison of one pipeline run with the owner's frozen Ground Truth (evaluation only).

Reads the run's diagnostics (predictions.v1.json for the selected windows, publishable_reel_manifest.json for the
reels and whether each one is publishable) and the frozen GT export (evaluation/ground_truth/gtv1_frozen.json).
Nothing here feeds inference: the pipeline never reads the GT (scripts/test_gt_product_check_contract.py checks it).

Measured per run:
  selection  - GT rides covered (>= 50 % of the ride's frames), selected windows with no GT ride, frames selected
               inside segments the owner marked exclude, mean start/end error to the ride.
  identity   - reels mixing GT athletes, GT athletes split over several reels.
  publishing - reels publishable, of which correct (one GT athlete, only GT rides, no excluded frames), with a
               wrong athlete, with a non-ride; correct reels withheld.

With --baseline, a run regresses when it covers fewer rides, publishes fewer correct reels, or has more mixed reels,
split athletes, wrong/non-ride published reels or non-ride selections than the baseline. Exit 1 on regression.

usage: gt_product_check.py --diagnostics DIR [--gt FILE] [--baseline FILE] [--out FILE]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GT = ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json"
SCHEMA = "sportreel.gt_product_check.v1"
RIDE_COVERAGE = 0.5          # a GT ride counts as covered when >= 50 % of its frames are selected
ATTRIBUTION_SHARE = 0.3      # a reel window belongs to a GT athlete when it overlaps >= 30 % of the window...
ATTRIBUTION_FRAMES = 120     # ...or more than 2 s (at ~60 fps) of that athlete's ride

# Lower is better for these; higher is better for the rest of REGRESSION_KEYS.
LOWER_IS_BETTER = {"mixed_reels", "split_athletes", "published_wrong_identity", "published_nonride",
                   "nonride_selections", "excluded_frames_selected"}
REGRESSION_KEYS = ["rides_covered", "published_correct", "mixed_reels", "split_athletes",
                   "published_wrong_identity", "published_nonride", "nonride_selections"]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _segments(gt: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for member in gt.get("members") or []:
        content = member.get("content")
        content = json.loads(content) if isinstance(content, str) else (content or {})
        out[member["sha256"]] = list(content.get("segments") or [])
    return out


def _rides(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contiguous include segments of one athlete form one physical ride (GT-v1 splits rides into manoeuvres)."""
    rides: list[dict[str, Any]] = []
    for seg in sorted((s for s in segments if s.get("decision") == "include"), key=lambda s: s["start_frame"]):
        last = rides[-1] if rides else None
        if last and last["athlete_id"] == seg.get("athlete_id") and seg["start_frame"] - last["end_frame"] <= 3:
            last["end_frame"] = max(last["end_frame"], seg["end_frame"])
        else:
            rides.append({"athlete_id": seg.get("athlete_id"), "start_frame": seg["start_frame"],
                          "end_frame": seg["end_frame"]})
    return rides


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def evaluate(gt: dict[str, Any], predictions: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    segs = _segments(gt)
    rides = {sha: _rides(s) for sha, s in segs.items()}
    names = {s.get("source_video"): s for s in predictions.get("sources") or []}
    by_sha = {s.get("source_sha256"): s for s in predictions.get("sources") or []}

    # --- selection: every selected window of the run, against the rides of its source
    covered_frames: dict[tuple[str, int], int] = defaultdict(int)
    nonride, excluded, start_err, end_err = [], 0, [], []
    for sha, src in by_sha.items():
        if sha not in segs:
            continue
        for ev in src.get("events") or []:
            if ev.get("decision") != "selected":
                continue
            a, b = int(ev["start_frame"]), int(ev["end_frame"])
            hits = [(i, _overlap(a, b, r["start_frame"], r["end_frame"])) for i, r in enumerate(rides[sha])]
            hits = [(i, ov) for i, ov in hits if ov > 0]
            for i, ov in hits:
                covered_frames[(sha, i)] += ov
            if not hits:
                nonride.append({"source": src.get("source_video"), "start_frame": a, "end_frame": b})
            else:
                best = rides[sha][max(hits, key=lambda h: h[1])[0]]
                start_err.append(abs(a - best["start_frame"]))
                end_err.append(abs(b - best["end_frame"]))
            excluded += sum(_overlap(a, b, s["start_frame"], s["end_frame"])
                            for s in segs[sha] if s.get("decision") == "exclude")
    ride_total = sum(len(r) for r in rides.values())
    rides_covered = sum(1 for sha, rs in rides.items() for i, r in enumerate(rs)
                        if covered_frames[(sha, i)] >= RIDE_COVERAGE * max(1, r["end_frame"] - r["start_frame"]))

    # --- reels: which GT athletes each reel shows, and whether it is publishable
    fps_of = {sha: float(s.get("fps") or 59.94) for sha, s in by_sha.items()}
    reels, athlete_reels = [], defaultdict(set)
    for index, row in enumerate(manifest.get("athletes") or []):
        if not isinstance(row, dict):
            continue
        publishable = any(p.get("publishable") is True for p in row.get("parts") or [])
        athletes, has_nonride, excl, windows = set(), False, 0, []
        for line in row.get("action_lineage") or []:
            parts = str(line).split("|")
            if len(parts) < 3:
                continue
            src = names.get(parts[0].split("/")[-1])
            if not src or src.get("source_sha256") not in segs:
                continue
            sha = src["source_sha256"]
            fps = fps_of.get(sha, 59.94)
            a, b = int(float(parts[1]) * fps), int(float(parts[2]) * fps)
            windows.append(f"{src.get('source_video')}[{float(parts[1]):.1f}-{float(parts[2]):.1f}]")
            on_ride = False
            for r in rides[sha]:
                ov = _overlap(a, b, r["start_frame"], r["end_frame"])
                if ov > 0:
                    on_ride = True
                if ov >= ATTRIBUTION_SHARE * max(1, b - a) or ov > ATTRIBUTION_FRAMES:
                    athletes.add(r["athlete_id"])
            has_nonride = has_nonride or not on_ride
            excl += sum(_overlap(a, b, s["start_frame"], s["end_frame"])
                        for s in segs[sha] if s.get("decision") == "exclude")
        if not windows:
            continue
        for athlete in athletes:
            athlete_reels[athlete].add(index)
        correct = len(athletes) == 1 and not has_nonride and excl == 0
        reels.append({"athlete_key": row.get("athlete_key"), "publishable": publishable, "gt_athletes": sorted(athletes),
                      "mixed": len(athletes) > 1, "nonride": has_nonride, "excluded_frames": excl,
                      "correct": correct, "windows": windows})

    published = [r for r in reels if r["publishable"]]
    metrics = {
        "gt_rides": ride_total,
        "rides_covered": rides_covered,
        "nonride_selections": len(nonride),
        "excluded_frames_selected": excluded,
        "mean_start_error_frames": round(sum(start_err) / len(start_err), 1) if start_err else None,
        "mean_end_error_frames": round(sum(end_err) / len(end_err), 1) if end_err else None,
        "reels": len(reels),
        "mixed_reels": sum(1 for r in reels if r["mixed"]),
        "split_athletes": sum(1 for v in athlete_reels.values() if len(v) > 1),
        "published": len(published),
        "published_correct": sum(1 for r in published if r["correct"]),
        "published_wrong_identity": sum(1 for r in published if r["mixed"]),
        "published_nonride": sum(1 for r in published if r["nonride"] or r["excluded_frames"]),
        "correct_reels_withheld": sum(1 for r in reels if r["correct"] and not r["publishable"]),
    }
    return {"schema": SCHEMA, "run_id": predictions.get("run_id"), "pipeline_commit": predictions.get("pipeline_commit"),
            "gt_dataset_id": gt.get("dataset_id"), "gt_digest": gt.get("digest"), "metrics": metrics,
            "nonride_selections": nonride, "reels": reels}


def compare(metrics: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    regressions = []
    for key in REGRESSION_KEYS:
        now, then = metrics.get(key), baseline.get(key)
        if now is None or then is None:
            continue
        worse = now > then if key in LOWER_IS_BETTER else now < then
        if worse:
            regressions.append(f"{key}: {then} -> {now}")
    return regressions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--gt", type=Path, default=DEFAULT_GT)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    report = evaluate(_load(args.gt), _load(args.diagnostics / "predictions.v1.json"),
                      _load(args.diagnostics / "publishable_reel_manifest.json"))
    if args.baseline:
        base = _load(args.baseline)
        report["baseline"] = {"run_id": base.get("run_id"), "metrics": base.get("metrics")}
        report["regressions"] = compare(report["metrics"], base.get("metrics") or {})
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    m = report["metrics"]
    print(f"rides covered {m['rides_covered']}/{m['gt_rides']} | non-ride selections {m['nonride_selections']} | "
          f"excluded frames {m['excluded_frames_selected']} | reels {m['reels']} (mixed {m['mixed_reels']}, "
          f"split athletes {m['split_athletes']}) | published {m['published']}: correct {m['published_correct']}, "
          f"wrong athlete {m['published_wrong_identity']}, non-ride {m['published_nonride']} | "
          f"correct withheld {m['correct_reels_withheld']}")
    for line in report.get("regressions") or []:
        print(f"REGRESSION {line}")
    return 1 if report.get("regressions") else 0


if __name__ == "__main__":
    sys.exit(main())
