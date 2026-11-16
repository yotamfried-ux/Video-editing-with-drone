#!/usr/bin/env python3
"""Quality-restore contracts (run 43920602179 vs GT-v1) and the product-level GT check.

R1  Image evidence recorded on an internal cluster (with the run-local `_clip_index`) still covers the same cluster
    after `identity._strip_internal_fields`, and the real identity gate passes it. Before: the evidence key used
    `_clip_index`, the gate key used the file name, and all five verified multi-source athletes were withheld.
R2  Evidence still does not cover a cluster whose membership changed.
R3  Batch qualification: an athlete withheld for identity is REVIEW_REQUIRED even when a shot ends at the recording
    end; SOURCE_LIMITED only when the recording end is the sole blocking reason.
G1  gt_product_check measures covered rides, non-ride selections, excluded frames, mixed reels, split athletes and
    published correct / wrong / non-ride reels on a synthetic GT.
G2  compare() reports a regression in either direction of the metric and none for an equal run.
G3  Inference never reads the GT: no file under pipeline/ or integrations/ names evaluation/ground_truth.
G4  The committed baseline is the 2026-11-14 run and the frozen GT has 24 sources.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)


def _thumbs(n: int) -> list[str]:
    folder = tempfile.mkdtemp()
    out = []
    for i in range(n):
        path = os.path.join(folder, f"t{i}.jpg")
        Path(path).write_bytes(b"thumb%d" % i)
        out.append(path)
    return out


def r1_r2_identity_evidence() -> None:
    from pipeline import identity_evidence as ie
    from pipeline.real_identity_gate import enforce_identity_gate
    from pipeline.stages.identity import _strip_internal_fields

    thumbs = _thumbs(2)
    internal = {"description": "same surfer", "appearances": [
        {"path": "/tmp/dtor/A_0160_D.MP4", "_clip_index": 3, "_person_id": "person_A", "thumbnail": thumbs[0],
         "events": [{"person_id": "person_A", "track_id": "10003"}]},
        {"path": "/tmp/dtor/B_0163_D.MP4", "_clip_index": 7, "_person_id": "person_A", "thumbnail": thumbs[1],
         "events": [{"person_id": "person_A", "track_id": "10001"}]},
    ]}
    ie.stamp(internal, ie.IMAGE_VERIFIER, images=thumbs, model="gemini-2.5-flash", raw_response='{"same_person": true}')
    check(ie.covers(internal), f"R1: evidence must cover the cluster it was recorded on: {ie.coverage_problem(internal)}")
    stripped = _strip_internal_fields([internal])[0]
    check(ie.covers(stripped), f"R1: evidence lost after strip: {ie.coverage_problem(stripped)} {ie.members(stripped)}")
    gated = enforce_identity_gate([stripped])
    check(len(gated) == 1 and gated[0].get("_identity_gate") == "pass",
          f"R1: verified two-source athlete must pass the gate: {[(c.get('_identity_gate'), c.get('_identity_gate_reason')) for c in gated]}")

    changed = json.loads(json.dumps(stripped))
    changed["appearances"].append({"path": "/tmp/dtor/C_0155_D.MP4", "events": [{"person_id": "person_A"}]})
    check(ie.coverage_problem(changed) == "evidence_does_not_cover_current_members",
          "R2: evidence must not cover a cluster that gained a member")


def r3_batch_labels() -> None:
    import write_batch_qualification as wbq

    def part(blocking: list[str], noted: bool) -> dict:
        notes = ["source_limited_recording_end"] if noted else []
        return {"part_index": 1, "publishable": False, "technical_issues": blocking, "qa_verdict": "PASS",
                "qualification_inputs": {"events": [{"interval": {"notes": notes}}]},
                "output_qualification": {"blocking": blocking}}

    manifest = {"athletes": [
        {"athlete_key": "identity_held", "eligible": True,
         "parts": [part(["qualification:identity_identity_gate_kept_together_unconfirmed",
                         "qualification:tail_after_actor_lost_to_recording_end:ev2_x"], True)]},
        {"athlete_key": "recording_end_only", "eligible": True,
         "parts": [part(["qualification:tail_after_actor_lost_to_recording_end:ev2_y"], True)]},
    ]}
    states = {a["athlete_key"]: a["state"] for a in wbq.build(manifest, exit_code=0)["athletes"]}
    check(states.get("identity_held") == "REVIEW_REQUIRED", f"R3: identity-withheld athlete mislabelled: {states}")
    check(states.get("recording_end_only") == "SOURCE_LIMITED", f"R3: recording-end-only athlete mislabelled: {states}")


def _synthetic():
    fps = 60.0
    gt = {"dataset_id": "t", "digest": "d", "members": [
        {"sha256": "s1", "content": {"segments": [{"start_frame": 0, "end_frame": 600, "decision": "include", "athlete_id": "A"}]}},
        {"sha256": "s2", "content": {"segments": [{"start_frame": 0, "end_frame": 600, "decision": "include", "athlete_id": "B"}]}},
        {"sha256": "s3", "content": {"segments": [{"start_frame": 0, "end_frame": 300, "decision": "exclude", "athlete_id": None}]}},
        {"sha256": "s4", "content": {"segments": [{"start_frame": 0, "end_frame": 600, "decision": "include", "athlete_id": "A"}]}},
    ]}
    preds = {"run_id": "r", "pipeline_commit": "c", "sources": [
        {"source_sha256": f"s{i}", "source_video": f"v{i}.MP4", "fps": fps,
         "events": [{"decision": "selected", "start_frame": 0, "end_frame": 540}]} for i in (1, 2, 3, 4)]}
    lineage = lambda v: f"/tmp/{v}.MP4|0.0|9.0|surf_ride"
    manifest = {"athletes": [
        {"athlete_key": "mixed", "action_lineage": [lineage("v1"), lineage("v2")], "parts": [{"publishable": True}]},
        {"athlete_key": "nonride", "action_lineage": [lineage("v3")], "parts": [{"publishable": True}]},
        {"athlete_key": "a_again", "action_lineage": [lineage("v4")], "parts": [{"publishable": False}]},
    ]}
    return gt, preds, manifest


def g1_g2_check() -> None:
    import gt_product_check as g

    gt, preds, manifest = _synthetic()
    m = g.evaluate(gt, preds, manifest)["metrics"]
    expect = {"gt_rides": 3, "rides_covered": 3, "nonride_selections": 1, "excluded_frames_selected": 300,
              "reels": 3, "mixed_reels": 1, "split_athletes": 1, "published": 2, "published_correct": 0,
              "published_wrong_identity": 1, "published_nonride": 1, "correct_reels_withheld": 1}
    for key, value in expect.items():
        check(m.get(key) == value, f"G1: {key} = {m.get(key)}, expected {value}")
    check(g.compare(m, m) == [], "G2: an equal run must not regress")
    better = {**m, "published_correct": 2, "mixed_reels": 0}
    regs = g.compare(m, better)
    check(any(r.startswith("published_correct") for r in regs) and any(r.startswith("mixed_reels") for r in regs),
          f"G2: fewer correct reels and more mixed reels must regress: {regs}")
    check(g.compare(better, m) == [], "G2: an improvement must not regress")


def g3_inference_isolation() -> None:
    offenders = []
    for folder in ("pipeline", "integrations"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "evaluation/ground_truth" in text or "gtv1_frozen" in text or "gt_product_check" in text:
                offenders.append(str(path.relative_to(ROOT)))
    check(not offenders, f"G3: inference code reads the GT: {offenders}")


def g4_committed_files() -> None:
    gt = json.loads((ROOT / "evaluation/ground_truth/gtv1_frozen.json").read_text(encoding="utf-8"))
    base = json.loads((ROOT / "evaluation/ground_truth/baseline.json").read_text(encoding="utf-8"))
    check(len(gt.get("members") or []) == 24, "G4: frozen GT-v1 must hold 24 sources")
    check(base.get("github_run_id") == "43583126199" and base.get("gt_digest") == gt.get("digest"),
          "G4: baseline must be run 43583126199 on the same GT digest")


def main() -> int:
    for fn in (r1_r2_identity_evidence, r3_batch_labels, g1_g2_check, g3_inference_isolation, g4_committed_files):
        try:
            fn()
        except Exception as exc:  # a crash is a failure of that contract, not of the runner
            FAILURES.append(f"{fn.__name__}: {type(exc).__name__}: {exc}")
    if FAILURES:
        print("FAIL: gt product check / quality restore")
        for f in FAILURES:
            print(" -", f)
        return 1
    print("PASS: gt product check / quality restore (identity evidence after strip, batch labels, GT metrics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
