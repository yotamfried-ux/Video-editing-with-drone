#!/usr/bin/env python3
"""Reprocess requests bound to one athlete, one output part and its defects (PR #390 review, 2026-11-16).

 B1  A QA task records a v2 binding (event ids, source content refs, windows, tracks, output byte hash,
     defect types, run) read from the manifest; an unknown draft, a specs-digest hash or incomplete action
     evidence records an explicit `binding_missing` marker - never an empty key.
 B2  Binding modes: only `athlete_and_output_bound` can close as `done`. Missing, invalid (incl. v1), stale
     (other draft / other output revision) and legacy rows are never `done`; legacy goes to manual
     reconciliation even when every source-wide output passed.
 B3  Identity-safe matching (10 cases): simultaneous athletes, overlapping separate actions, short-inside-long,
     several actions of one athlete, same name / different content, multiple sources, tracker id change,
     missing actor evidence, ambiguity, legitimate boundary correction.
 B4  Exact repaired output: the linked part, real byte hash that changed, final QA PASS recorded, no requested
     defect, publishable; another part's hash or a specs digest never proves a repair.
 B5  Task refresh: a refresh without a new binding overwrites the old one with a marker (no stale reuse);
     updates are compare-and-swap on qa_blocked; a concurrent insert is refreshed, not duplicated.
 B6  Closure writes repair_attempt_id / repair_output_sha256 / repair_verdict under ownership filters.
 B7  Crash recovery: a request left `queued` by a finished, crashed or silent run returns to `pending`
     (counted) or `failed_max_attempts`; a live run's and this run's requests are untouched.
 B8  The orchestrator carries the binding from claim to verdict.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))

SHA_A = "sha256:" + "a" * 64
SHA_A2 = "sha256:" + "c" * 64  # same file name, different content
SHA_B = "sha256:" + "b" * 64
OUT_ORIG = "1" * 64
OUT_NEW = "2" * 64


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def act(start, end, *, ref=SHA_A, src="DJI_0094_D.MP4", track=None, uid=None, typ="wave_catch") -> dict:
    return {"event_uid": uid, "source": src, "source_ref": ref, "start": start, "end": end, "type": typ, "track": track}


def part(actions, *, sha=OUT_NEW, kind="bytes", publishable=True, qa="PASS", defects=(), draft=None, index=1) -> dict:
    return {"part_index": index, "content_sha256": sha, "content_sha256_kind": kind, "action_evidence": actions,
            "publishable": publishable, "qa_verdict": qa, "qa_evidence_recorded": qa is not None,
            "qa_defects": [{"type": d} for d in defects], "technical_issues": [], "review_draft_name": draft,
            "local_path": f"/tmp/{draft or index}.mp4"}


def row(key, *parts) -> dict:
    return {"athlete_key": key, "parts": list(parts),
            "primary_publishable_reel": "x" if any(p["publishable"] for p in parts) else None}


def manifest(*rows) -> dict:
    return {"athletes": list(rows)}


def binding_for(actions, *, sha=OUT_ORIG, draft="DRAFT_A.mp4") -> dict:
    from pipeline.reprocess_binding import build_binding
    m = manifest(row("athlete_A", part(actions, sha=sha, publishable=False, draft=draft)))
    b = build_binding(m, draft, defect_types=["PREMATURE_CUT"], run_id="run-orig")
    check(b.get("original_output_sha256") == sha, f"B1: binding not built: {b}")
    return b


def request(b, *, draft="DRAFT_A.mp4", defects=("PREMATURE_CUT",)) -> dict:
    return {"id": "r", "draft_name": draft, "sources": ["DJI_0094_D.MP4"], "defect_types": list(defects), **b}


def judge(req, m):
    from pipeline.reprocess_binding import judge as j
    return j(req, m)


def binding_tests() -> None:
    from pipeline.reprocess_binding import build_binding, classify_binding, MODE_BOUND, MODE_MISSING

    b = binding_for([act(10, 18, track="7", uid="ev2_x")])
    data = json.loads(b["target_athlete_key"])
    check(data["v"] == 2 and data["mode"] == MODE_BOUND and data["run_id"] == "run-orig"
          and data["defect_types"] == ["PREMATURE_CUT"] and data["source_refs"] == [SHA_A]
          and data["actions"][0]["track"] == "7" and data["actions"][0]["event_uid"] == "ev2_x",
          f"B1: v2 binding incomplete: {data}")
    for label, m, draft in (
        ("unknown draft", manifest(), "DRAFT_A.mp4"),
        ("specs digest", manifest(row("a", part([act(1, 2)], kind="specs_digest", draft="D.mp4"))), "D.mp4"),
        ("no source sha", manifest(row("a", part([act(1, 2, ref="name:x.mp4")], draft="D.mp4"))), "D.mp4"),
        ("no actions", manifest(row("a", part([], draft="D.mp4"))), "D.mp4"),
    ):
        got = build_binding(m, draft)
        mode = classify_binding({"draft_name": draft, **got})[0]
        check(got["original_output_sha256"] is None and mode == MODE_MISSING,
              f"B1: {label} must give an explicit binding_missing marker, got {got}")

    # B1 through the QA gate's helper and the real manifest file
    from pipeline.publishable_reel_policy import MANIFEST_SCHEMA_VERSION
    with tempfile.TemporaryDirectory() as folder:
        f = Path(folder) / "m.json"
        f.write_text(json.dumps({"schema_version": MANIFEST_SCHEMA_VERSION,
                                 **manifest(row("athlete_A", part([act(10, 18)], sha=OUT_ORIG, draft="DRAFT_A.mp4")))}))
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(f)
        try:
            from pipeline.qa_gate_policy import _reedit_binding
            got = _reedit_binding("DRAFT_A.mp4", {"defects": [{"type": "PREMATURE_CUT"}]})
            check(got["original_output_sha256"] == OUT_ORIG
                  and json.loads(got["target_athlete_key"])["defect_types"] == ["PREMATURE_CUT"],
                  f"B1: QA gate helper did not bind from the manifest: {got}")
            check(classify_binding({"draft_name": "DRAFT_Z.mp4", **_reedit_binding("DRAFT_Z.mp4")})[0] == MODE_MISSING,
                  "B1: QA gate invented a binding")
        finally:
            os.environ.pop("PUBLISHABLE_REEL_MANIFEST_FILE", None)


def mode_tests() -> None:
    from pipeline.reprocess_binding import MODE_INVALID, MODE_LEGACY, MODE_MISSING, MODE_STALE, missing_marker

    b = binding_for([act(10, 18, track="7")])
    good = manifest(row("athlete_A2", part([act(9.5, 19, track="7")])))
    check(judge(request(b), good)["verified"] is True, "B2: a bound, repaired athlete must close as done")
    cases = (
        ("legacy", {"id": "r", "draft_name": "DRAFT_A.mp4", "defect_types": ["PREMATURE_CUT"]}, MODE_LEGACY),
        ("missing", {**request(b), **missing_marker("DRAFT_A.mp4", "x")}, MODE_MISSING),
        ("invalid text", {**request(b), "target_athlete_key": "athlete_A"}, MODE_INVALID),
        ("v1 binding", {**request(b), "target_athlete_key": json.dumps({"v": 1, "actions": [["a", 1, 2]]})}, MODE_INVALID),
        ("bad actions", {**request(b), "target_athlete_key": b["target_athlete_key"].replace(SHA_A, "name:x")}, MODE_INVALID),
        ("other draft", request(b, draft="DRAFT_B.mp4"), MODE_STALE),
        ("other revision", {**request(b), "original_output_sha256": "9" * 64}, MODE_STALE),
    )
    for label, req, mode in cases:
        v = judge(req, good)
        check(v["verified"] is False and v["binding_mode"] == mode,
              f"B2: {label} must be {mode} and never done, got {v}")
    v = judge(cases[0][1], good)
    check(v["reason"] == "legacy_manual_reconciliation_required",
          f"B2: a legacy request must go to manual reconciliation even when all outputs pass: {v}")


def identity_tests() -> None:
    def verdict(original, *rows):
        return judge(request(binding_for(original)), manifest(*rows))

    one = [act(10, 18, track="7")]
    # 1. two athletes simultaneously: tracks tell them apart; without tracks it is ambiguous
    v = verdict(one, row("A", part([act(10, 18, track="7")])), row("B", part([act(10, 18, track="9")])))
    check(v["verified"] and v["repair_athlete_key"] == "A", f"B3.1: simultaneous athletes with tracks: {v}")
    v = verdict([act(10, 18)], row("A", part([act(10, 18)])), row("B", part([act(10, 18)])))
    check(not v["verified"] and v["reason"] == "target_athlete_ambiguous", f"B3.1: no tracks must be ambiguous: {v}")
    # 2. two separate actions with strongly overlapping windows, different actors
    v = verdict(one, row("B", part([act(11, 19, track="9")])))
    check(not v["verified"] and v["reason"] == "identity_unverified", f"B3.2: other actor's overlapping action: {v}")
    # 3. a short action fully inside a longer action of another actor (no track evidence)
    v = verdict([act(10, 12)], row("long", part([act(5, 20)])))
    check(not v["verified"] and v["reason"] == "identity_unverified", f"B3.3: short-inside-long matched: {v}")
    v = verdict([act(10, 12)], row("short", part([act(10, 12.4)])), row("long", part([act(5, 20)])))
    check(not v["verified"] and v["reason"] == "target_athlete_ambiguous",
          f"B3.3: a containing action of another row must make it ambiguous: {v}")
    # 4. several actions of one athlete
    v = verdict([act(10, 18), act(40, 48)], row("A", part([act(10.5, 18.5), act(39, 47)])))
    check(v["verified"], f"B3.4: two supporting intervals must match: {v}")
    v = verdict([act(10, 18), act(40, 48)], row("A", part([act(10.5, 18.5)])))
    check(not v["verified"] and v["reason"] == "identity_unverified",
          f"B3.4: one of two actions without track evidence is not enough: {v}")
    # 5. same file name, different content
    v = verdict(one, row("A", part([act(10, 18, track="7", ref=SHA_A2)])))
    check(not v["verified"] and v["reason"] == "target_athlete_not_found", f"B3.5: name-only match: {v}")
    # 6. one athlete across several sources
    v = verdict([act(10, 18, track="7"), act(3, 9, ref=SHA_B, src="0118.MP4", track="2")],
                row("A", part([act(10, 18, track="7"), act(3, 9, ref=SHA_B, src="0118.MP4", track="2")])))
    check(v["verified"], f"B3.6: multi-source athlete: {v}")
    # 7. tracker id changed for the same window: a contradiction, not a match
    v = verdict(one, row("A", part([act(10, 18, track="12")])))
    check(not v["verified"], f"B3.7: changed track id must not silently match: {v}")
    # 8. missing actor evidence: a single near-identical window still matches when nothing competes
    v = verdict([act(10, 18)], row("A", part([act(10.2, 18.4)])))
    check(v["verified"], f"B3.8: single action, no competitor, no tracks: {v}")
    # 9. ambiguous identity: two qualifying rows
    v = verdict(one, row("A", part([act(10, 18, track="7")])), row("B", part([act(10, 18, track="7")])))
    check(not v["verified"] and v["reason"] == "target_athlete_ambiguous", f"B3.9: duplicate qualifiers: {v}")
    # 10. legitimate correction: start earlier, end later, same track
    v = verdict(one, row("A", part([act(8, 24, track="7")])))
    check(v["verified"], f"B3.10: boundary correction with same track must match: {v}")
    v = verdict([act(10, 18)], row("A", part([act(8, 30)])))
    check(not v["verified"], f"B3.10: a large change without track evidence must not match: {v}")


def output_tests() -> None:
    b = binding_for([act(10, 18, track="7")])
    req = request(b)
    linked = [act(10, 18, track="7")]
    other = [act(60, 70, track="7")]
    cases = (
        (row("A", part(linked, sha=OUT_ORIG)), "output_unchanged"),
        (row("A", part(linked, kind="specs_digest")), "repair_output_hash_not_bytes"),
        (row("A", part(linked, defects=["PREMATURE_CUT"])), "remaining_defects"),
        (row("A", part(linked, publishable=False)), "not_publishable"),
        (row("A", part(linked, qa="FAIL")), "final_qa_not_passed"),
    )
    for r, reason in cases:
        v = judge(req, manifest(r))
        check(not v["verified"] and v["reason"] == reason, f"B4: expected {reason}, got {v}")
    # the unchanged linked part is not hidden by a changed unrelated part
    v = judge(req, manifest(row("A", part(linked, sha=OUT_ORIG, index=1), part(other, sha=OUT_NEW, index=2))))
    check(not v["verified"] and v["reason"] == "output_unchanged" and v["repair_part_indexes"] == [1],
          f"B4: another part's hash proved the repair: {v}")
    v = judge(req, manifest(row("A", part(linked, sha=OUT_NEW, index=1), part(other, sha=OUT_ORIG, index=2))))
    check(v["verified"] and v["repair_part_indexes"] == [1] and v["repair_output_sha256"] == OUT_NEW,
          f"B4: the linked, changed part must prove the repair: {v}")


class FakeTable:
    def __init__(self, rows, runs=None, fail_ids=()):
        self.rows, self.runs, self.fail_ids, self.calls = rows, runs or {}, set(fail_ids), []

    def client(self):
        outer = self

        class Q:
            def __init__(self, table, op, payload=None):
                self.table, self.op, self.payload, self.filters = table, op, payload, []
            def select(self, *_a): return self
            def eq(self, k, v): self.filters.append((k, v)); return self
            def limit(self, *_a): return self
            def order(self, *_a, **_k): return self
            def execute(self):
                outer.calls.append((self.table, self.op, self.payload, list(self.filters)))
                store = outer.rows if self.table == "reprocess_requests" else outer.runs
                f = dict(self.filters)
                if f.get("id") in outer.fail_ids and self.op == "update":
                    raise RuntimeError("db down")
                if self.op == "insert":
                    if any(r.get("draft_name") == self.payload.get("draft_name")
                           and r.get("status") in {"qa_blocked", "pending", "queued"} for r in store.values()):
                        raise RuntimeError('duplicate key value violates unique constraint "23505"')
                    store[f"new{len(store)}"] = dict(self.payload)
                    return types.SimpleNamespace(data=[self.payload])
                hits = [(k, r) for k, r in store.items()
                        if all((k if key == "id" else r.get(key)) == val for key, val in self.filters)]
                if self.op == "select":
                    return types.SimpleNamespace(data=[dict(r, id=k) for k, r in hits])
                for _, r in hits:
                    r.update(self.payload)
                return types.SimpleNamespace(data=[dict(r, id=k) for k, r in hits])

        return types.SimpleNamespace(table=lambda name: types.SimpleNamespace(
            select=lambda *a: Q(name, "select"), update=lambda p: Q(name, "update", p),
            insert=lambda p: Q(name, "insert", p)))


def task_refresh_tests() -> None:
    from integrations import supabase_uploader as up
    from pipeline.reprocess_binding import classify_binding, MODE_MISSING

    b = binding_for([act(10, 18)])
    fake = FakeTable({"t1": {"draft_name": "DRAFT_A.mp4", "status": "qa_blocked", **b}})
    up._supabase = fake.client
    gate = {"qa_review_required": True, "defects": [{"type": "PREMATURE_CUT"}]}
    up.upsert_qa_reedit_task("DRAFT_A.mp4", gate, binding={})
    t = fake.rows["t1"]
    check(classify_binding({"draft_name": "DRAFT_A.mp4", **t})[0] == MODE_MISSING and t["original_output_sha256"] is None,
          f"B5: a refresh without a binding kept the old output's binding: {t}")
    updates = [c for c in fake.calls if c[1] == "update"]
    check(updates and ("status", "qa_blocked") in updates[-1][3], f"B5: refresh is not compare-and-swap: {updates}")
    # promoted meanwhile: the refresh must not overwrite it
    fake.rows["t1"]["status"] = "pending"
    before = dict(fake.rows["t1"])
    up.upsert_qa_reedit_task("DRAFT_A.mp4", gate, binding=b)
    check(fake.rows["t1"] == before, "B5: a promoted task was overwritten by a QA refresh")
    # concurrent insert: the unique index rejects the second writer, which refreshes instead
    fake2 = FakeTable({})
    up._supabase = fake2.client
    saved = up._active_reedit_task
    calls = {"n": 0}

    def racing(_name):
        calls["n"] += 1
        if calls["n"] == 1:
            fake2.rows["other"] = {"draft_name": "DRAFT_A.mp4", "status": "qa_blocked"}
            return None
        return {"id": "other", "status": "qa_blocked"}

    up._active_reedit_task = racing
    try:
        up.upsert_qa_reedit_task("DRAFT_A.mp4", gate, binding=b)
    finally:
        up._active_reedit_task = saved
    check(len(fake2.rows) == 1 and fake2.rows["other"].get("target_athlete_key") == b["target_athlete_key"],
          f"B5: a concurrent insert was duplicated or lost: {fake2.rows}")


def close_tests() -> None:
    from integrations import supabase_uploader as up
    fake = FakeTable({"r1": {"status": "queued", "last_pipeline_run_id": "run-A"},
                      "r2": {"status": "queued", "last_pipeline_run_id": "other"}})
    up._supabase = fake.client
    ok = {"verified": True, "binding_mode": "athlete_and_output_bound", "reason": "", "repair_output_sha256": OUT_NEW}
    written = up.close_reprocess_requests({"r1": ok, "r2": ok}, "run-A")
    check(written == {"r1": "done", "r2": "close_not_applied"}, f"B6: closure report {written}")
    check(fake.rows["r1"]["repair_attempt_id"] == "run-A" and fake.rows["r1"]["repair_verdict"] == ok
          and "repair_verdict" not in fake.rows["r2"], f"B6: evidence: {fake.rows}")


def recovery_tests() -> None:
    from integrations import supabase_uploader as up
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(hours=7)).isoformat()
    recent = (now - timedelta(minutes=5)).isoformat()
    fake = FakeTable(
        {"finished": {"status": "queued", "last_pipeline_run_id": "run-done", "attempt_count": 1, "max_attempts": 3},
         "exhausted": {"status": "queued", "last_pipeline_run_id": "run-done", "attempt_count": 3, "max_attempts": 3},
         "silent": {"status": "queued", "last_pipeline_run_id": "run-silent", "attempt_count": 1, "max_attempts": 3},
         "live": {"status": "queued", "last_pipeline_run_id": "run-live", "attempt_count": 1, "max_attempts": 3},
         "mine": {"status": "queued", "last_pipeline_run_id": "run-me", "attempt_count": 1, "max_attempts": 3},
         "orphan": {"status": "queued", "last_pipeline_run_id": "run-gone", "attempt_count": 0, "max_attempts": 3},
         "boom": {"status": "queued", "last_pipeline_run_id": "run-done", "attempt_count": 1, "max_attempts": 3}},
        runs={"run-done": {"status": "failed", "updated_at": recent},
              "run-silent": {"status": "running", "updated_at": old},
              "run-live": {"status": "running", "updated_at": recent}},
        fail_ids={"boom"})
    up._supabase = fake.client
    report = up.recover_stale_reprocess("run-me", now=now)
    expected = {"finished": "pending", "exhausted": "failed_max_attempts", "silent": "pending",
                "live": "owner_still_running", "orphan": "pending", "boom": "close_failed"}
    check(all(report.get(k) == v for k, v in expected.items()) and "mine" not in report,
          f"B7: recovery report {report}")
    r = fake.rows
    check(r["finished"]["attempt_count"] == 2 and r["finished"]["repair_verdict"]["previous_run_id"] == "run-done"
          and r["exhausted"]["status"] == "failed_max_attempts" and r["live"]["status"] == "queued"
          and r["mine"]["status"] == "queued" and r["boom"]["status"] == "queued",
          f"B7: recovery wrote the wrong state: {r}")
    # recovering twice changes nothing more (idempotent)
    again = up.recover_stale_reprocess("run-me", now=now)
    check(not any(v in {"pending", "failed_max_attempts"} for k, v in again.items() if k != "boom"),
          f"B7: recovery is not idempotent: {again}")


def orchestrator_tests() -> None:
    from integrations import supabase_uploader as up
    from pipeline import orchestrator

    b = binding_for([act(10, 18, track="7")])
    req = {"id": "req-1", "draft_name": "DRAFT_A.mp4", "notes": "", "qa_defects": [{"type": "PREMATURE_CUT"}], **b}
    saved = (up.fetch_pending_reprocess, up.claim_reprocess, up.lookup_draft_sources, up.mark_reprocess,
             up.recover_stale_reprocess)
    up.fetch_pending_reprocess = lambda: [req]
    up.claim_reprocess = lambda req_id, run_id=None: True
    up.lookup_draft_sources = lambda name: [{"id": "raw/DJI_0094_D.MP4", "name": "DJI_0094_D.MP4"}]
    up.mark_reprocess = lambda *a, **k: None
    recovered = []
    up.recover_stale_reprocess = lambda run_id: recovered.append(run_id) or {}
    drive = types.ModuleType("integrations.drive")
    drive.requeue_video = lambda _id: True
    sys.modules["integrations.drive"] = drive
    orchestrator._QUEUED_REPROCESS.clear()
    try:
        orchestrator._handle_reprocess_requests()
        queued = list(orchestrator._QUEUED_REPROCESS)
    finally:
        (up.fetch_pending_reprocess, up.claim_reprocess, up.lookup_draft_sources, up.mark_reprocess,
         up.recover_stale_reprocess) = saved
        orchestrator._QUEUED_REPROCESS.clear()
    check(recovered, "B7: the orchestrator must recover stale requests before fetching work")
    check(len(queued) == 1 and queued[0]["target_athlete_key"] == b["target_athlete_key"]
          and queued[0]["original_output_sha256"] == OUT_ORIG, f"B8: binding lost: {queued}")
    verdicts = orchestrator.reprocess_verdicts(queued, manifest(row("A2", part([act(9.5, 19, track="7")]))))
    check(verdicts["req-1"]["verified"] is True, f"B8: orchestrator verdict: {verdicts}")
    json.dumps(verdicts)


def main() -> int:
    binding_tests()
    mode_tests()
    identity_tests()
    output_tests()
    task_refresh_tests()
    close_tests()
    recovery_tests()
    orchestrator_tests()
    print("PASS: reprocess binding (modes, identity-safe matching, exact output, refresh, closure, recovery)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
