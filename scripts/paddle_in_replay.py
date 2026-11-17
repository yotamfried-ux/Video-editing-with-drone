#!/usr/bin/env python3
"""EXP-08-003: frozen replay of a candidate paddle-in start rule (evaluation only; no model, no media).

Candidate: open the cut at the analyzer's own `setup_start` ("paddle into position") beyond the 2 s lead-in cap when a
SAME-BODY backward chain shows the target continuously present from that time (person boxes on consecutive samples,
centre within CHAIN_DIST of the frame, height ratio 0.5-2, no gap > CHAIN_GAP; the chain may cross track-id
fragments, e.g. the stitched canonical track and its raw / high-res duplicates). Then the existing source-start snap.
Both steps call the PRODUCTION functions (`complete_action_window_policy.extend_to_setup` with the cap lifted and the
chain's first time as `setup_first_track_sec`; `extend_to_recording_start` with the chain's first time as
`track_continuous_from_sec`). Baseline = the run's rendered start. Scored against GT-v1 per ride; regression = a
start that gets worse by > 0.1 s or leaves the 0.5 s tolerance.

usage: paddle_in_replay.py --diagnostics DIR --out FILE
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402
from identity_pair_experiment import build_appearances  # noqa: E402
from pipeline import complete_action_window_policy as pol  # noqa: E402
from pipeline import window_refinement as wr  # noqa: E402
from pipeline.perception.runtime import _detections_from_payload  # noqa: E402

CHAIN_DIST, CHAIN_GAP, TOL = 0.04, 0.45, 0.5


def setup_starts(diag: Path) -> dict[str, float]:
    """source file stem -> analyzer setup_start, from the run's identity trace."""
    d = json.loads((diag / "identity_trace.json").read_text())
    out: dict[str, float] = {}

    def walk(o, src=None):
        if isinstance(o, dict):
            for k in ("source_video", "path", "video", "source", "clip"):
                if isinstance(o.get(k), str) and o[k].upper().endswith(".MP4"):
                    src = o[k]
            if o.get("setup_start") is not None and src:
                m = re.search(r"_(\d{4})_D", src)
                if m:
                    out.setdefault(m.group(1), float(o["setup_start"]))
            for v in o.values():
                walk(v, src)
        elif isinstance(o, list):
            for v in o:
                walk(v, src)
    walk(d)
    return out


