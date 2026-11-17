#!/usr/bin/env python3
"""Replay of the primary-athlete binding separability rule (pipeline/perception/runtime._binding_separability) on
stored runs: every selected output window, its run's frozen perception sidecar, the production `_best_primary`.

Crop hints are not exported to diagnostics, so the hint is a PROXY: the bound track's centre at the event middle.
Output lists every window (denominator = len(windows)).

usage: binding_replay.py --run RUN_ID=DIAG_DIR [--run ...] --out FILE
"""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.perception.runtime import _best_primary, _in_window  # noqa: E402
from pipeline.perception.schema import PerceptionDetection  # noqa: E402


def replay(run_dir: Path) -> list[dict]:
    pred = json.loads((run_dir / "predictions.v1.json").read_text())
    side = {}
    for p in glob.glob(str(run_dir / "sidecars" / "*.perception.json")):
        d = json.loads(Path(p).read_text())
        side[d["source_sha256"]] = d
    rows = []
    for src in pred["sources"]:
        sc = side.get(src["source_sha256"])
        dets = [] if not sc else [
            PerceptionDetection(source_video="S", frame_index=x["frame_index"], time_sec=x["time_sec"],
                                xyxy=tuple(x["bbox_xyxy"]), frame_width=x["frame_width"], frame_height=x["frame_height"],
                                confidence=x.get("confidence"), class_id=0, class_name="person", tracker_id=x.get("track_id"))
            for x in sc["detections"] if x.get("class_name") == "person"]
        for ev in src["events"]:
            if ev["decision"] != "selected":
                continue
            for out in ev["outputs"]:
                row = {"source": src["source_video"], "event_id": out.get("event_id"), "output_id": out.get("output_id"),
                       "track_id": str(out.get("track_id")), "window_sec": [ev["start_sec"], ev["end_sec"]]}
                e = {"start": ev["start_sec"], "end": ev["end_sec"]}
                win = _in_window(dets, e)
                own = [d for d in win if str(d.tracker_id) == row["track_id"]]
                if not sc or not own:
                    row["status"] = "not_replayable" if not sc else "track_not_in_window"
                    rows.append(row)
                    continue
                mid = (e["start"] + e["end"]) / 2
                ref = min(own, key=lambda d: abs(d.time_sec - mid))
                e.update(crop_x=ref.crop_x, crop_y=ref.crop_y)
                rep: dict = {}
                prim = _best_primary(win, e, track_profiles=sc.get("track_activity_profiles"), binding_report=rep)
                row.update(status=rep.get("track_binding_status", "single_track"), rebound_track=str(prim.tracker_id),
                           runner_up=rep.get("track_binding_runner_up"), evidence=rep.get("track_binding_evidence"))
                rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    per_run, windows = {}, []
    for spec in a.run:
        run_id, d = spec.split("=", 1)
        rows = replay(Path(d))
        for r in rows:
            r["run"] = run_id
        windows += rows
        per_run[run_id] = dict(Counter(r["status"] for r in rows))
    out = {"experiment": "EXP-08-000 (re-run of EXP-07-002 with per-window output)", "executed_code_sha": sha,
           "rule": "pipeline/perception/runtime._binding_separability",
           "hint": "PROXY: bound track centre at the event middle (crop hints not exported)",
           "denominator": len(windows), "status_counts": dict(Counter(r["status"] for r in windows)),
           "per_run": per_run, "windows": windows}
    a.out.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("executed_code_sha", "denominator", "status_counts", "per_run")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
