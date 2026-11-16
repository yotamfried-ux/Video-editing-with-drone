#!/usr/bin/env python3
"""The GT review package classifies pipeline/GT disagreements without touching inference.

A tiny diagnostics fixture: one wrong merge (two GT athletes in one cluster), one missed merge (one GT athlete
split over two clusters), one excluded segment that was rendered (usability), one excluded tail that was rendered
(event boundary). Every case is VISUAL_REVIEW_REQUIRED.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    import build_gt_review_package as pkg

    with tempfile.TemporaryDirectory() as folder:
        d = Path(folder)
        (d / "edl").mkdir()
        m = lambda s: f"2026_DJI_X_{s}_D.MP4::person_A"
        (d / "identity_trace.json").write_text(json.dumps({"layers": {"model": [], "compile": [
            {"members": [m("0001"), m("0002")], "flags": {"_identity_gate_reason": "visual_verified_per_source_tracks"}},
            {"members": [m("0003")]}, {"members": [m("0004")]}, {"members": [m("0005")]}]}}))
        (d / "candidate_decision_ledger.json").write_text(json.dumps({"candidates": []}))
        (d / "publishable_reel_manifest.json").write_text(json.dumps({"athletes": []}))
        shots = [("0005", 0, 300), ("0002", 60, 540)]
        for i, (src, start_frame, out_frames) in enumerate(shots):
            (d / "edl" / f"r{i}.edl.json").write_text(json.dumps({"output_id": f"r{i}", "shots": [
                {"source_file": f"DJI_X_{src}_D.MP4", "src_start": start_frame, "out_start": 0, "out_end": out_frames,
                 "source": {"fps": 60.0}, "event_id": f"ev2_{i}"}]}))
        seg = lambda a, b, decision, athlete: {"start_frame": str(a), "end_frame": str(b), "decision": decision,
                                               "usability": "usable" if decision == "include" else "unusable",
                                               "reasons": [], "athlete": athlete}
        gt = [
            {"src": "0001_D", "fps_num": 60, "fps_den": 1, "duration_ms": 9000, "segments": [seg(0, 500, "include", "A")]},
            {"src": "0002_D", "fps_num": 60, "fps_den": 1, "duration_ms": 12000,
             "segments": [seg(0, 400, "include", "B"), seg(400, 700, "exclude", "B")]},
            {"src": "0003_D", "fps_num": 60, "fps_den": 1, "duration_ms": 8000, "segments": [seg(0, 400, "include", "C")]},
            {"src": "0004_D", "fps_num": 60, "fps_den": 1, "duration_ms": 8000, "segments": [seg(0, 400, "include", "C")]},
            {"src": "0005_D", "fps_num": 60, "fps_den": 1, "duration_ms": 6000, "segments": [seg(0, 360, "exclude", "D")]},
        ]
        cases = {c["source"]: c for c in pkg.build(d, gt, set())}
        expect = {"0001": "identity_wrong_merge:0002", "0003": "identity_missed_merge:0004",
                  "0005": "usability", "0002": "event_boundary"}
        for source, kind in expect.items():
            if kind not in cases[source]["disagreement"]:
                raise SystemExit(f"{source}: expected {kind}, got {cases[source]['disagreement']}")
        if any(c["status"] != "VISUAL_REVIEW_REQUIRED" for c in cases.values()):
            raise SystemExit("every case needs visual review")
    print("PASS: GT review package classifies identity, usability and boundary disagreements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
