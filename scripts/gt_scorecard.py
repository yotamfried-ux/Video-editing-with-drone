#!/usr/bin/env python3
"""Strict, fail-closed product scorecard of one pipeline run against the owner's frozen Ground Truth.

Evaluation only: nothing in pipeline/ or integrations/ may read the GT (see test_gt_scorecard_contract.py).

Unit of evidence: a *rendered window* = one event of one reel part in publishable_reel_manifest.json, carrying
source_sha256 and a source interval in seconds (interval.rendered_window, else source_frame_range_sec). Windows are
converted to frames with the GT's exact rational fps. Missing sha / interval / unknown source => that reel is
BLOCKED for the affected metrics (never counted as correct, never silently dropped).

Differences from the draft scripts/gt_product_check.py of PR #391 (PQ-07, PQ-08, PQ-16, PQ-21, PQ-36):
  * coverage is the UNION of intervals (an overlap is never counted twice) and is reported as
    ANY / >=50% / >=95% / FULL with the missing seconds of each ride - "covered" is not "complete";
  * excluded frames are a union too, and are counted for every rendered window;
  * boundary error is reported in seconds, per ride, with max and p95 (a mean hides the worst ride);
  * a ride is only RECALLED when a publishable, correct reel contains it FULL;
  * every protected metric is compared; a missing/None metric on either side is an error, not a skip;
  * a window's athlete is attributed from per-event source sha, not from a file-name string.

usage: gt_scorecard.py --diagnostics DIR [--gt FILE] [--baseline FILE] [--out FILE]
exit : 0 clean, 1 regression, 2 blocked / malformed input.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GT = ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json"
SCHEMA = "sportreel.gt_scorecard.v1"
BOUNDARY_TOLERANCE_SEC = 0.5     # owner target: start/end within 0.5 s
ATTRIBUTION_SHARE = 0.3          # a window belongs to a ride's athlete when it covers >= 30 % of the window ...
ATTRIBUTION_SEC = 2.0            # ... or more than 2 s of that ride
RIDE_GAP_FRAMES = 3              # HEURISTIC (PQ-19): same-athlete include segments <= 3 frames apart are one ride

# direction: +1 = higher is better, -1 = lower is better. EVERY key must exist on both sides (fail closed).
PROTECTED: dict[str, int] = {
    "rides_recalled_published_full": +1,
    "rides_full_selected": +1,
    "rides_any_selected": +1,
    "published_correct": +1,
    "correct_reels_withheld": -1,
    "nonride_windows": -1,
    "excluded_frames_selected": -1,
    "wrong_actor_reels": -1,
    "mixed_reels": -1,
    "split_athletes": -1,
    "duplicate_ride_frames": -1,
    "published_wrong_identity": -1,
    "published_nonride": -1,
    "boundary_max_error_sec": -1,
    "blocked_windows": -1,
}


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- intervals
def _union(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(s for s in spans if s[1] > s[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _len(spans: list[tuple[int, int]]) -> int:
    return sum(b - a for a, b in spans)


def _clip(spans: list[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    return [(max(a, lo), min(b, hi)) for a, b in spans if min(b, hi) > max(a, lo)]


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


# ---------------------------------------------------------------- ground truth
def load_gt(gt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """sha256 -> {fps, rides[], excludes[]}; rides carry a synthetic ride_uid (heuristic, see PQ-19)."""
    out: dict[str, dict[str, Any]] = {}
    for member in gt.get("members") or []:
        content = member.get("content")
        content = json.loads(content) if isinstance(content, str) else (content or {})
        fps = float(content["fps_num"]) / float(content["fps_den"])
        segs = list(content.get("segments") or [])
        rides: list[dict[str, Any]] = []
        for seg in sorted((s for s in segs if s.get("decision") == "include"), key=lambda s: s["start_frame"]):
            last = rides[-1] if rides else None
            if last and last["athlete_id"] == seg.get("athlete_id") and seg["start_frame"] - last["end_frame"] <= RIDE_GAP_FRAMES:
                last["end_frame"] = max(last["end_frame"], seg["end_frame"])
            else:
                rides.append({"athlete_id": seg.get("athlete_id"), "start_frame": seg["start_frame"],
                              "end_frame": seg["end_frame"]})
        for i, r in enumerate(rides):
            r["ride_uid"] = f"{member['sha256'][:12]}#R{i}"
        excludes = [(s["start_frame"], s["end_frame"]) for s in segs if s.get("decision") == "exclude"]
        out[member["sha256"]] = {"fps": fps, "rides": rides, "excludes": excludes}
    return out


# ---------------------------------------------------------------- run windows
def _lineage_windows(arow: dict[str, Any], name_to_sha: dict[str, set[str]], blocked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LEGACY evidence level (runs before per-event lineage): action_lineage 'path|start|end|kind' strings.
    A basename that maps to zero or several source hashes is BLOCKED - a file name is not an identity."""
    wins = []
    for line in arow.get("action_lineage") or []:
        bits = str(line).split("|")
        shas = name_to_sha.get(bits[0].split("/")[-1], set()) if len(bits) >= 3 else set()
        if len(shas) != 1:
            blocked.append({"athlete_key": arow.get("athlete_key"), "reason": "legacy_lineage_unmapped_or_ambiguous",
                            "line": str(line)[:120]})
            continue
        wins.append({"sha": next(iter(shas)), "a_sec": float(bits[1]), "b_sec": float(bits[2]), "event_uid": None})
    return wins


