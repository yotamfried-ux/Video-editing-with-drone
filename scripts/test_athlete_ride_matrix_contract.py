#!/usr/bin/env python3
"""Athlete x Ride x Stage matrix: synthetic cases for A/B/C/D and agreement with the committed scorecards."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import athlete_ride_matrix as mx  # noqa: E402

FPS = 60
S1, S2, S3 = "a" * 64, "b" * 64, "c" * 64
ATH_A, ATH_B, ATH_C = "ath-A", "ath-B", "ath-C"


def seg(ath, a, b, decision="include"):
    return {"athlete_id": ath, "decision": decision, "start_frame": a, "end_frame": b, "id": f"{ath}{a}"}


def gt():
    def member(sha, segs):
        return {"sha256": sha, "revision_id": sha[:6], "split": "test",
                "content": {"fps_num": FPS, "fps_den": 1, "segments": segs, "reviewed_ranges": [{"start_frame": 0, "end_frame": 2000}]}}
    return {"dataset_id": "d", "digest": "x" * 64, "members": [
        member(S1, [seg(ATH_A, 100, 700)]),                       # ride A, source 1
        member(S2, [seg(ATH_A, 100, 700), seg(ATH_B, 800, 1000), seg(None, 1100, 1300, "exclude")]),
        member(S3, [seg(ATH_C, 100, 700)])]}                      # athlete C: never selected


def ev(a, b, decision="selected", reason="selected_for_uploaded_draft"):
    return {"candidate_id": f"e{a}", "event_type": "wave_catch", "start_frame": a, "end_frame": b,
            "decision": decision, "reason": reason}


def part(sha, a, b, key="r"):
    return {"qualification_inputs": {"events": [{"source_sha256": sha, "event_uid": f"u{a}",
                                                  "interval": {"rendered_window": [a / FPS, b / FPS]}}]}}


def merge(*parts_):
    """One reel (manifest part) holding the windows of several parts."""
    return {"qualification_inputs": {"events": [e for p in parts_ for e in p["qualification_inputs"]["events"]]}}


def manifest(rows):
    athletes = []
    for key, parts_, pub in rows:
        athletes.append({"athlete_key": key, "business_outcome": "publishable_ready" if pub else "review_or_upload_required",
                         "blocking_reasons": [] if pub else ["qa_gate:X"],
                         "parts": [dict(p, part_index=i + 1, publishable=pub, qa_verdict="PASS", state="UPLOADED")
                                   for i, p in enumerate(parts_)]})
    return {"pipeline_run_id": "run", "athletes": athletes}


def preds(extra=None):
    srcs = [{"source_sha256": S1, "source_video": "one.mp4", "fps": FPS, "events": [ev(100, 700)], "tracks": []},
            {"source_sha256": S2, "source_video": "two.mp4", "fps": FPS,
             "events": [ev(100, 700), ev(800, 1000)], "tracks": []},
            {"source_sha256": S3, "source_video": "three.mp4", "fps": FPS,
             "events": [ev(100, 700, "rejected", "duplicate_source_window_before_render")], "tracks": []}]
    return {"sources": srcs}


def test_split_excluded_and_no_reel_are_named() -> None:
    m = mx.build(gt(), manifest([
        ("k1", [part(S1, 100, 700)], True),                                   # A ride 1 in reel k1
        ("k2", [merge(part(S2, 100, 700), part(S2, 800, 1000), part(S2, 1100, 1250))], False)]),  # A ride 2 + B + excluded, one reel
        preds())
    by = {a["athlete_id"]: a for a in m["athletes"]}
    assert by[ATH_A]["cardinality"] == "SPLIT" and len(by[ATH_A]["reels"]) == 2, by[ATH_A]          # problem C
    assert by[ATH_B]["cardinality"] == "MIXED", by[ATH_B]                                          # B shares reel k2 with A
    assert by[ATH_C]["cardinality"] == "NO_REEL" and by[ATH_C]["d_no_reel_silent"], by[ATH_C]      # problem D
    assert m["summary"]["B_excluded_frames_union"] == 150, m["summary"]                             # problem B (no GT ride there)
    rc = [r for r in m["rides"] if r["athlete_id"] == ATH_C][0]
    assert rc["first_loss_stage"].startswith("selection_dedup:duplicate_source_window_before_render"), rc


def test_missing_start_is_attributed_to_the_candidate_window() -> None:
    p = preds()
    p["sources"][0]["events"] = [ev(200, 700)]
    m = mx.build(gt(), manifest([("k1", [part(S1, 200, 700)], True)]), p)
    r = [x for x in m["rides"] if x["source_sha256"] == S1][0]
    assert not r["full"] and r["first_loss_stage"] == "event_candidate_window", r
    assert r["rendered_start_err_sec"] == round(100 / FPS, 2)                                      # problem A, measured


def test_agrees_with_committed_scorecards() -> None:
    for run in ("43920602179", "43583126199"):
        mpath = ROOT / "evaluation/matrix" / f"{run}.json"
        spath = ROOT / "evaluation/scorecards" / f"{run}.json"
        if not (mpath.exists() and spath.exists()):
            continue
        m, s = json.loads(mpath.read_text()), json.loads(spath.read_text())["metrics"]
        sm = m["summary"]
        assert sm["rides_full"] == s["rides_full_selected"], (run, sm, s)
        assert sm["B_excluded_frames_union"] == s["excluded_frames_selected"], (run, sm, s)
        assert sm["C_split_athletes"] == s["split_athletes"], (run, sm, s)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"PASS athlete ride matrix contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
