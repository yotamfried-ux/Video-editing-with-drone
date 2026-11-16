#!/usr/bin/env python3
"""Release-safety invariants (production safety qualification, 2026-11-16).

Identity
 I1  The same tracker number in two sources is not identity evidence, in either one-reel mode.
 I2  A cluster passes as visually verified only with image evidence covering exactly its current members:
     a bare `_visual_verified` flag, evidence for a subset, or evidence that predates a membership change fails.
 I3  Two different athletes that share a tracker number never merge on that number; a verified athlete with
     the same or different tracker numbers passes through its image evidence.
 I4  Several people in one source never form one cluster; a missing source or missing tracks never passes.
 I5  A chain A~B, B~C with a hard conflict between A and C is split, whatever the cluster order.
Event lineage
 E1  Two distinct late events with identical window, type and track get different ids.
 E2  A reel with an event lacking a canonical id, or two shots claiming one id, is not publishable; the
     manifest lists the event ids of every part.
 E3  The draft metadata serializer keeps the event id and the identity gate.
Reprocess lifecycle
 R1  A request is claimed atomically: a second worker cannot claim it.
 R2  A request closes only under the run that claimed it; a failed write closes nothing else.
 R3  `done` needs every reel from its sources publishable and none still carrying the request's defect type;
     an unrelated publishable reel or a repaired co-athlete does not close it.
"""
from __future__ import annotations

import itertools
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))


def app(source: str, person: str, track: str | None, description: str = "surfer in a black wetsuit on a white board") -> dict:
    event = {"person_id": person, "type": "wave_catch", "start": 1.0, "end": 8.0, "event_uid": f"ev2_{source}_{person}"}
    if track is not None:
        event["track_id"] = track
    return {"path": source, "_clip_index": source, "_person_id": person, "description": description,
            "_description": description, "events": [event]}


def gate(clusters, one_reel: bool):
    from pipeline.real_identity_gate import enforce_identity_gate
    os.environ["SPORTREEL_ONE_REEL_PER_ATHLETE"] = "1" if one_reel else "0"
    try:
        return enforce_identity_gate(clusters)
    finally:
        os.environ.pop("SPORTREEL_ONE_REEL_PER_ATHLETE", None)


def passed(out) -> bool:
    return len(out) == 1 and out[0].get("_identity_gate") == "pass"


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def identity() -> None:
    from pipeline import identity_evidence as ev

    # I1 / I3: same tracker number, different (unverified) athletes
    for one_reel in (True, False):
        out = gate([{"description": "x", "appearances": [app("a.mp4", "person_A", "7"), app("b.mp4", "person_A", "7")]}], one_reel)
        check(not any(c.get("_identity_gate") == "pass" for c in out), f"I1 one_reel={one_reel}: shared tracker number passed")

    # I2: bare flag without evidence
    bare = {"description": "x", "_visual_verified": True, "appearances": [app("a.mp4", "person_A", "7"), app("b.mp4", "person_B", "3")]}
    check(not passed(gate([bare], False)), "I2: a bare _visual_verified flag passed the gate")

    # I3: verified athlete, same and different tracker numbers -> passes through evidence
    for tracks in (("7", "7"), ("7", "3")):
        c = {"description": "x", "appearances": [app("a.mp4", "person_A", tracks[0]), app("b.mp4", "person_B", tracks[1])]}
        ev.stamp(c, ev.IMAGE_VERIFIER)
        out = gate([c], False)
        check(passed(out) and out[0].get("_identity_gate_reason") == "visual_verified_per_source_tracks",
              f"I3: a verified athlete with tracks {tracks} must pass on its image evidence")

    # I2: evidence for a subset / stale after a member is added
    c = {"description": "x", "appearances": [app("a.mp4", "person_A", "7"), app("b.mp4", "person_B", "3")]}
    ev.stamp(c, ev.IMAGE_VERIFIER)
    c["appearances"].append(app("c.mp4", "person_C", "5"))
    check(not ev.covers(c) and not passed(gate([c], False)), "I2: evidence that predates an added member still passed")
    c = {"description": "x", "appearances": [app("a.mp4", "person_A", "7")]}
    ev.stamp(c, ev.IMAGE_VERIFIER)
    c["appearances"].append(app("b.mp4", "person_B", "3"))
    check(not passed(gate([c], False)), "I2: single-member evidence promoted to a two-member cluster")

    # Evidence survives the identity module's field stripping (production hand-off to the editor)
    from pipeline.stages.identity import _strip_internal_fields
    c = {"description": "x", "appearances": [app("a.mp4", "person_A", "7"), app("b.mp4", "person_B", "3")]}
    ev.stamp(c, ev.IMAGE_VERIFIER)
    stripped = _strip_internal_fields([c])[0]
    check(ev.covers(stripped) and passed(gate([stripped], False)), "evidence must survive _strip_internal_fields")

    # I4: several people in one source; missing source; missing tracks
    from pipeline.stages.identity import _split_impossible_clusters
    same_clip = {"description": "x", "appearances": [app("a.mp4", "person_A", "7"), app("a.mp4", "person_B", "3")]}
    check(len(_split_impossible_clusters([same_clip])) == 2, "I4: two people of one source formed one cluster")
    no_source = {"description": "x", "appearances": [app("", "person_A", "7"), app("", "person_B", "7")]}
    check(not passed(gate([no_source], False)), "I4: appearances without a source passed")
    no_tracks = {"description": "x", "appearances": [app("a.mp4", "person_A", None), app("b.mp4", "person_B", None)]}
    check(not passed(gate([no_tracks], False)), "I4: appearances without tracks passed")

    # I5: chain conflict, every order
    a = app("a.mp4", "person_A", "1", "surfer in a black long-sleeve wetsuit on a white board")
    b = app("b.mp4", "person_B", "2", "surfer in a black top on a white board")
    c3 = app("c.mp4", "person_C", "3", "shirtless surfer in black shorts on a white board")
    for order in itertools.permutations([a, b, c3]):
        out = _split_impossible_clusters([{"description": "x", "appearances": list(order)}])
        check(len(out) == 3, f"I5: chain with an A/C conflict was not split for order {[x['path'] for x in order]}")