def chain_from(dets: list[tuple], track: str, anchor: float) -> float | None:
    own = [x for x in dets if x[5] == track and x[0] >= anchor - 1.0]
    if not own:
        return None
    cur = own[0]
    while True:
        prev = [x for x in dets if cur[0] - CHAIN_GAP <= x[0] < cur[0] - 1e-6
                and math.hypot(x[1] - cur[1], x[2] - cur[2]) <= CHAIN_DIST and cur[4] and 0.5 <= x[4] / cur[4] <= 2]
        if not prev:
            return round(cur[0], 2)
        cur = max(prev, key=lambda x: (x[0], -math.hypot(x[1] - cur[1], x[2] - cur[2])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    gt = json.loads(sc.DEFAULT_GT.read_text())
    manifest = json.loads((a.diagnostics / "publishable_reel_manifest.json").read_text())
    truth, apps = sc.load_gt(gt), build_appearances(gt, manifest)
    setup = setup_starts(a.diagnostics)
    side, names, prod_dets = {}, {}, {}
    for f in glob.glob(str(a.diagnostics / "sidecars" / "*.perception.json")):
        p = json.loads(Path(f).read_text())
        rows = []
        for d in p["detections"]:
            if d.get("class_name") != "person":
                continue
            x0, y0, x1, y1 = d["bbox_xyxy"]
            W, H = d["frame_width"], d["frame_height"]
            rows.append((d["time_sec"], (x0 + x1) / 2 / W, (y0 + y1) / 2 / H, (x1 - x0) / W, (y1 - y0) / H, str(d.get("track_id"))))
        side[p["source_sha256"]] = sorted(rows)
        prod_dets[p["source_sha256"]] = _detections_from_payload(p.get("source_video", ""), p)
        m = re.search(r"_(\d{4})_D", p.get("source_video", ""))
        names[p["source_sha256"]] = m.group(1) if m else p["source_sha256"][:12]
    table = []
    saved_cap = pol.SETUP_LEAD_IN_MAX_SEC
    for sha, t in truth.items():
        for r in t["rides"]:
            cands = [x for x in apps if x["source_sha256"] == sha and x["athlete_id"] == r["athlete_id"]]
            if not cands or sha not in side:
                continue
            app = max(cands, key=lambda x: sc._overlap(int(x["window_sec"][0] * t["fps"]), int(x["window_sec"][1] * t["fps"]),
                                                       r["start_frame"], r["end_frame"]))
            start, gs = app["window_sec"][0], r["start_frame"] / t["fps"]
            if abs(start - gs) > 8:      # a window of another ride of this athlete; start rules cannot fix it
                continue
            name = names[sha]
            # current code (cycle 5): source-start snap on the bound track's own continuous presence
            cont = wr.continuous_presence_from(prod_dets[sha], app["track_id"], start)
            cur = float(pol.extend_to_recording_start({"start": start, "window_refinement": (
                {"track_continuous_from_sec": cont} if cont is not None else {})})["start"])
            cf = chain_from(side[sha], app["track_id"], start)
            new = cur                    # the candidate is layered on top of the current code
            if cf is not None and name in setup:
                ev = {"start": start, "end": app["window_sec"][1], "setup_start": setup[name],
                      "window_refinement": {"setup_first_track_sec": cf, "track_continuous_from_sec": cf}}
                pol.SETUP_LEAD_IN_MAX_SEC = 1e9
                try:
                    ev = pol.extend_to_setup(ev)
                finally:
                    pol.SETUP_LEAD_IN_MAX_SEC = saved_cap
                ev = pol.extend_to_recording_start(ev)
                new = min(cur, float(ev["start"]))
            table.append({"source": name, "ride": r["ride_uid"], "gt_start": round(gs, 2), "setup_start": setup.get(name),
                          "chain_from": cf, "rendered_start": round(start, 2), "start": round(cur, 2), "new_start": round(new, 2),
                          "err_rendered": round(start - gs, 2), "err_before": round(cur - gs, 2), "err_after": round(new - gs, 2)})
    reg = [x for x in table if (abs(x["err_before"]) <= TOL < abs(x["err_after"])) or abs(x["err_after"]) > abs(x["err_before"]) + 0.1]
    imp = [x for x in table if abs(x["err_after"]) < abs(x["err_before"]) - 0.1]
    out = {"baseline": "current code: cycle-5 source-start snap on the bound track (err_before); err_rendered = run's rendered start",
           "experiment": "EXP-08-003", "rule": "setup_start beyond the 2 s cap when a same-body chain proves presence",
           "rides": len(table), "improved": len(imp), "regressions": [x["source"] for x in reg],
           "within_tol_before": sum(abs(x["err_before"]) <= TOL for x in table),
           "within_tol_after": sum(abs(x["err_after"]) <= TOL for x in table),
           "seconds_recovered": round(sum(abs(x["err_before"]) - abs(x["err_after"]) for x in imp), 2),
           "seconds_lost": round(sum(abs(x["err_after"]) - abs(x["err_before"]) for x in reg), 2), "table": table}
    if a.out:
        a.out.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "table"}))
    for x in sorted(table, key=lambda x: x["gt_start"]):
        flag = "MOVED" if x["new_start"] != x["start"] else "     "
        print(f"{flag} {x['source']} GT {x['gt_start']:5} setup {x['setup_start']} chain {x['chain_from']} start {x['start']:5} -> {x['new_start']:5} err {x['err_before']:+.2f} -> {x['err_after']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
