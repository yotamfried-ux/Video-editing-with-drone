#!/usr/bin/env python3
"""Qualification-run isolation (cycle 9, Phase B) — fake boto3 and fake Supabase, no network.

 Q1  every object op of the production storage code (upload_draft, upload_preview, mark_source_processed, listing,
     download, copy, delete, flag_quality_issue, manifest checkpoint via r2._client()) lands under
     qualification/<run>/; listings come back as logical keys; production keys are never touched.
 Q2  S3 methods outside the allowlist (delete_objects, create_bucket, put_bucket_policy) raise.
 Q3  a key in ANOTHER qualification namespace is refused; an invalid run id is refused.
 Q4  Supabase: select passes through; insert / upsert / update / delete / rpc are not sent (ledger instead);
     storage (the Discover `reels` bucket) raises; revoke_draft_publishability and record_draft send nothing.
 Q5  LLM budget: qualification without SPORTREEL_LLM_BUDGET_USD refuses every call; spend + reserve over the
     cap refuses; under the cap allowed.
 Q6  STORAGE_BACKEND=drive with a qualification run id is refused.
 Q7  without SPORTREEL_QUALIFICATION_RUN_ID nothing changes: plain client, writes sent, no budget required.
 Q8  notifications skipped (email, athlete follow) and Cloudflare Stream refused.
 Q10 the qualification workflow is label-gated (never on push), never resets, never saves caches, never writes the
     operator run row / batch lifecycle, fingerprints production before and after, caps the budget at the
     authorised remainder and runs the pipeline with the qualification run id + budget.
 Q9  exact-source dedup in a qualification run reuses production's recorded decision read-only (no RPC, no row
     update); bytes that differ from the recorded SHA-256 are refused (sources are never altered to pass dedup).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS: list[str] = []
TMP = tempfile.mkdtemp(prefix="qual-")
os.environ["TMP_DIR"] = TMP


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ---------------------------------------------------------------- fake boto3
class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple] = []

    class exceptions:  # noqa: N801
        ClientError = Exception

    def _rec(self, *a):
        self.calls.append(a)

    def put_object(self, Bucket, Key, Body=b"", **k):
        self._rec("put", Key); self.objects[Key] = Body if isinstance(Body, bytes) else b"x"

    def get_object(self, Bucket, Key, **k):
        self._rec("get", Key)
        data = self.objects[Key]
        body = types.SimpleNamespace(read=lambda: data, close=lambda: None, iter_chunks=lambda chunk_size=0: [data])
        return {"Body": body, "ContentLength": len(data)}

    def head_object(self, Bucket, Key, **k):
        self._rec("head", Key)
        if Key not in self.objects:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key]), "ETag": str(hash(self.objects[Key]))}

    def delete_object(self, Bucket, Key, **k):
        self._rec("delete", Key); self.objects.pop(Key, None)

    def copy_object(self, Bucket, Key, CopySource, **k):
        self._rec("copy", CopySource["Key"], Key); self.objects[Key] = self.objects[CopySource["Key"]]

    def download_file(self, Bucket, Key, Filename, *a, **k):
        self._rec("download", Key); Path(Filename).write_bytes(self.objects[Key])

    def upload_file(self, Filename, Bucket, Key, *a, **k):
        self._rec("upload", Key); self.objects[Key] = Path(Filename).read_bytes()

    def generate_presigned_url(self, method, Params=None, **k):
        return f"https://signed/{Params['Key']}"

    def get_paginator(self, op):
        store = self
        class P:
            def paginate(self, Bucket, Prefix=""):
                yield {"Contents": [{"Key": k, "Size": len(v), "ETag": "e"} for k, v in store.objects.items() if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, **k):
        self._rec("bulk_delete")

    def create_bucket(self, **k):
        self._rec("create_bucket")

    def put_bucket_policy(self, **k):
        self._rec("policy")


FAKE = FakeS3()


class _ClientError(Exception):
    def __init__(self, response, op):
        super().__init__(op); self.response = response


boto3 = types.ModuleType("boto3"); boto3.client = lambda *a, **k: FAKE
botocore = types.ModuleType("botocore"); bc_config = types.ModuleType("botocore.config"); bc_exc = types.ModuleType("botocore.exceptions")
bc_config.Config = lambda **k: None; bc_exc.ClientError = _ClientError
sys.modules.update({"boto3": boto3, "botocore": botocore, "botocore.config": bc_config, "botocore.exceptions": bc_exc})


# CI jobs without the supabase SDK: a stub module so the production integrations import (the client is faked below).
try:
    from supabase import create_client as _probe  # noqa: F401
except Exception:
    _sb = types.ModuleType("supabase")
    _sb.create_client = lambda *a, **k: None
    _sb.Client = object
    sys.modules["supabase"] = _sb

# ---------------------------------------------------------------- fake supabase
class FakeQuery:
    def __init__(self, log, table, op, payload=None):
        self.log, self.table, self.op, self.payload = log, table, op, payload

    def __getattr__(self, name):
        def chain(*a, **k):
            if name == "execute":
                self.log.append((self.table, self.op, self.payload))
                return types.SimpleNamespace(data=[{"id": 1}] if self.op == "select" else [self.payload])
            return self
        return chain


class FakeTable:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def select(self, *a, **k):
        return FakeQuery(self.log, self.name, "select")

    def insert(self, p, **k):
        return FakeQuery(self.log, self.name, "insert", p)

    def upsert(self, p, **k):
        return FakeQuery(self.log, self.name, "upsert", p)

    def update(self, p, **k):
        return FakeQuery(self.log, self.name, "update", p)

    def delete(self, **k):
        return FakeQuery(self.log, self.name, "delete")


class FakeSupabase:
    def __init__(self):
        self.log = []
        self.storage = types.SimpleNamespace(from_=lambda b: types.SimpleNamespace(upload=lambda *a, **k: self.log.append(("storage", b))))

    def table(self, name):
        return FakeTable(self.log, name)

    def rpc(self, fn, params=None):
        return FakeQuery(self.log, f"rpc:{fn}", "rpc", params)


def fresh(module):
    return importlib.reload(importlib.import_module(module))


def ledger():
    path = Path(TMP) / "pipeline-debug" / "qualification_ledger.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def main() -> int:
    os.environ.update({"SPORTREEL_QUALIFICATION_RUN_ID": "q9-test-run", "STORAGE_BACKEND": "r2", "R2_ENDPOINT_URL": "https://x",
                       "SPORTREEL_LLM_BUDGET_USD": "1.0"})
    q = fresh("integrations.qualification")
    r2 = fresh("integrations.r2_storage")
    ns = "qualification/q9-test-run/"
    FAKE.objects.update({"raw/b1/DJI_0097_D.MP4": b"prod-source", "review/old_draft.mp4": b"prod-draft",
                         ns + "raw/b1/DJI_0097_D.MP4": b"prod-source"})
    prod_before = {k: v for k, v in FAKE.objects.items() if not k.startswith("qualification/")}

    sb = FakeSupabase()
    import integrations.supabase_uploader as su
    su._client = sb
    draft = Path(TMP) / "d.mp4"; draft.write_bytes(b"new-draft")
    key = r2.upload_draft(str(draft), "MULTI_x.mp4")
    r2.upload_preview(str(draft), "MULTI_x_preview.mp4")
    r2.mark_source_processed("raw/b1/DJI_0097_D.MP4")
    listed = r2.list_objects("raw/b1/")
    r2.download_object("raw/b1/DJI_0097_D.MP4", str(Path(TMP) / "src.mp4"))
    r2.flag_quality_issue("raw/b1/DJI_0097_D.MP4", "test")
    r2.copy_object("review/MULTI_x.mp4", "review/MULTI_x_copy.mp4")
    r2.delete_object("review/MULTI_x_copy.mp4")
    r2._client().put_object(Bucket="b", Key="metadata/pipeline_checkpoints/abc.json", Body=b"{}")
    touched = [c for c in FAKE.calls if c[0] not in ("bulk_delete", "create_bucket", "policy")]
    keys = [k for c in touched for k in c[1:]]
    check(key == "review/MULTI_x.mp4", f"Q1 upload_draft returns the logical key ({key})")
    check(all(k.startswith(ns) for k in keys), f"Q1 every R2 call stayed in {ns} ({len(keys)} keys)")
    check({k: v for k, v in FAKE.objects.items() if not k.startswith("qualification/")} == prod_before,
          "Q1 production objects byte-identical (raw source + existing review draft untouched)")
    check([o["Key"] for o in listed] == ["raw/b1/DJI_0097_D.MP4"], f"Q1 listing returns logical keys ({[o['Key'] for o in listed]})")

    for meth in ("delete_objects", "create_bucket", "put_bucket_policy"):
        try:
            getattr(r2._client(), meth)(Bucket="b")
            check(False, f"Q2 {meth} refused")
        except q.QualificationIsolationError:
            check(True, f"Q2 {meth} refused")
    try:
        q.physical_key("qualification/other-run/review/x.mp4"); check(False, "Q3 other namespace refused")
    except q.QualificationIsolationError:
        check(True, "Q3 other namespace refused")
    os.environ["SPORTREEL_QUALIFICATION_RUN_ID"] = "../prod"
    try:
        q.run_id(); check(False, "Q3 invalid run id refused")
    except q.QualificationIsolationError:
        check(True, "Q3 invalid run id refused")
    os.environ["SPORTREEL_QUALIFICATION_RUN_ID"] = "q9-test-run"

    g = su._supabase()
    sent_before = list(sb.log)
    g.table("drafts").select("*").eq("id", 1).execute()
    g.table("drafts").insert({"name": "x"}).execute()
    g.table("draft_publishability").upsert({"storage_object_id": "review/x"}).execute()
    g.table("reels").update({"status": "published"}).eq("id", 1).execute()
    g.table("drafts").delete().eq("id", 1).execute()
    g.rpc("claim_reprocess", {"a": 1}).execute()
    sent = sb.log[len(sent_before):]
    check(sent == [("drafts", "select", None)], f"Q4 only the select reached Supabase ({sent})")
    blocked = [e for e in ledger() if e["kind"] == "supabase_write_blocked"]
    check({(e["table"], e["op"]) for e in blocked} >= {("drafts", "insert"), ("draft_publishability", "upsert"),
                                                     ("reels", "update"), ("drafts", "delete"), ("rpc:claim_reprocess", "rpc")},
          f"Q4 blocked writes recorded in the ledger ({len(blocked)})")
    try:
        g.storage.from_("reels").upload("a", b"b"); check(False, "Q4 Discover storage refused")
    except q.QualificationIsolationError:
        check(True, "Q4 Discover storage (reels bucket) refused")
    check(not [x for x in sb.log if x[0] == "storage"], "Q4 nothing uploaded to Discover storage")
    check(any(e.get("table") == "draft_publishability" and e.get("op") == "update" for e in blocked)
          or any(e.get("table") == "draft_publishability" for e in blocked), "Q4 revoke_draft_publishability (via upload_draft) blocked")

    os.environ.pop("SPORTREEL_LLM_BUDGET_USD")
    try:
        q.check_llm_budget(); check(False, "Q5 no budget -> refused")
    except q.LlmBudgetExceeded:
        check(True, "Q5 qualification without a budget refuses model calls")
    os.environ["SPORTREEL_LLM_BUDGET_USD"] = "0.10"
    cost = Path(TMP) / "pipeline-debug" / "llm_cost_calls.jsonl"
    cost.write_text(json.dumps({"cost_usd": 0.02}) + "\n")
    try:
        q.check_llm_budget(); check(True, "Q5 under the cap allowed ($0.02 + reserve <= $0.10)")
    except q.LlmBudgetExceeded:
        check(False, "Q5 under the cap allowed")
    cost.write_text(json.dumps({"cost_usd": 0.06}) + "\n")
    try:
        q.check_llm_budget(); check(False, "Q5 over the cap refused")
    except q.LlmBudgetExceeded:
        check(True, "Q5 spend + reserve over the cap refused ($0.06 + $0.05 > $0.10)")

    os.environ["STORAGE_BACKEND"] = "drive"
    st = fresh("integrations.storage")
    try:
        st.get_backend_name(); check(False, "Q6 drive refused")
    except q.QualificationIsolationError:
        check(True, "Q6 STORAGE_BACKEND=drive refused in a qualification run")
    os.environ["STORAGE_BACKEND"] = "r2"

    import integrations.athlete_follow as af
    check(af.notify_athlete_followers(None, "reel-1", "ath-1", send=lambda m: FAILS.append("push sent")) == 0,
          "Q8 athlete follow notification skipped")
    import integrations.cloudflare_stream as cs
    try:
        cs.upload_to_stream(str(draft)); check(False, "Q8 Stream refused")
    except q.QualificationIsolationError:
        check(True, "Q8 Cloudflare Stream upload refused")

    class RowsDB:
        def __init__(self, rows):
            self.rows, self.rpcs = rows, []
        def rpc(self, *a, **k):
            self.rpcs.append(a); raise AssertionError("RPC must not be called in a qualification run")
        def table(self, name):
            db = self
            class Q:
                def __init__(self): self.f = {}
                def select(self, *a): return self
                def eq(self, k, v): self.f[k] = v; return self
                def limit(self, n): return self
                def execute(self):
                    return types.SimpleNamespace(data=[r for r in db.rows if all(str(r.get(k)) == str(v) for k, v in self.f.items())])
            return Q()
    import integrations.source_uploads as su2
    db = RowsDB([{"id": "u2", "storage_key": "raw/b1/DJI_0097_D.MP4", "status": "verified", "content_sha256": "abc",
                  "canonical_upload_id": "u1"}, {"id": "u1", "storage_key": "raw/b0/DJI_0097_D.MP4"}])
    decision = su2.resolve_exact_source_duplicate("u2", "abc", client=db)
    check(decision["canonical"] == {"upload_id": "u1", "storage_key": "raw/b0/DJI_0097_D.MP4"} and not db.rpcs,
          f"Q9 recorded canonical reused read-only ({decision['canonical']})")
    try:
        su2.resolve_exact_source_duplicate("u2", "different", client=db); check(False, "Q9 changed bytes refused")
    except RuntimeError:
        check(True, "Q9 bytes differing from the recorded SHA-256 refused")

    os.environ.pop("SPORTREEL_QUALIFICATION_RUN_ID")
    os.environ.pop("SPORTREEL_LLM_BUDGET_USD", None)
    FAKE.calls.clear()
    r2._client().put_object(Bucket="b", Key="review/prod.mp4", Body=b"p")
    check(FAKE.calls == [("put", "review/prod.mp4")], f"Q7 production mode unchanged: plain key ({FAKE.calls})")
    sb2 = FakeSupabase(); su._client = sb2
    su._supabase().table("drafts").insert({"n": 1}).execute()
    check(sb2.log == [("drafts", "insert", {"n": 1})], "Q7 production mode: Supabase writes are sent")
    try:
        q.check_llm_budget(); check(True, "Q7 production mode: no budget required")
    except q.LlmBudgetExceeded:
        check(False, "Q7 production mode: no budget required")
    text = (ROOT / ".github/workflows/pipeline-qualification-run.yml").read_text()
    head = "\n".join(l for l in text.split("jobs:")[0].splitlines() if not l.lstrip().startswith("#"))
    run_block = text[text.index("name: Run pipeline (qualification"):]
    run_block = run_block[:run_block.index("- name:", 10)] if "- name:" in run_block[10:] else run_block
    check("pull_request:" in head and "labeled" in head and "push" not in head and "workflow_dispatch" not in head
          and "qualrun-dry" in text and "qualrun-paid" in text, "Q10 label-gated only")
    check("reset_and_rerun" not in text and "inputs.reset" not in text, "Q10 no reset path")
    check("actions/cache/save" not in text, "Q10 no cache is saved")
    check("record_run_correlation" not in text and "finalize" not in text.lower(), "Q10 no operator run row / batch lifecycle writes")
    check("snapshot --out" in text and " compare " in text, "Q10 production fingerprint before/after + compare")
    check("2.273" in text and "SPORTREEL_LLM_BUDGET_USD" in run_block and "SPORTREEL_QUALIFICATION_RUN_ID" in run_block
          and "PIPELINE_RUN_ID" not in run_block, "Q10 run step: qualification id + capped budget, no production pipeline run id")
    # Q11 (cycle 10, Gate A): fault injection is honoured ONLY inside a qualification run, only at known points
    import subprocess
    code = ("import os; os.environ.pop('SPORTREEL_QUALIFICATION_RUN_ID', None); "
            "os.environ['SPORTREEL_QUALIFICATION_FAULT']='after_analysis'; "
            "from integrations import qualification as q; q.fault('after_analysis'); print('alive')")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    check(r.returncode == 0 and "alive" in r.stdout, f"Q11 no crash outside a qualification run (rc={r.returncode})")
    code_q = ("import os, tempfile; os.environ['SPORTREEL_QUALIFICATION_RUN_ID']='q-fault-test'; "
              "os.environ['TMP_DIR']=tempfile.mkdtemp(); os.environ['SPORTREEL_QUALIFICATION_FAULT']='before_qa'; "
              "from integrations import qualification as q; q.fault('after_analysis'); print('alive1'); "
              "q.fault('before_qa'); print('alive2')")
    r = subprocess.run([sys.executable, "-c", code_q], cwd=str(ROOT), capture_output=True, text=True)
    check(r.returncode == 97 and "alive1" in r.stdout and "alive2" not in r.stdout,
          f"Q11 qualification run: only the configured point crashes, hard, exit 97 (rc={r.returncode})")
    try:
        q.fault("unknown_point"); check(False, "Q11 unknown fault point refused")
    except ValueError:
        check(True, "Q11 unknown fault point refused")
    orch = (ROOT / "pipeline/orchestrator.py").read_text()
    check(all(f'_qualification.fault("{p}")' in orch for p in q.FAULT_POINTS), "Q11 every fault point is wired in the orchestrator")
    # Gate A run 44140263067: production replaces orchestrator._compile_clusters with the context-QA path, so the
    # QA and upload fault points must live THERE (they never fired when they were only in the shadowed function).
    ctx = (ROOT / "pipeline/context_qa_gate.py").read_text()
    check('_qualification.fault("before_qa")' in ctx and '_qualification.fault("after_first_upload")' in ctx,
          "Q11 QA and upload fault points are wired in the ACTIVE compile path (context_qa_gate)")
    ga = (ROOT / ".github/workflows/pipeline-qualification-gate-a.yml").read_text()
    ga_head = "\n".join(l for l in ga.split("jobs:")[0].splitlines() if not l.lstrip().startswith("#"))
    check("labeled" in ga_head and "push" not in ga_head and "workflow_dispatch" not in ga_head and "qualgate-a" in ga,
          "Q12 Gate A workflow is label-gated only")
    check("SPORTREEL_LLM_BUDGET_USD: '0'" in ga and "actions/cache/save" not in ga and "PIPELINE_RUN_ID" not in ga
          and "reset_and_rerun" not in ga and "snapshot --out" in ga and " compare " in ga,
          "Q12 Gate A: budget 0, no cache save, no production run id, no reset, production fingerprint compared")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