def lineage() -> None:
    from pipeline import event_identity as ei

    ei.reset_for_tests()
    with tempfile.TemporaryDirectory() as folder:
        video = Path(folder) / "DJI_0094_D.MP4"
        video.write_bytes(b"source")
        one = {"type": "wave_catch", "start": 27.0, "end": 35.5, "target_track_id": "154"}
        two = dict(one)
        u1 = ei.ensure_event_uid(one, str(video), "rescued_track_154", origin=ei.RESCUE)
        u2 = ei.ensure_event_uid(two, str(video), "rescued_track_154", origin=ei.RESCUE)
        check(u1 != u2, "E1: two late events with identical keys shared an id")
        check(ei.ensure_event_uid(dict(one), str(video)) == u1, "a copy of an event keeps its id")
    check(ei.lineage_issues([{"event_uid": "a"}, {"event_uid": "b"}]) == [], "E2: clean lineage flagged")
    check(ei.lineage_issues([{"event_uid": "a"}, {"start": 1}]) == ["missing_event_provenance"], "E2: missing id not flagged")
    check(ei.lineage_issues([{"event_uid": "a"}, {"event_uid": "a"}]) == ["duplicate_event_uid"], "E2: duplicate id not flagged")
    check(ei.lineage_issues([{"event_uid": "a"}, {"start": 1, "_teaser": True}]) == [], "teasers are not published shots")

    with tempfile.TemporaryDirectory() as folder:
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(Path(folder) / "m.json")
        from pipeline import publishable_reel_policy as policy
        policy.reset_manifest()
        specs = {"duration": 8.0, "width": 2160, "height": 3840, "aspect": 0.5625, "has_audio": False, "fps": 30.0}
        for label, events in (("clean", [{"event_uid": "ev2_x", "start": 1, "end": 8, "type": "ride"}]),
                              ("orphan", [{"start": 1, "end": 8, "type": "ride"}]),
                              ("dup", [{"event_uid": "ev2_y", "start": 1, "end": 4, "type": "ride"},
                                       {"event_uid": "ev2_y", "start": 4, "end": 8, "type": "ride"}])):
            path = str(Path(folder) / f"{label}.mp4")
            Path(path).write_bytes(label.encode())
            policy.record_athlete_outcome(sport="surfing", athlete_label=label, final_reels=[path],
                                          events_by_reel={path: events}, flagged_paths=set(), specs_by_path={path: specs})
        rows = {r["athlete_label"]: r["parts"][0] for r in json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())["athletes"]}
        check(rows["clean"]["event_uids"] == ["ev2_x"], "E2: manifest part must list its event ids")
        check("missing_event_provenance" in rows["orphan"]["technical_issues"] and not rows["orphan"]["render_ready"],
              "E2: a reel with an orphan shot must not be render-ready")
        check("duplicate_event_uid" in rows["dup"]["technical_issues"] and not rows["dup"]["render_ready"],
              "E2: a reel claiming one event twice must not be render-ready")

    from pipeline.draft_identity_metadata import serialize_event
    out = serialize_event({"event_uid": "ev2_z", "event_id": "ev2_z", "identity_gate": {"decision": "kept_together_unconfirmed"}})
    check(out.get("event_uid") == "ev2_z" and out.get("identity_gate"), "E3: serializer dropped the event id or identity gate")


