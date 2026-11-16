#!/usr/bin/env python3
"""Reprocess requests bound to one athlete and one output (repair-evidence columns, 2026-11-16).

 B1  A QA task records the uploaded draft's athlete actions (`target_athlete_key`) and content hash
     (`original_output_sha256`), read from the manifest; an unknown or ambiguous draft records nothing.
 B2  `done` needs the bound athlete - the single row overlapping an original action on the same source - to be
     publishable, free of the requested defect types, and a different output. A co-athlete on the same source no
     longer decides the request; an unchanged hash, a missing hash, no match or two matches never close it.
 B3  A request without a valid binding keeps the source-wide rule, and its verdict says so.
 B4  The closing update writes repair_attempt_id, repair_output_sha256 and repair_verdict under the same
     ownership filters; it is reported only if it returned the row.
 B5  The orchestrator carries a claimed request's binding to the verdict.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))

SRC = "2026-10-03T12-19-53_DJI_20260720160337_0094_D.MP4"


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def row(key: str, actions, *, publishable=True, sha="new", defects=(), draft=None) -> dict:
    part = {"publishable": publishable, "content_sha256": sha, "local_path": f"/tmp/{key}.mp4",
            "qa_defects": [{"type": d} for d in defects], "review_draft_name": draft}
    return {"athlete_key": key, "primary_publishable_reel": f"/tmp/{key}.mp4" if publishable else None,
            "parts": [part], "action_lineage": [f"/tmp/run/{s}|{a:.3f}|{b:.3f}|wave_catch" for s, a, b in actions]}


def binding_tests() -> dict:
    from pipeline.reprocess_binding import build_binding, parse_binding

    original = {"athletes": [row("athlete_A", [(SRC, 10.0, 18.0), ("0118.MP4", 3.0, 9.0)], publishable=False,
                                 sha="orig", draft="DRAFT_A.mp4"),
                             row("athlete_B", [(SRC, 40.0, 48.0)], draft="DRAFT_B.mp4")]}
    bound = build_binding(original, "DRAFT_A.mp4")
    check(bound.get("original_output_sha256") == "orig", f"B1: original output hash not recorded: {bound}")
    parsed = parse_binding(bound.get("target_athlete_key"))
    check(parsed is not None and parsed["run_athlete_key"] == "athlete_A"
          and [SRC, 10.0, 18.0] in parsed["actions"] and ["0118.MP4", 3.0, 9.0] in parsed["actions"],
          f"B1: athlete actions not recorded: {bound}")
    check(build_binding(original, "DRAFT_unknown.mp4") == {}, "B1: an unknown draft got a binding")
    twice = {"athletes": original["athletes"] + [row("athlete_C", [(SRC, 1.0, 2.0)], draft="DRAFT_A.mp4")]}
    check(build_binding(twice, "DRAFT_A.mp4") == {}, "B1: an ambiguous draft got a binding")
    for bad in (None, "", "athlete_A", "{}", '{"v":2,"actions":[["a",1,2]]}', '{"v":1,"actions":[["a",2,1]]}'):
        check(parse_binding(bad) is None, f"B1: invalid binding {bad!r} was accepted")

    # B1: the QA gate's helper reads the binding from this run's manifest file
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        manifest_file = Path(folder) / "manifest.json"
        from pipeline.publishable_reel_policy import MANIFEST_SCHEMA_VERSION
        manifest_file.write_text(json.dumps({"schema_version": MANIFEST_SCHEMA_VERSION, **original}))
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest_file)
        try:
            from pipeline.qa_gate_policy import _reedit_binding
            check(_reedit_binding("DRAFT_A.mp4") == bound, "B1: the QA gate did not read the binding from the manifest")
            check(_reedit_binding("DRAFT_unknown.mp4") == {}, "B1: the QA gate invented a binding")
        finally:
            os.environ.pop("PUBLISHABLE_REEL_MANIFEST_FILE", None)

    # B1: the QA gate writes the binding into the task row
    from integrations import supabase_uploader as up
    inserted: list[dict] = []
    fake = types.SimpleNamespace(table=lambda _n: types.SimpleNamespace(
        insert=lambda payload: types.SimpleNamespace(execute=lambda: inserted.append(payload))))
    up._supabase, saved = (lambda: fake), up._active_reedit_task
    up._active_reedit_task = lambda _name: None
    try:
        gate = {"qa_review_required": True, "defects": [{"type": "PREMATURE_CUT"}]}
        up.upsert_qa_reedit_task("DRAFT_A.mp4", gate, binding=bound)
        up.upsert_qa_reedit_task("DRAFT_X.mp4", gate, binding={})
    finally:
        up._active_reedit_task = saved
    check(inserted[0].get("target_athlete_key") == bound["target_athlete_key"]
          and inserted[0].get("original_output_sha256") == "orig", f"B1: task row lacks the binding: {inserted[0]}")
    check("target_athlete_key" not in inserted[1] and "original_output_sha256" not in inserted[1],
          "B1: a task without a binding must not write empty binding columns")
    return bound


def judge_tests(bound: dict) -> None:
    from pipeline.reprocess_binding import BASIS_BOUND, BASIS_LEGACY, judge

    req = {"id": "r", "sources": [SRC, "0118.MP4"], "defect_types": ["PREMATURE_CUT"], **bound}

    def verdict(*rows, request=req):
        return judge(request, {"athletes": list(rows)})

    co_blocked = row("athlete_B2", [(SRC, 40.0, 48.0)], publishable=False, defects=["PRIMARY_ACTOR_UNCLEAR"])
    fixed = row("athlete_A2", [(SRC, 9.5, 19.0)], sha="new")
    v = verdict(fixed, co_blocked)
    check(v["verified"] is True and v["basis"] == BASIS_BOUND and v["repair_output_sha256"] == "new"
          and v["repair_athlete_key"] == "athlete_A2",
          f"B2: the repaired athlete must close the request although a co-athlete is blocked: {v}")
    cases = (
        ((row("a", [(SRC, 9.5, 19.0)], publishable=False), co_blocked), "not_publishable"),
        ((row("a", [(SRC, 9.5, 19.0)], defects=["PREMATURE_CUT"]),), "remaining_defects"),
        ((row("a", [(SRC, 9.5, 19.0)], sha="orig"),), "output_unchanged"),
        ((row("a", [(SRC, 9.5, 19.0)], sha=""),), "repair_output_hash_unknown"),
        ((row("a", [(SRC, 60.0, 70.0)]),), "target_athlete_not_found"),
        ((row("a", [("0999.MP4", 9.5, 19.0)]),), "target_athlete_not_found"),
        ((row("a", [(SRC, 17.0, 30.0)]),), "target_athlete_not_found"),  # 1 s of an 8 s window: not the same action
        ((row("a", [(SRC, 9.5, 19.0)]), row("b", [("0118.MP4", 2.0, 8.0)])), "target_athlete_ambiguous"),
    )
    for rows, reason in cases:
        v = verdict(*rows)
        check(v["verified"] is False and v["reason"] == reason, f"B2: expected {reason}, got {v}")
    v = verdict(fixed, request={**req, "original_output_sha256": None})
    check(v["verified"] is False and v["reason"] == "original_output_hash_unknown",
          f"B2: without the original hash a change of output is not shown: {v}")

    legacy = {"id": "r", "sources": [SRC], "defect_types": ["PREMATURE_CUT"], "target_athlete_key": "athlete_A"}
    v = judge(legacy, {"athletes": [fixed, co_blocked]})
    check(v["basis"] == BASIS_LEGACY and v["verified"] is False and v["reason"] == "not_publishable",
          f"B3: an unbound request must keep the source-wide rule: {v}")
    v = judge(legacy, {"athletes": [fixed]})
    check(v["basis"] == BASIS_LEGACY and v["verified"] is True, f"B3: source-wide rule, all publishable: {v}")


def close_tests() -> None:
    from integrations import supabase_uploader as up

    table = {"r1": {"status": "queued", "last_pipeline_run_id": "run-A"},
             "r2": {"status": "queued", "last_pipeline_run_id": "run-A"},
             "r3": {"status": "queued", "last_pipeline_run_id": "other"}}
    calls: list[tuple[dict, list]] = []

    class Q:
        def __init__(self, payload): self.payload, self.filters = payload, []
        def eq(self, k, v): self.filters.append((k, v)); return self
        def execute(self):
            calls.append((self.payload, self.filters))
            rid = dict(self.filters)["id"]
            r = table.get(rid)
            if r is None or any(r.get(k) != v for k, v in self.filters if k != "id"):
                return types.SimpleNamespace(data=[])
            r.update(self.payload)
            return types.SimpleNamespace(data=[dict(r, id=rid)])

    up._supabase = lambda: types.SimpleNamespace(table=lambda _n: types.SimpleNamespace(update=lambda p: Q(p)))
    ok = {"verified": True, "basis": "athlete_and_output_bound", "reason": "", "repair_output_sha256": "new"}
    bad = {"verified": False, "basis": "athlete_and_output_bound", "reason": "output_unchanged",
           "repair_output_sha256": "orig"}
    written = up.close_reprocess_requests({"r1": ok, "r2": bad, "r3": ok}, "run-A")
    check(written == {"r1": "done", "r2": "reprocessed_unverified", "r3": "close_not_applied"},
          f"B4: unexpected closure report {written}")
    check(table["r1"]["repair_attempt_id"] == "run-A" and table["r1"]["repair_output_sha256"] == "new"
          and table["r1"]["repair_verdict"] == ok, f"B4: repair evidence not written: {table['r1']}")
    check(table["r2"]["repair_verdict"]["reason"] == "output_unchanged", "B4: a failed verdict must be recorded too")
    check("repair_verdict" not in table["r3"], "B4: another run's request was written")
    for payload, filters in calls:
        check(("status", "queued") in filters and ("last_pipeline_run_id", "run-A") in filters,
              f"B4: evidence written without the ownership filters: {filters}")
    calls.clear()
    table["r4"] = {"status": "queued", "last_pipeline_run_id": "run-A"}
    check(up.close_reprocess_requests({"r4": True}, "run-A") == {"r4": "done"}
          and "repair_verdict" not in calls[0][0], "B4: a bare bool keeps the plain closure")


def orchestrator_tests(bound: dict) -> None:
    from integrations import supabase_uploader as up
    from pipeline import orchestrator

    request = {"id": "req-1", "draft_name": "DRAFT_A.mp4", "notes": "", "qa_defects": [{"type": "PREMATURE_CUT"}],
               **bound}
    saved = (up.fetch_pending_reprocess, up.claim_reprocess, up.lookup_draft_sources, up.mark_reprocess)
    up.fetch_pending_reprocess = lambda: [request]
    up.claim_reprocess = lambda req_id, run_id=None: True
    up.lookup_draft_sources = lambda name: [{"id": f"raw/{SRC}", "name": SRC}]
    up.mark_reprocess = lambda *a, **k: None
    drive = types.ModuleType("integrations.drive")
    drive.requeue_video = lambda _id: True
    sys.modules["integrations.drive"] = drive
    orchestrator._QUEUED_REPROCESS.clear()
    try:
        orchestrator._handle_reprocess_requests()
        queued = list(orchestrator._QUEUED_REPROCESS)
    finally:
        up.fetch_pending_reprocess, up.claim_reprocess, up.lookup_draft_sources, up.mark_reprocess = saved
        orchestrator._QUEUED_REPROCESS.clear()
    check(len(queued) == 1 and queued[0]["target_athlete_key"] == bound["target_athlete_key"]
          and queued[0]["original_output_sha256"] == "orig", f"B5: binding lost between claim and verdict: {queued}")
    manifest = {"athletes": [row("athlete_A2", [(SRC, 9.5, 19.0)], sha="new"),
                             row("athlete_B2", [(SRC, 40.0, 48.0)], publishable=False)]}
    verdicts = orchestrator.reprocess_verdicts(queued, manifest)
    check(verdicts["req-1"]["verified"] is True and verdicts["req-1"]["basis"] == "athlete_and_output_bound",
          f"B5: the orchestrator verdict ignored the binding: {verdicts}")
    check(orchestrator.reprocess_outcomes(queued, manifest) == {"req-1": True}, "B5: outcomes disagree with verdicts")
    json.dumps(verdicts)  # the verdict is written to a jsonb column


def main() -> int:
    bound = binding_tests()
    judge_tests(bound)
    close_tests()
    orchestrator_tests(bound)
    print("PASS: reprocess requests bound to one athlete and one output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
