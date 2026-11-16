#!/usr/bin/env python3
"""Frozen replay of the source-limited start rule on a stored run (evaluation only: sidecars + manifest, no model, no media).

For every GT ride the pipeline's own rendered window start (manifest) and the target track's detections (the run's frozen
perception sidecar, normalised by the production loader) go through the PRODUCTION functions
(`window_refinement.continuous_presence_from`, `complete_action_window_policy.extend_to_recording_start`). Start errors are
measured against GT-v1 before and after; a regression is a ride whose start error was within 0.5 s and is not any more, or
whose error grew by more than 0.1 s. The whole manifest is then re-scored with the strict scorecard.

usage: boundary_start_replay.py --diagnostics DIR [--out FILE]
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402
from identity_pair_experiment import athlete_split, build_appearances  # noqa: E402
from pipeline import complete_action_window_policy as pol  # noqa: E402
from pipeline import window_refinement as wr  # noqa: E402
from pipeline.perception.runtime import _detections_from_payload  # noqa: E402

TOL = 0.5


def replay(diag: Path) -> dict:
    gt = json.loads(sc.DEFAULT_GT.read_text(encoding="utf-8"))
    manifest = json.loads((diag / "publishable_reel_manifest.json").read_text(encoding="utf-8"))
    truth = sc.load_gt(gt)
    apps = build_appearances(gt, manifest)
    dev_ath, hold_ath = athlete_split([a["athlete_id"] for a in apps])
    side = {}
    for f in glob.glob(str(diag / "sidecars" / "*.perception.json")):
        payload = json.loads(Path(f).read_text(encoding="utf-8"))
        side[payload["source_sha256"]] = _detections_from_payload(payload.get("source_video", ""), payload)
    rows, shifted = [], {}
    for sha, t in truth.items():
        fps = t["fps"]
        for r in t["rides"]:
            cands = [a for a in apps if a["source_sha256"] == sha and a["athlete_id"] == r["athlete_id"]]
            if not cands or sha not in side:
                continue
            a = max(cands, key=lambda a: sc._overlap(int(a["window_sec"][0] * fps), int(a["window_sec"][1] * fps),
                                                     r["start_frame"], r["end_frame"]))
            start = a["window_sec"][0]
            cont = wr.continuous_presence_from(side[sha], a["track_id"], start)
            event = {"start": start, "end": a["window_sec"][1],
                     "window_refinement": ({"track_continuous_from_sec": cont} if cont is not None else {})}
            new = pol.extend_to_recording_start(event)["start"]
            gs = r["start_frame"] / fps
            rows.append({"ride": r["ride_uid"], "split": "holdout" if r["athlete_id"] in hold_ath else "dev",
                         "gt_start": round(gs, 2), "start": round(start, 2), "new_start": round(new, 2),
                         "err_before": round(start - gs, 2), "err_after": round(new - gs, 2), "continuous_from": cont})
            if new != start:
                shifted[(sha, a["track_id"], round(start, 2))] = new
    regressions = [r["ride"] for r in rows
                   if (abs(r["err_before"]) <= TOL < abs(r["err_after"])) or abs(r["err_after"]) > abs(r["err_before"]) + 0.1]
    # re-score the manifest with the shifted starts
    replayed = copy.deepcopy(manifest)
    for arow in replayed.get("athletes") or []:
        for part in arow.get("parts") or []:
            for e in ((part.get("qualification_inputs") or {}).get("events")) or []:
                uid = str(e.get("actor_track_uid") or "")
                rng = (e.get("interval") or {}).get("rendered_window") or e.get("source_frame_range_sec")
                if "#" in uid and rng:
                    new = shifted.get((e.get("source_sha256"), uid.rsplit("#", 1)[1], round(rng[0], 2)))
                    if new is not None:
                        e.setdefault("interval", {})["rendered_window"] = [new, rng[1]]
    before = sc.evaluate(gt, manifest)["metrics"]
    after = sc.evaluate(gt, replayed)["metrics"]
    keys = ("rides_full_selected", "rides_ge95_selected", "missing_seconds_total", "boundary_over_tolerance",
            "boundary_max_error_sec", "excluded_frames_selected", "nonride_windows", "mixed_reels", "published_correct")
    within = lambda f: sum(1 for r in rows if abs(r[f]) <= TOL)
    return {"rides": len(rows), "moved": sum(r["new_start"] != r["start"] for r in rows), "regressions": regressions,
            "start_within_tol_before": within("err_before"), "start_within_tol_after": within("err_after"),
            "by_split": {s: {"rides": sum(r["split"] == s for r in rows),
                             "moved": sum(r["split"] == s and r["new_start"] != r["start"] for r in rows),
                             "within_before": sum(r["split"] == s and abs(r["err_before"]) <= TOL for r in rows),
                             "within_after": sum(r["split"] == s and abs(r["err_after"]) <= TOL for r in rows)}
                         for s in ("dev", "holdout")},
            "scorecard_before": {k: before[k] for k in keys}, "scorecard_after": {k: after[k] for k in keys}, "table": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    result = replay(args.diagnostics)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "table"}, indent=1))
    for r in sorted(result["table"], key=lambda r: r["gt_start"]):
        flag = "MOVED " if r["new_start"] != r["start"] else "      "
        print(f"{flag}{r['ride']:16} {r['split']:7} GT {r['gt_start']:5} start {r['start']:5} -> {r['new_start']:5}  err {r['err_before']:+5} -> {r['err_after']:+5}")
    return 1 if result["regressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