def rendered_windows(manifest: dict[str, Any], predictions: dict[str, Any] | None = None
                     ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (parts, blocked). Each part: {key, publishable, windows[{sha, a_sec, b_sec, event_uid}]}"""
    parts: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    name_to_sha: dict[str, set[str]] = defaultdict(set)
    for src in (predictions or {}).get("sources") or []:
        if src.get("source_video") and src.get("source_sha256"):
            name_to_sha[src["source_video"]].add(src["source_sha256"])
    for arow in manifest.get("athletes") or []:
        if not isinstance(arow, dict):
            blocked.append({"reason": "athlete_row_not_object"})
            continue
        for part in arow.get("parts") or []:
            wins: list[dict[str, Any]] = []
            for ev in ((part.get("qualification_inputs") or {}).get("events")) or []:
                sha = ev.get("source_sha256")
                iv = ev.get("interval") or {}
                rng = iv.get("rendered_window") or ev.get("source_frame_range_sec")
                if not sha or not isinstance(rng, (list, tuple)) or len(rng) != 2 or rng[1] <= rng[0]:
                    blocked.append({"athlete_key": arow.get("athlete_key"), "event_uid": ev.get("event_uid"),
                                    "reason": "missing_sha_or_interval"})
                    continue
                wins.append({"sha": sha, "a_sec": float(rng[0]), "b_sec": float(rng[1]), "event_uid": ev.get("event_uid")})
            if not (part.get("qualification_inputs") or {}).get("events") and predictions is not None:
                wins = _lineage_windows(arow, name_to_sha, blocked)   # legacy: whole-reel lineage on every part
            if not wins and not (part.get("qualification_inputs") or {}).get("events") and predictions is None:
                blocked.append({"athlete_key": arow.get("athlete_key"), "reason": "part_has_no_event_lineage"})
            parts.append({"key": f"{arow.get('athlete_key')}#{part.get('part_index')}",
                          "publishable": part.get("publishable") is True, "windows": wins,
                          "lineage_blocked": any(b.get("athlete_key") == arow.get("athlete_key") for b in blocked)})
    return parts, blocked


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, math.ceil(q * len(s)) - 1)]


def evaluate(gt: dict[str, Any], manifest: dict[str, Any], predictions: dict[str, Any] | None = None) -> dict[str, Any]:
    truth = load_gt(gt)
    parts, blocked = rendered_windows(manifest, predictions)

    per_part: list[dict[str, Any]] = []
    part_ride_spans: dict[tuple[str, str], dict[str, list[tuple[int, int]]]] = {}
    sel_by_ride: dict[str, list[tuple[int, int]]] = defaultdict(list)   # selected windows clipped to a ride
    all_by_source: dict[str, list[tuple[int, int]]] = defaultdict(list)
    ride_hits_per_part: dict[str, dict[str, list[tuple[int, int]]]] = {}
    unknown_source = 0

    for part in per_part_iter(parts):
        athletes, nonride, ride_spans = set(), 0, defaultdict(list)
        for w in part["windows"]:
            src = truth.get(w["sha"])
            if src is None:
                unknown_source += 1          # an input outside GT-v1: UNKNOWN, never counted as correct
                part["has_unknown"] = True
                continue
            fps = src["fps"]
            a, b = int(round(w["a_sec"] * fps)), int(round(w["b_sec"] * fps))
            all_by_source[w["sha"]].append((a, b))
            attributed = False
            for r in src["rides"]:
                ov = _overlap(a, b, r["start_frame"], r["end_frame"])
                if ov and (ov >= ATTRIBUTION_SHARE * max(1, b - a) or ov > ATTRIBUTION_SEC * fps):
                    athletes.add(r["athlete_id"])
                    attributed = True
                if ov:
                    ride_spans[r["ride_uid"]].append((max(a, r["start_frame"]), min(b, r["end_frame"])))
                    sel_by_ride[r["ride_uid"]].append((max(a, r["start_frame"]), min(b, r["end_frame"])))
            if not attributed:
                nonride += 1
        part["athletes"] = sorted(athletes)
        part["nonride_windows"] = nonride
        part["ride_spans"] = dict(ride_spans)
        per_part.append(part)

    # ---- excluded frames: union per source, once
    excluded = 0
    for sha, spans in all_by_source.items():
        u = _union(spans)
        for ex in truth[sha]["excludes"]:
            excluded += _len(_clip(u, ex[0], ex[1]))
    for p in per_part:
        ex_p = 0
        by_src: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for w in p["windows"]:
            src = truth.get(w["sha"])
            if src:
                by_src[w["sha"]].append((int(round(w["a_sec"] * src["fps"])), int(round(w["b_sec"] * src["fps"]))))
        for sha, spans in by_src.items():
            for ex in truth[sha]["excludes"]:
                ex_p += _len(_clip(_union(spans), ex[0], ex[1]))
        p["excluded_frames"] = ex_p

    # ---- per ride coverage (union), buckets, missing seconds, boundary error
    ride_rows, starts, ends, dup_frames = [], [], [], 0
    for sha, src in truth.items():
        for r in src["rides"]:
            span = r["end_frame"] - r["start_frame"]
            raw = sel_by_ride.get(r["ride_uid"], [])
            u = _union(raw)
            dup_frames += max(0, sum(b - a for a, b in raw) - _len(u))
            cov = _len(u)
            row = {"ride_uid": r["ride_uid"], "source_sha256": sha, "athlete_id": r["athlete_id"],
                   "frames": span, "covered_frames": cov, "missing_sec": round((span - cov) / src["fps"], 2),
                   "any": cov > 0, "ge50": cov >= 0.5 * span, "ge95": cov >= 0.95 * span}
            if u:
                s_err = abs(u[0][0] - r["start_frame"]) / src["fps"]
                e_err = abs(u[-1][1] - r["end_frame"]) / src["fps"]
                row.update(start_error_sec=round(s_err, 2), end_error_sec=round(e_err, 2))
                starts.append(s_err)
                ends.append(e_err)
                row["full"] = (cov >= span - 2 * BOUNDARY_TOLERANCE_SEC * src["fps"]
                               and s_err <= BOUNDARY_TOLERANCE_SEC and e_err <= BOUNDARY_TOLERANCE_SEC)
            else:
                row["full"] = False
            ride_rows.append(row)
    ride_by_uid = {r["ride_uid"]: r for r in ride_rows}

    # ---- reels
    athlete_parts: dict[str, set[str]] = defaultdict(set)
    for p in per_part:
        for a in p["athletes"]:
            athlete_parts[a].add(p["key"])
        p["mixed"] = len(p["athletes"]) > 1
        clean = (len(p["athletes"]) == 1 and p["nonride_windows"] == 0 and p["excluded_frames"] == 0
                 and not p.get("has_unknown") and not p["lineage_blocked"])
        p["correct"] = clean
    recalled = set()
    for p in per_part:
        if p["publishable"] and p["correct"]:
            for uid in p["ride_spans"]:
                if ride_by_uid[uid]["full"]:
                    recalled.add(uid)
    published = [p for p in per_part if p["publishable"]]
    boundary_errs = starts + ends
    metrics = {
        "gt_rides": len(ride_rows),
        "rides_any_selected": sum(r["any"] for r in ride_rows),
        "rides_ge50_selected": sum(r["ge50"] for r in ride_rows),
        "rides_ge95_selected": sum(r["ge95"] for r in ride_rows),
        "rides_full_selected": sum(r["full"] for r in ride_rows),
        "rides_recalled_published_full": len(recalled),
        "missing_seconds_total": round(sum(r["missing_sec"] for r in ride_rows), 1),
        "duplicate_ride_frames": dup_frames,
        "nonride_windows": sum(p["nonride_windows"] for p in per_part),
        "excluded_frames_selected": excluded,
        "boundary_max_error_sec": round(max(boundary_errs), 2) if boundary_errs else None,
        "boundary_p95_error_sec": round(_pct(boundary_errs, 0.95), 2) if boundary_errs else None,
        "boundary_over_tolerance": sum(1 for e in boundary_errs if e > BOUNDARY_TOLERANCE_SEC),
        "reels": len(per_part),
        "mixed_reels": sum(p["mixed"] for p in per_part),
        "wrong_actor_reels": sum(1 for p in per_part if p["mixed"]),
        "split_athletes": sum(1 for v in athlete_parts.values() if len(v) > 1),
        "published": len(published),
        "published_correct": sum(p["correct"] for p in published),
        "published_wrong_identity": sum(p["mixed"] for p in published),
        "published_nonride": sum(1 for p in published if p["nonride_windows"] or p["excluded_frames"]),
        "correct_reels_withheld": sum(1 for p in per_part if p["correct"] and not p["publishable"]),
        "blocked_windows": len(blocked),
        "unknown_source_windows": unknown_source,
    }
    return {"schema": SCHEMA, "run_id": manifest.get("pipeline_run_id"), "gt_dataset_id": gt.get("dataset_id"),
            "gt_digest": gt.get("digest"), "ride_unit": "HEURISTIC_same_athlete_include_gap_le_3_frames",
            "metrics": metrics, "rides": ride_rows, "blocked": blocked,
            "reels": [{k: p[k] for k in ("key", "publishable", "athletes", "mixed", "nonride_windows",
                                         "excluded_frames", "correct")} for p in per_part]}


def per_part_iter(parts: list[dict[str, Any]]):
    for p in parts:
        yield dict(p)


def compare(metrics: dict[str, Any], baseline: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (regressions, errors). A missing/None protected metric is an ERROR (exit 2), never a skip."""
    regressions, errors = [], []
    for key, direction in PROTECTED.items():
        now, then = metrics.get(key), baseline.get(key)
        if now is None or then is None:
            errors.append(f"{key}: missing (baseline={then!r}, current={now!r})")
            continue
        if (now < then) if direction > 0 else (now > then):
            regressions.append(f"{key}: {then} -> {now}")
    return regressions, errors


def absolute_release_gate(metrics: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Post-inference GT release gate: absolute P0 targets, never baseline-only comparison.

    Evaluation-side only. A clean metric gate is NOT a blind-holdout, media,
    isolation or production qualification certificate. Returns (failures, errors).
    """
    zero_keys = (
        "excluded_frames_selected", "nonride_windows", "duplicate_ride_frames",
        "mixed_reels", "split_athletes", "published_wrong_identity",
        "published_nonride", "wrong_actor_reels", "blocked_windows",
        "unknown_source_windows", "boundary_over_tolerance",
        "correct_reels_withheld",
    )
    required = ("gt_rides", "rides_full_selected", "rides_recalled_published_full",
                "boundary_max_error_sec", *zero_keys)
    errors: list[str] = []
    for key in required:
        value = metrics.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            errors.append(f"{key}: missing, invalid or negative: {value!r}")
    if errors:
        return [], errors
    failures = [f"{key}: expected 0, got {metrics[key]}" for key in zero_keys if metrics[key] != 0]
    total = metrics["gt_rides"]
    if total <= 0:
        errors.append("gt_rides: must contain at least one fully adjudicated ride")
    for key in ("rides_full_selected", "rides_recalled_published_full"):
        if metrics[key] != total:
            failures.append(f"{key}: expected {total} of {total}, got {metrics[key]}")
    if metrics["boundary_max_error_sec"] > BOUNDARY_TOLERANCE_SEC:
        failures.append(f"boundary_max_error_sec: {metrics['boundary_max_error_sec']} > {BOUNDARY_TOLERANCE_SEC}")
    return failures, errors

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--gt", type=Path, default=DEFAULT_GT)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--absolute-release-gate", action="store_true",
                    help="post-run P0 metric veto (not a production certification)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    try:
        pred_path = args.diagnostics / "predictions.v1.json"
        report = evaluate(_load(args.gt), _load(args.diagnostics / "publishable_reel_manifest.json"),
                          _load(pred_path) if pred_path.exists() else None)
    except (OSError, ValueError, KeyError) as exc:
        print(f"BLOCKED malformed or absent input: {exc}")
        return 2
    code = 0
    if args.baseline:
        base = _load(args.baseline)
        report["baseline"] = {"run_id": base.get("run_id"), "metrics": base.get("metrics")}
        reg, err = compare(report["metrics"], base.get("metrics") or {})
        report["regressions"], report["errors"] = reg, err
        code = 2 if err else (1 if reg else 0)
    if args.absolute_release_gate:
        failures, errors = absolute_release_gate(report["metrics"])
        report["absolute_release_gate"] = {
            "verdict": "BLOCKED" if failures or errors else "METRIC_GATE_PASS",
            "failures": failures, "errors": errors,
            "scope": "post-inference GT metric gate only; external isolation/media/holdout proofs still required",
        }
        code = 2 if errors else (max(code, 1) if failures else code)
        for entry in errors:
            print(f"RELEASE BLOCKED {entry}")
        for entry in failures:
            print(f"RELEASE FAIL {entry}")
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    m = report["metrics"]
    print(" | ".join(f"{k}={m[k]}" for k in ("gt_rides", "rides_any_selected", "rides_ge95_selected",
                                               "rides_full_selected", "rides_recalled_published_full",
                                               "published", "published_correct", "correct_reels_withheld",
                                               "nonride_windows", "excluded_frames_selected", "mixed_reels",
                                               "split_athletes", "boundary_max_error_sec", "blocked_windows")))
    for line in report.get("errors") or []:
        print(f"BLOCKED {line}")
    for line in report.get("regressions") or []:
        print(f"REGRESSION {line}")
    return code


if __name__ == "__main__":
    sys.exit(main())
