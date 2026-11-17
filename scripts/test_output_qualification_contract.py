#!/usr/bin/env python3
"""Output qualification (RC-01/02/03/04/05/08 release invariants), through the production manifest functions.

 Q1 RC-03  explicit no-ride is INVALID whatever the score; VALID needs rating + tracked actor + CV activity +
           coherent window; missing evidence or a CV contradiction is UNCERTAIN; a short valid ride is VALID.
 Q2 RC-04  tails past the verified actor, leads before it, unproven track gaps inside the shot and an unvalidated
           actor span block; a measured fall tail does not; a recording-end tail is recorded as source-limited.
 Q3 RC-01  single-source single-actor reels claim nothing; multi-source needs a gate pass with image evidence;
           unconfirmed, ungated, or several actors of one source never publish.
 Q4 RC-08  a shot without canonical event id or content-addressed source blocks.
 Q5        the qualification object derives publishable itself; tampering, specs-digest hashes and failed
           requirements are rejected; record_athlete_outcome turns failures into technical issues.
 Q6        the identity gate's pass carries the digest of the image evidence it rests on.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import os as _os
# Cycle 10 (FIX-PQ-10-001): model-only visual consensus no longer auto-publishes a multi-source cluster by default.
# This contract tests the evidence plumbing behind a pass, so it runs with the explicit opt-in; the default policy
# is covered by scripts/test_identity_autopublish_policy_contract.py.
_os.environ["SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH"] = "1"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))

from _qualification_fixture import qualified  # noqa: E402


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def ev(**over):
    base = qualified({"type": "wave_catch", "start": 10.0, "end": 18.0, "score": 8, "description": "rides the wave"})
    base.update(over)
    return base


def q1_eligibility() -> None:
    from pipeline.output_qualification import INVALID, UNCERTAIN, VALID, classify_action
    check(classify_action(ev(), "surfing")["verdict"] == VALID, "Q1: a fully evidenced ride must be VALID")
    v = classify_action(ev(score=9, description="tries to stand up but falls immediately, failed takeoff"), "surfing")
    check(v["verdict"] == INVALID, f"Q1: an explicit failed takeoff must be INVALID whatever the score: {v}")
    for label, over, code in (
        ("no tracker", {"perception_evidence_status": "no_tracker_detection"}, "target_actor_not_tracked"),
        ("activity unmeasured", {"athlete_activity_state": None}, "cv_activity_unmeasured"),
        ("low score", {"score": 5}, "analyzer_rating_below_threshold"),
    ):
        v = classify_action(ev(**over), "surfing")
        check(v["verdict"] == UNCERTAIN and code in v["missing"], f"Q1: {label} must be UNCERTAIN ({code}): {v}")
    v = classify_action(ev(athlete_activity_state="waiting"), "surfing")
    check(v["verdict"] == UNCERTAIN and "cv_target_track_waiting" in v["negative"],
          f"Q1: a CV contradiction must withhold the shot: {v}")
    v = classify_action(ev(athlete_activity_state="waiting", equipment_association_ratio=0.5), "surfing")
    check(v["verdict"] == VALID, f"Q1: a board-associated target counts as active evidence: {v}")
    short = ev(start=10.0, end=12.5)
    short["window_refinement"] = {**short["window_refinement"], "first_track_sec": 10.0, "last_track_sec": 12.5}
    check(classify_action(short, "surfing")["verdict"] == VALID, "Q1: a valid short ride must not be dropped for length")


def q2_intervals() -> None:
    from pipeline.output_qualification import action_interval

    def interval(**over):
        e = ev()
        refinement = dict(e["window_refinement"])
        refinement.update(over.pop("refinement", {}))
        e["window_refinement"] = refinement
        e.update(over)
        return action_interval(e)

    check(interval()["issues"] == [], "Q2: a shot inside the verified actor span has no issue")
    check("tail_beyond_verified_actor" in interval(final_cut_end=21.0)["issues"], "Q2: invented tail passed")
    check(interval(final_cut_end=18.8)["issues"] == [], "Q2: the permitted end pad must not block")
    i = interval(final_cut_end=20.5, refinement={"track_lost_in_fall_kept": True})
    check(not i["issues"] and "tail_is_measured_fall" in i["notes"], f"Q2: a measured fall tail must be kept: {i}")
    i = interval(final_cut_end=21.0, recording_end_tail_sec=1.2)
    check("tail_after_actor_lost_to_recording_end" in i["issues"] and "source_limited_recording_end" in i["notes"],
          f"Q2: a recording-end tail without the actor must block and be marked source-limited: {i}")
    check("lead_before_verified_actor" in interval(final_cut_start=7.0)["issues"], "Q2: unsupported lead passed")
    check(interval(final_cut_start=8.0, refinement={"setup_first_track_sec": 8.0})["issues"] == [],
          "Q2: a lead onto the tracked setup must pass")
    i = interval(refinement={"max_track_gap_sec": 9.0, "max_track_gap_start_sec": 12.0})
    check("track_gap_identity_continuity_unproven" in i["issues"], f"Q2: a 9 s gap inside the shot passed: {i}")
    i = interval(refinement={"max_track_gap_sec": 9.0, "max_track_gap_start_sec": 30.0})
    check("track_gap_identity_continuity_unproven" not in i["issues"], "Q2: a gap outside the shot must not block")
    e = ev()
    e.pop("window_refinement")
    check("actor_span_unvalidated" in action_interval(e)["issues"], "Q2: an unvalidated actor span passed")


def q3_identity() -> None:
    from pipeline.output_qualification import identity_verdict
    a = ev()
    b = ev(event_source_ref="sha256:" + "b" * 64, event_uid="ev2_b", target_track_id="3")
    check(identity_verdict([a, ev(start=30.0, end=36.0, event_uid="ev2_a2")])["verdict"] == "MATCH",
          "Q3: one actor in one source needs no cross-source proof")
    passed = {"decision": "pass", "evidence_digest": "d" * 64}
    check(identity_verdict([{**a, "identity_gate": passed}, {**b, "identity_gate": passed}])["verdict"] == "MATCH",
          "Q3: a gated multi-source reel with image evidence must match")
    for label, events in (
        ("unconfirmed", [{**a, "identity_gate": {"decision": "kept_together_unconfirmed"}},
                         {**b, "identity_gate": {"decision": "kept_together_unconfirmed"}}]),
        ("pass without evidence", [{**a, "identity_gate": {"decision": "pass"}}, {**b, "identity_gate": {"decision": "pass"}}]),
        ("ungated multi-source", [a, b]),
        ("two actors one source", [a, ev(target_track_id="9", event_uid="ev2_other")]),
    ):
        v = identity_verdict(events)
        check(v["verdict"] != "MATCH" and v["has_unconfirmed_edges"], f"Q3: {label} must not match: {v}")


def q4_lineage() -> None:
    from pipeline.output_qualification import build_inputs
    check(not build_inputs([ev()], "surfing")["issues"], "Q4: a complete shot must have no issue")
    for label, over in (("no uid", {"event_uid": None}), ("name-only source", {"event_source_ref": "name:x.mp4"})):
        issues = build_inputs([ev(**over)], "surfing")["issues"]
        check(any("lineage_incomplete" in i for i in issues), f"Q4: {label} passed: {issues}")


def q5_proof() -> None:
    from pipeline.output_qualification import build_inputs, finalize, verify
    from pipeline.publishable_reel_policy import _refresh_row_publishability

    def part(**over):
        p = {"render_ready": True, "uploaded_to_review": True, "upload_error": None, "review_draft_name": "d.mp4",
             "qa_evidence_recorded": True, "qa_verdict": "PASS", "qa_passed": True, "technical_issues": [],
             "content_sha256": "1" * 64, "content_sha256_kind": "bytes",
             "qualification_inputs": build_inputs([ev()], "surfing")}
        p.update(over)
        return p

    row = {"parts": [part()]}
    _refresh_row_publishability(row)
    obj = row["parts"][0]["output_qualification"]
    check(row["parts"][0]["publishable"] is True and verify(obj), f"Q5: a qualified part must publish: {obj}")
    tampered = copy.deepcopy(obj)
    tampered["events"][0]["eligibility"]["verdict"] = "UNCERTAIN"
    check(not verify(tampered), "Q5: a tampered qualification passed verification")
    forged = copy.deepcopy(obj)
    forged["publishable"] = True
    forged["blocking"] = ["x"]
    check(not verify(forged), "Q5: a forged publishable flag passed verification")
    for label, over in (
        ("missing inputs", {"qualification_inputs": None}),
        ("uncertain shot", {"qualification_inputs": build_inputs([ev(athlete_activity_state=None)], "surfing")}),
        ("specs digest", {"content_sha256_kind": "specs_digest"}),
        ("critical defect", {"qa_defects": [{"type": "IDENTITY_SWITCH", "severity": "critical"}]}),
    ):
        r = {"parts": [part(**over)]}
        _refresh_row_publishability(r)
        p = r["parts"][0]
        check(not verify(p["output_qualification"]), f"Q5: {label} passed proof verification")
        if True:
            check(p["publishable"] is False and p["output_qualification"]["publishable"] is False,
                  f"Q5: {label} published: {p['output_qualification']}")

    # through record_athlete_outcome: an unevidenced shot becomes a technical issue, the part is not render-ready
    with tempfile.TemporaryDirectory() as folder:
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(Path(folder) / "m.json")
        from pipeline import publishable_reel_policy as policy
        policy.reset_manifest()
        specs = {"duration": 8.0, "width": 2160, "height": 3840, "aspect": 0.5625, "has_audio": False, "fps": 30.0}
        for label, events in (("ok", [ev()]), ("uncertain", [ev(athlete_activity_state=None, event_uid="ev2_u")])):
            path = str(Path(folder) / f"{label}.mp4")
            Path(path).write_bytes(label.encode())
            policy.record_athlete_outcome(sport="surfing", athlete_label=label, final_reels=[path],
                                          events_by_reel={path: events}, flagged_paths=set(),
                                          specs_by_path={path: specs})
        rows = {r["athlete_label"]: r["parts"][0]
                for r in json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())["athletes"]}
        check(rows["ok"]["render_ready"] is True and rows["ok"]["content_sha256_kind"] == "bytes",
              f"Q5: a qualified shot was withheld: {rows['ok']['technical_issues']}")
        check(rows["uncertain"]["render_ready"] is False
              and any(i.startswith("qualification:action_uncertain") for i in rows["uncertain"]["technical_issues"]),
              f"Q5: an UNCERTAIN shot reached render-ready: {rows['uncertain']}")
        check(rows["ok"]["action_evidence"][0]["source_ref"].startswith("sha256:"),
              "Q5: manifest parts must carry per-shot action evidence")


def q6_gate_carries_evidence() -> None:
    from pipeline import identity_evidence
    from pipeline.real_identity_gate import enforce_identity_gate
    image = str(Path(__file__).resolve())
    apps = [{"path": "a.mp4", "_clip_index": "a.mp4", "_person_id": "p1", "events": [ev(person_id="p1")]},
            {"path": "b.mp4", "_clip_index": "b.mp4", "_person_id": "p2",
             "events": [ev(person_id="p2", target_track_id="3", track_id="3")]}]
    for app in apps:
        app["events"][0]["track_id"] = app["events"][0]["target_track_id"]
    import _consensus_fixture as fx
    cluster = fx.prove({"description": "x", "appearances": apps}, image=image)
    os.environ["SPORTREEL_ONE_REEL_PER_ATHLETE"] = "0"
    try:
        out = enforce_identity_gate([cluster])
    finally:
        os.environ.pop("SPORTREEL_ONE_REEL_PER_ATHLETE", None)
    gate = out[0]["appearances"][0]["events"][0]["identity_gate"]
    check(gate["decision"] == "pass" and gate["evidence_digest"] == cluster["_identity_evidence"]["evidence_digest"],
          f"Q6: the identity gate pass must carry its evidence digest: {gate}")


def main() -> int:
    q1_eligibility()
    q2_intervals()
    q3_identity()
    q4_lineage()
    q5_proof()
    q6_gate_carries_evidence()
    print("PASS: output qualification (action eligibility, actor intervals, identity, lineage, proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
