#!/usr/bin/env python3
"""Pure logic of the boundary experiment (no model, no media).

B1  The clip is cut from the PIPELINE candidate (never the GT), with room before and after.
B2  The verifier answer is read strictly: finite, ordered start <= takeoff <= end inside the clip, ride=true; anything
    else is None (never a guessed time).
B3  Errors are signed seconds against the GT; the summary counts tolerance hits (0.5 s) per boundary and for both.
B4  The experiment writes only its JSON result (no media outside the job temp dir).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boundary_experiment as bx  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def b1():
    a, b = bx.clip_window(20.0, 30.0)
    check((a, b) == (8.0, 36.0), f"B1 window {a, b}")
    check(bx.clip_window(2.0, 5.0)[0] == 0.0, "B1 start clamps at 0")
    check(bx.clip_window(20.0, 30.0, duration=31.0)[1] == 31.0, "B1 end clamps at the recording end")


def b2():
    ok = json.dumps({"ride": True, "paddle_start": 1.0, "takeoff": 4.0, "ride_end": 9.0, "ride_end_kind": "fall", "evidence": "x"})
    check(bx.parse_boundaries(ok, 20.0) is not None, "B2 valid")
    for bad in ('', 'not json', '{}', '{"ride": false}', '[]',
                json.dumps({"ride": True, "paddle_start": 5, "takeoff": 4, "ride_end": 9}),          # unordered
                json.dumps({"ride": True, "paddle_start": 1, "takeoff": 4, "ride_end": 99}),         # outside the clip
                json.dumps({"ride": True, "paddle_start": -1, "takeoff": 4, "ride_end": 9}),
                json.dumps({"ride": True, "paddle_start": "a", "takeoff": 4, "ride_end": 9}),
                json.dumps({"ride": True, "paddle_start": 1, "takeoff": 4})):
        check(bx.parse_boundaries(bad, 20.0) is None, f"B2 {bad!r} must be rejected")


def b3():
    v = bx.parse_boundaries(json.dumps({"ride": True, "paddle_start": 2.0, "takeoff": 5.0, "ride_end": 9.0}), 20.0)
    e = bx.boundary_errors(v, 10.0, ride_start_sec=11.7, ride_end_sec=18.0)
    check(e["start_err"] == 0.3 and e["end_err"] == 1.0, f"B3 {e}")
    rows = [{"verifier": {"start_err": 0.3, "end_err": 0.4}}, {"verifier": {"start_err": -0.9, "end_err": 0.1}}, {"verifier": None}]
    s = bx.summarize(rows, "verifier")
    check((s["evaluated"], s["within_tol_start"], s["within_tol_end"], s["both_within_tol"]) == (2, 1, 2, 1), f"B3 {s}")


def b4():
    src = (ROOT / "scripts" / "boundary_experiment.py").read_text(encoding="utf-8")
    check(src.count("write_text") == 1 and "write_bytes" not in src, "B4 only the JSON result is written")
    check("gt_start" not in src.split("def _cut")[1].split("def main")[0], "B4 the clip cut never sees the GT")


for case in (b1, b2, b3, b4):
    try:
        case()
    except Exception as exc:
        FAILURES.append(f"{case.__name__} crashed: {exc!r}")
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("boundary experiment contract: all cases passed")