def reprocess() -> None:
    from integrations import supabase_uploader as up
    from pipeline import orchestrator

    table: dict[str, dict] = {"r1": {"status": "pending"}, "r2": {"status": "queued", "last_pipeline_run_id": "other-run"}}
    fail_ids: set[str] = set()

    class Q:
        def __init__(self, payload): self.payload, self.filters = payload, []
        def eq(self, k, v): self.filters.append((k, v)); return self
        def execute(self):
            rid = dict(self.filters).get("id")
            if rid in fail_ids:
                raise RuntimeError("db down")
            row = table.get(rid)
            if row is None or any(row.get(k) != v for k, v in self.filters if k != "id"):
                return types.SimpleNamespace(data=[])
            row.update(self.payload)
            return types.SimpleNamespace(data=[row])

    fake = types.SimpleNamespace(table=lambda _n: types.SimpleNamespace(update=lambda p: Q(p)))
    up._supabase = lambda: fake

    check(up.claim_reprocess("r1", "run-A") is True, "R1: first claim must succeed")
    check(up.claim_reprocess("r1", "run-B") is False, "R1: a second worker claimed the same request")
    up.close_reprocess_requests({"r2": True}, "run-A")
    check(table["r2"]["status"] == "queued", "R2: a run closed a request claimed by another run")
    table["r3"] = {"status": "queued", "last_pipeline_run_id": "run-A"}
    fail_ids.add("r1")
    written = up.close_reprocess_requests({"r1": True, "r3": False}, "run-A")
    check(written["r1"] == "close_failed" and table["r3"]["status"] == "reprocessed_unverified",
          "R2: a failed write must not stop or corrupt the other closures")
    up.close_reprocess_requests({"r3": True}, "run-A")
    check(table["r3"]["status"] == "reprocessed_unverified", "a terminal request is not reopened or re-closed")

    def row(source, publishable, defects=()):
        return {"primary_publishable_reel": "D.mp4" if publishable else None,
                "parts": [{"publishable": publishable, "qa_defects": [{"type": d} for d in defects]}],
                "action_lineage": [f"/tmp/{source}|1.000|9.000|wave_catch"]}

    manifest = {"athletes": [row("S1.MP4", True), row("S2.MP4", True), row("S2.MP4", False, ["PRIMARY_ACTOR_UNCLEAR"]),
                             row("S3.MP4", True, ["RECORDING_ENDS_MID_ACTION"]), row("S4.MP4", True)]}
    queued = [
        {"id": "fixed", "sources": ["S1.MP4"], "defect_types": ["PREMATURE_CUT"]},
        {"id": "co-athlete-still-blocked", "sources": ["S2.MP4"], "defect_types": ["PRIMARY_ACTOR_UNCLEAR"]},
        {"id": "defect-persists", "sources": ["S3.MP4"], "defect_types": ["RECORDING_ENDS_MID_ACTION"]},
        {"id": "no-output", "sources": ["S9.MP4"], "defect_types": ["PREMATURE_CUT"]},
        {"id": "shared-source", "sources": ["S4.MP4"], "defect_types": ["PREMATURE_CUT"]},
        {"id": "shared-source-2", "sources": ["S4.MP4"], "defect_types": ["CUT_TOO_EARLY"]},
    ]
    got = orchestrator.reprocess_outcomes(queued, manifest)
    check(got == {"fixed": True, "co-athlete-still-blocked": False, "defect-persists": False, "no-output": False,
                  "shared-source": True, "shared-source-2": True}, f"R3: unexpected outcomes {got}")
    check(orchestrator._request_defect_types({"approval_blocked_reasons": ["PREMATURE_CUT: ride cut early"]}) == ["PREMATURE_CUT"],
          "R3: defect types are read from the request")


def main() -> int:
    identity()
    lineage()
    reprocess()
    print("PASS: release-safety invariants (identity evidence, event lineage, reprocess lifecycle)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
