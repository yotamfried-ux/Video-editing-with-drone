#!/usr/bin/env python3
"""A/B perception on real footage: direct 4K decode vs single-decode intermediate.

Run on the sources that have human Ground Truth in Annotation Studio, before trusting the single-decode
path on a new camera/codec. For each video it runs the real producer twice and reports wall time and how
closely the two sidecars agree on identical frames (box IoU, confidence). The end-to-end acceptance gate
remains the blind Ground-Truth evaluation of the run's predictions.v1 export in Annotation Studio.

    python scripts/ab_perception_decode.py VIDEO.MP4 [VIDEO2.MP4 ...] --model yolo11n.pt [--out ab_out/]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(video: str, out: Path, model: str, single: bool) -> float:
    env = {**os.environ, "SPORTREEL_SINGLE_DECODE": "1" if single else "0", "SPORTREEL_PERCEPTION_WRITE_PROXY": "0"}
    t = time.monotonic()
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_perception_sidecar.py"), video, str(out),
         "--backend", "ultralytics", "--ultralytics-model", model],
        check=True, env=env,
    )
    return time.monotonic() - t


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def compare(ref_path: Path, new_path: Path) -> dict:
    """Greedy IoU>=0.5 matching per frame, only on frames both sidecars sampled."""
    def load(path: Path):
        by = defaultdict(list)
        for det in json.loads(path.read_text(encoding="utf-8")).get("detections", []):
            by[det["frame_index"]].append(det)
        return by

    ref, new = load(ref_path), load(new_path)
    common = sorted(set(ref) & set(new))
    matched, ious, dconf, ref_n, new_n = 0, [], [], 0, 0
    for frame in common:
        used: set[int] = set()
        ref_n += len(ref[frame])
        new_n += len(new[frame])
        for det in ref[frame]:
            best, best_j = 0.0, None
            for j, cand in enumerate(new[frame]):
                if j not in used:
                    value = _iou(det["bbox_xyxy"], cand["bbox_xyxy"])
                    if value > best:
                        best, best_j = value, j
            if best_j is not None and best >= 0.5:
                used.add(best_j)
                matched += 1
                ious.append(best)
                dconf.append(abs((det.get("confidence") or 0) - (new[frame][best_j].get("confidence") or 0)))
    ious.sort()
    dconf.sort()
    return {
        "common_frames": len(common),
        "frames_only_direct": len(set(ref) - set(new)),
        "frames_only_single": len(set(new) - set(ref)),
        "direct_boxes_on_common_frames": ref_n,
        "single_boxes_on_common_frames": new_n,
        "matched_share_of_direct": round(matched / ref_n, 4) if ref_n else None,
        "median_iou": round(ious[len(ious) // 2], 4) if ious else None,
        "median_abs_conf_delta": round(dconf[len(dconf) // 2], 4) if dconf else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--model", default=os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "yolo11n.pt"))
    parser.add_argument("--out", default="ab_perception_out")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for video in args.videos:
        stem = Path(video).stem
        direct, single = out / f"{stem}.direct.json", out / f"{stem}.single.json"
        t_direct = _run(video, direct, args.model, single=False)
        t_single = _run(video, single, args.model, single=True)
        row = {"video": video, "direct_seconds": round(t_direct, 1), "single_decode_seconds": round(t_single, 1),
               **compare(direct, single)}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {out / 'report.json'}")
    print("Note: when the two passes pick different weak windows the escalated frames differ; compare matched "
          "share on common frames, then confirm with the blind Ground-Truth evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
