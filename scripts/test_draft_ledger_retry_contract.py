#!/usr/bin/env python3
"""PA-13 (cycle 12): no duplicate Review drafts across crashes and retries - RED on the legacy names, GREEN with the
draft ledger. Exercises the production hooks pipeline.context_qa_gate._ledger_assign / _ledger_upload, the
production uploader chain (orchestrator.upload_draft -> metadata via draft_ledger.upload_metadata) and
pipeline.draft_ledger.publish, against an in-memory object store with real conditional-PUT semantics (If-Match /
If-None-Match, ETags). The real R2 path is exercised by the Gate A workflow (scripts/qualification_gate_a.py).

Scenarios (3 reels per run, names = legacy DRAFT_<description>_<date>):
 L1..L10  - the same scenarios with SPORTREEL_DRAFT_LEDGER=0 must show the defect (RED) where it exists
 D1  crash after the first upload, retry                    -> 3 review objects, no duplicate, all committed
 D1b crash after an upload but before the ledger commit      -> retry commits it without re-upload
 D2  crash after several parallel uploads, retry             -> no duplicate, nothing lost
 D3  retry the same day                                      -> same names, SKIPPED (same plan), no new revision
 D4  retry on another day                                    -> names kept
 D5  retry with different model descriptions                 -> names kept
 D6  retry after QA PASS (same plan)                         -> bytes and revision unchanged
 D7  retry after QA FAIL -> PASS, same plan                  -> no second object; verdict history kept
 D8  retry after the render changed (new plan)               -> same name, new revision, previous bytes archived
                                                                (copy), new revision requires a new approval
 D9  retry after the operator approved (review -> approved)  -> same plan: nothing uploaded, approved untouched;
                                                                new plan: one pending review revision, approved
                                                                bytes and approval untouched
 D10 two concurrent runs                                     -> one object per reel, ledgers consistent
 S   safety: no delete, nothing written outside review/ and metadata/, raw/ untouched, every revision recoverable
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import context_qa_gate as cqg  # noqa: E402
from pipeline import draft_ledger as dl  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


class MemStore:
    """S3-like store: objects with ETag + metadata, conditional PUT, no delete method at all."""

    def __init__(self):
        self.objects: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.writes: list[str] = []
        self.deletes = 0
        self._n = 0

    def _etag(self) -> str:
        self._n += 1
        return f'"e{self._n}"'

    def get_json(self, key):
        with self.lock:
            obj = self.objects.get(key)
            return (json.loads(obj["body"]), obj["etag"]) if obj else (None, None)

    def put_json(self, key, data, *, if_match=None, if_none_match=False):
        with self.lock:
            cur = self.objects.get(key)
            if if_none_match and cur is not None:
                return False
            if if_match and (cur is None or cur["etag"] != if_match):
                return False
            self.objects[key] = {"body": json.dumps(data, sort_keys=True), "etag": self._etag(), "metadata": {}}
            self.writes.append(key)
            return True

    def head(self, key):
        with self.lock:
            obj = self.objects.get(key)
            return None if obj is None else {"size": len(obj["body"]), "etag": obj["etag"], "metadata": dict(obj["metadata"])}

    def copy(self, src, dst):
        with self.lock:
            self.objects[dst] = dict(self.objects[src], etag=self._etag())
            self.writes.append(dst)

    def put_video(self, key, path, metadata):
        with self.lock:
            self.objects[key] = {"body": Path(path).read_text(), "etag": self._etag(), "metadata": dict(metadata or {})}
            self.writes.append(key)

    def move(self, src, dst):  # the OPERATOR's approval action (app), not the pipeline
        with self.lock:
            self.objects[dst] = self.objects.pop(src)

    def review(self):
        return sorted(k for k in self.objects if k.startswith("review/"))


class Crash(RuntimeError):
    pass


class FakeOrchestrator:
    """orchestrator.upload_draft as wired in production: the store is R2, the metadata arrives via the ledger."""

    def __init__(self, store: MemStore):
        self.store = store
        self.uploads = 0
        self.crash_after: int | None = None
        self.crash_before_commit = False
        self.lock = threading.Lock()

    def upload_draft(self, path, name):
        with self.lock:
            if self.crash_after is not None and self.uploads >= self.crash_after:
                raise Crash("injected crash before upload")
            self.uploads += 1
        self.store.put_video("review/" + Path(name).name, path, dl.pending_upload_metadata())
        if self.crash_before_commit:
            raise Crash("injected crash after upload, before ledger commit")
        return "review/" + Path(name).name


SOURCES = {}


def make_sources(tmp: Path):
    for name in ("0097", "0115", "0142"):
        p = tmp / f"2026-10-03T12-19-53_DJI_2026072016_{name}_D.MP4"
        p.write_bytes(b"raw-" + name.encode())
        SOURCES[name] = p


def clusters(desc_suffix=""):
    return [{"description": f"surfer {k} {desc_suffix}".strip(),
             "appearances": [{"path": str(SOURCES[k]), "_person_id": "person_A",
                              "events": [{"person_id": "person_A", "start": 1.0, "end": 9.0}]}]} for k in ("0097", "0115", "0142")]


def run_once(store, orch, tmp, *, day="20261118", desc="", plan_shift=0.0, flagged=False, crash_after=None,
             crash_before_commit=False, parallel=False, run_id="run-1", barrier=None):
    """One pipeline run of the naming + upload stages. Returns (names, outcomes-or-errors)."""
    orch.crash_after, orch.crash_before_commit = crash_after, crash_before_commit
    jobs = []
    for i, cl in enumerate(clusters(desc)):
        reel = tmp / f"{run_id}_{i}_{day}_{plan_shift}.mp4"
        reel.write_text(f"render {cl['description']} {plan_shift}")
        events = [{"source_path": cl["appearances"][0]["path"], "start": 1.0 + plan_shift, "end": 9.0, "track_id": "7"}]
        proposed = f"DRAFT_{cl['description'].replace(' ', '_')}{'_QA-FLAGGED' if flagged else ''}_{day}.mp4"
        os.environ["SPORTREEL_QUALIFICATION_RUN_ID"] = run_id
        name = cqg._ledger_assign(cl, 1, False, proposed, str(reel), events, flagged)
        jobs.append((str(reel), name))
    if barrier is not None:
        barrier.wait()
    errors = []

    def up(job):
        try:
            cqg._ledger_upload(orch, *job)
            return job[1]
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)
            return None
    if parallel:
        with ThreadPoolExecutor(max_workers=3) as pool:
            done = list(pool.map(up, jobs))
    else:
        done = []
        for job in jobs:
            r = up(job)
            done.append(r)
            if r is None:
                break
    return [j[1] for j in jobs], errors


def ledger(store, name_hint):
    for k, o in store.objects.items():
        if k.startswith(dl.LEDGER_PREFIX) and "/names/" not in k:
            d = json.loads(o["body"])
            if name_hint in d.get("draft_name", ""):
                return d
    return {}


def fresh(ledger_on: bool):
    store, tmp = MemStore(), Path(tempfile.mkdtemp(prefix="pa13-"))
    make_sources(tmp)
    orch = FakeOrchestrator(store)
    os.environ["SPORTREEL_DRAFT_LEDGER"] = "1" if ledger_on else "0"
    dl.default_store = (lambda uploader=None: _Adapter(store, uploader)) if ledger_on else (lambda uploader=None: None)
    return store, orch, tmp


class _Adapter(dl.R2Store):
    """The production R2Store logic (uploader + metadata channel) over the in-memory store."""

    def __init__(self, store, uploader):
        super().__init__(uploader)
        self.s = store

    def get_json(self, key): return self.s.get_json(key)
    def put_json(self, key, data, **k): return self.s.put_json(key, data, **k)
    def head(self, key): return self.s.head(key)
    def copy(self, src, dst): self.s.copy(src, dst)


def main() -> int:
    os.environ["STORAGE_BACKEND"] = "r2"
    original_default = dl.default_store

    # ---------------- RED: legacy names (ledger off) ----------------
    store, orch, tmp = fresh(False)
    run_once(store, orch, tmp, crash_after=1)
    run_once(store, orch, tmp, day="20261119", desc="(retry)")
    check(len(store.review()) > 3, f"L1/L4/L5 RED legacy: crash + retry next day with new descriptions -> {len(store.review())} review objects for 3 reels (duplicates)")

    # ---------------- GREEN: ledger ----------------
    store, orch, tmp = fresh(True)
    names1, err = run_once(store, orch, tmp, crash_after=1)
    check(err == ["Crash"] and len(store.review()) == 1, f"D1 crash after the first upload ({err}, {len(store.review())} object)")
    names2, err = run_once(store, orch, tmp)
    check(not err and len(store.review()) == 3 and names2 == names1, f"D1 retry: 3 objects, same names, no duplicate ({store.review()})")
    revs = [ledger(store, n[:20]).get("revisions", []) for n in names2]
    check(all(r and r[-1]["committed"] and all(x.get("committed") or x.get("abandoned") for x in r) for r in revs),
          "D1 latest revision of every reel committed; the crashed intents closed as abandoned (none left pending)")

    store, orch, tmp = fresh(True)
    run_once(store, orch, tmp, crash_before_commit=True)
    before = orch.uploads
    names, err = run_once(store, orch, tmp)
    l0 = ledger(store, names[0][:20])
    check(not err and orch.uploads == before + 2 and l0["revisions"][-1]["committed"] and len(l0["revisions"]) == 1,
          f"D1b crash after upload before commit: retry commits that reel without re-upload, uploads only the 2 others ({before}->{orch.uploads})")

    store, orch, tmp = fresh(True)
    run_once(store, orch, tmp, crash_after=2, parallel=True)
    n_crash = len(store.review())
    names, err = run_once(store, orch, tmp, parallel=True)
    check(not err and len(store.review()) == 3 and n_crash == 2, f"D2 parallel crash after 2 uploads ({n_crash}) -> retry 3 objects, none lost")

    store, orch, tmp = fresh(True)
    n1, _ = run_once(store, orch, tmp)
    up1 = orch.uploads
    n3, err = run_once(store, orch, tmp)
    check(not err and n3 == n1 and orch.uploads == up1 and len(ledger(store, n1[0][:20])["revisions"]) == 1,
          "D3 retry same day: same names, nothing re-uploaded, no new revision")
    n4, err = run_once(store, orch, tmp, day="20261125")
    check(not err and n4 == n1 and len(store.review()) == 3, f"D4 retry another day: names kept ({n4[0]})")
    n5, err = run_once(store, orch, tmp, day="20261126", desc="in a dark wetsuit")
    check(not err and n5 == n1 and len(store.review()) == 3, "D5 retry with a different model description: names kept")
    bytes_before = {k: store.objects[k]["body"] for k in store.review()}
    run_once(store, orch, tmp)
    check({k: store.objects[k]["body"] for k in store.review()} == bytes_before, "D6 retry after QA PASS (same plan): bytes unchanged")

    store, orch, tmp = fresh(True)
    nf, _ = run_once(store, orch, tmp, flagged=True)
    npass, err = run_once(store, orch, tmp, flagged=False)
    check(not err and npass == nf and len(store.review()) == 3, f"D7 QA FAIL then PASS (same plan): one object per reel ({store.review()[0]})")

    store, orch, tmp = fresh(True)
    n1, _ = run_once(store, orch, tmp)
    old_bytes = store.objects["review/" + n1[0]]["body"]
    n8, err = run_once(store, orch, tmp, plan_shift=0.5)
    l8 = ledger(store, n1[0][:20])
    archived = [k for k in store.objects if k.startswith(dl.REVISION_PREFIX)]
    check(not err and n8 == n1 and len(store.review()) == 3 and len(l8["revisions"]) == 2 and l8["revisions"][-1]["requires_new_approval"],
          "D8 render changed: same name, revision 2, requires a new approval")
    check(any(store.objects[k]["body"] == old_bytes for k in archived), "D8 previous revision bytes archived (copy) and recoverable")

    store, orch, tmp = fresh(True)
    n1, _ = run_once(store, orch, tmp)
    store.move("review/" + n1[0], "approved/" + n1[0])
    approved_bytes = store.objects["approved/" + n1[0]]["body"]
    up = orch.uploads
    run_once(store, orch, tmp)
    check(orch.uploads == up and "review/" + n1[0] not in store.objects, "D9 after approval, same plan: nothing uploaded, no review duplicate")
    run_once(store, orch, tmp, plan_shift=0.7)
    l9 = ledger(store, n1[0][:20])
    check(store.objects["approved/" + n1[0]]["body"] == approved_bytes and "review/" + n1[0] in store.objects
          and l9["revisions"][-1]["requires_new_approval"] and not l9["revisions"][-1].get("approved"),
          "D9 after approval, new plan: approved bytes untouched; one pending review revision needing a new approval")

    store, orch, tmp = fresh(True)
    barrier = threading.Barrier(2)
    results = []
    t1 = threading.Thread(target=lambda: results.append(run_once(store, orch, tmp, run_id="run-a", barrier=barrier, parallel=True)))
    t2 = threading.Thread(target=lambda: results.append(run_once(store, orch, tmp, run_id="run-b", day="20261119", desc="other", barrier=barrier, parallel=True)))
    t1.start(); t2.start(); t1.join(); t2.join()
    names_a, names_b = results[0][0], results[1][0]
    check(len(store.review()) == 3 and sorted(names_a) == sorted(names_b), f"D10 two concurrent runs: 3 objects, identical names ({len(store.review())})")
    revs = [ledger(store, n[:20]).get("revisions", []) for n in names_a]
    check(not (results[0][1] + results[1][1]) and all(r and r[-1]["committed"] for r in revs),
          f"D10 no error in either run, latest revision of every reel committed (errors {results[0][1] + results[1][1]})")

    sys.path.insert(0, str(ROOT / "scripts"))
    import qualification_ledger_inventory as qli

    def inventory(st):
        rev = [{"key": k, "cid": st.objects[k]["metadata"].get(dl.META_CID)} for k in st.review()]
        leds = [json.loads(o["body"]) for k, o in st.objects.items() if k.startswith(dl.LEDGER_PREFIX) and "/names/" not in k]
        return {"review": rev, "ledgers": [{"cid": l["cid"], "draft_name": l["draft_name"], "revisions": l["revisions"]} for l in leds]}
    inv = inventory(store)
    dup = {"review": inv["review"] + [{"key": "review/DRAFT_other_name.mp4", "cid": inv["review"][0]["cid"]}],
           "ledgers": inv["ledgers"] + [dict(inv["ledgers"][0], draft_name="DRAFT_other_name.mp4")]}
    check(qli.check(inv) == [] and any("review objects" in p for p in qli.check(dup)),
          "I namespace inventory check: clean after concurrent runs; a second object for one canonical reel is reported")
    check(store.deletes == 0 and all(k.startswith(("review/", "metadata/")) for k in store.writes)
          and not any(k.startswith(("raw/", "approved/")) for k in store.writes),
          "S no delete; writes only under review/ and metadata/; raw/ and approved/ never written by the pipeline")
    from integrations import qualification
    from pipeline import orchestrator
    os.environ.update(SPORTREEL_QUALIFICATION_DESCRIPTION_SUFFIX="retry", SPORTREEL_QUALIFICATION_DRAFT_DATE="20991231")
    os.environ.pop("SPORTREEL_QUALIFICATION_RUN_ID", None)
    prod = cqg._proposed_draft_name(orchestrator, "Surfer", "")
    os.environ["SPORTREEL_QUALIFICATION_RUN_ID"] = "q12-contract"
    qual = cqg._proposed_draft_name(orchestrator, "Surfer", "")
    check(qualification.draft_name_perturbation() == ("retry", "20991231") and "retry" not in prod and "20991231" not in prod
          and "retry" in qual and qual.endswith("_20991231.mp4"),
          f"Q Gate A name perturbation only inside a qualification run (production {prod}, qualification {qual})")
    for k in ("SPORTREEL_QUALIFICATION_DESCRIPTION_SUFFIX", "SPORTREEL_QUALIFICATION_DRAFT_DATE", "SPORTREEL_QUALIFICATION_RUN_ID"):
        os.environ.pop(k, None)
    dl.default_store = original_default
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
