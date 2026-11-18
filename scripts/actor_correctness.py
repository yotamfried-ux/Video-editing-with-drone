#!/usr/bin/env python3
"""Frame-level actor correctness of the rendered tracked crops, against the live Ground Truth boxes.

GT-v1 as frozen in the repo only has segments; the live Annotation Studio revision also carries per-athlete boxes
(`tracks`, sparse keyframes). With them a rendered window can be checked frame by frame: the pipeline's tracked crop
(`outputs[].track_id` -> `predictions.sources[].tracks[].samples[].bbox`) is compared with every GT athlete's box
(linear interpolation between GT keyframes) and each window gets the GT athlete it actually followed.

    actor_correctness.py --run-dir DIR --gt-boxes gt_boxes.json [--out FILE]

`gt_boxes.json` = {source_sha256: {"fps": f, "tracks": [{"athlete_id": id, "points": [[frame, x, y, w, h], ...]}]}}.
It is derived from private footage annotations and is NOT committed; only aggregate results are.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

CONTAIN_MATCH = 0.5  # median share of the pipeline's person box that lies inside the GT athlete box
MIN_FRAMES = 5       # compared frames needed for a verdict


def containment(a: tuple, b: tuple) -> float:
    """Share of the pipeline box `a` that lies inside the GT box `b`.

    The GT box encloses the athlete and the board; the pipeline tracks the person only, so IoU would be small even
    for the right surfer (measured: median IoU 0.17 on a correctly followed ride). A different person is not inside
    the GT athlete box at all, so containment separates them.
    """
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return (ix * iy) / (aw * ah) if aw * ah > 0 else 0.0


def interp(points: list[list[float]], frame: int, max_gap: int = 30):
    """GT box at `frame` (linear between keyframes, None when the nearest keyframes are more than max_gap apart)."""
    frames = [p[0] for p in points]
    i = bisect.bisect_left(frames, frame)
    if i < len(frames) and frames[i] == frame:
        return tuple(points[i][1:5])
    if i == 0 or i == len(points) or points[i][0] - points[i - 1][0] > max_gap:
        return None
    f0, f1 = points[i - 1][0], points[i][0]
    t = (frame - f0) / (f1 - f0)
    return tuple(points[i - 1][k] + t * (points[i][k] - points[i - 1][k]) for k in range(1, 5))


def median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2] if s else 0.0


def check(predictions: dict[str, Any], gt_boxes: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for src in predictions.get("sources") or []:
        gt = gt_boxes.get(src.get("source_sha256"))
        if not gt:
            continue
        tracks = {str(t["track_id"]): sorted(t.get("samples") or [], key=lambda s: s["src_frame"])
                  for t in src.get("tracks") or []}
        for ev in src.get("events") or []:
            if ev.get("decision") != "selected":
                continue
            for out in ev.get("outputs") or []:
                tid = str(out.get("track_id")) if out.get("track_id") is not None else None
                samples = tracks.get(tid) or []
                per_ath: dict[str, list[float]] = defaultdict(list)
                compared = 0
                for s in samples:
                    f = int(s["src_frame"])
                    if not (ev["start_frame"] <= f <= ev["end_frame"]):
                        continue
                    b = s["bbox"]
                    box = (b["x"], b["y"], b["w"], b["h"])
                    seen = False
                    for t in gt["tracks"]:
                        g = interp(t["points"], f)
                        if g is not None:
                            per_ath[t["athlete_id"]].append(containment(box, g))
                            seen = True
                    compared += seen
                best = max(per_ath.items(), key=lambda kv: median(kv[1]), default=(None, []))
                rows.append({"source_sha256": src["source_sha256"], "source_video": src.get("source_video"),
                             "event_id": out.get("event_id"), "output_id": out.get("output_id"), "track_id": tid,
                             "mode": out.get("mode"), "frames": [ev["start_frame"], ev["end_frame"]],
                             "compared_frames": compared, "followed_athlete": best[0] if compared >= MIN_FRAMES else None,
                             "median_containment": round(median(best[1]), 3) if best[1] else 0.0,
                             "followed_ok": bool(best[0]) and compared >= MIN_FRAMES and median(best[1]) >= CONTAIN_MATCH})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--gt-boxes", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rows = check(json.loads((a.run_dir / "predictions.v1.json").read_text()), json.loads(a.gt_boxes.read_text()))
    summary = {"windows": len(rows), "followed_ok": sum(r["followed_ok"] for r in rows),
               "unverifiable": sum(r["compared_frames"] < MIN_FRAMES for r in rows),
               "not_following_any_gt_athlete": sum(1 for r in rows if r["compared_frames"] >= MIN_FRAMES and not r["followed_ok"])}
    print(json.dumps(summary))
    if a.out:
        a.out.write_text(json.dumps({"summary": summary, "windows": rows}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
