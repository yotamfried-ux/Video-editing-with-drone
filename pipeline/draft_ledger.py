"""Stable Review-draft identity, revisions and idempotent upload (PA-13). Sport-neutral Core.

Problem: a draft object was named only from the model's athlete description and the date
(``DRAFT_<description>_<YYYYMMDD>.mp4``). A paid run that crashed after some uploads and was retried on another day,
or with a different model description, left the first drafts next to the new ones (duplicates).

This module gives every reel a CANONICAL id that does not depend on any model text or date:

    canonical_reel_id = H(sorted source content SHA-256 :: person of every appearance, part index, variant)

and keeps a small ledger per canonical reel (``metadata/draft_ledger/<cid>.json``) with the draft name it first
received and every revision (render plan digest, render SHA-256, run id, QA verdict, committed or not). Names are
claimed in ``metadata/draft_ledger/names/<H(name)>.json`` so two different reels never share an object name.

Upload protocol (``publish``):
  1. read the ledger (with its ETag);
  2. same plan already committed and its object still exists in review/ or approved/ -> SKIP (idempotent retry);
  3. same plan pending (a crash after upload, before commit) and the review object carries this cid + plan in its
     metadata -> commit without re-upload;
  4. otherwise write the revision intent with a conditional PUT (If-Match / If-None-Match), copy any existing review
     object to ``metadata/draft_revisions/<cid>/r<k>.mp4`` (copy, never delete), upload the new render under the SAME
     draft name with cid/plan/revision metadata (the existing upload path revokes the old object's publishability),
     then commit the revision with another conditional PUT.

Never: delete or move a draft, write approved/, write raw/, publish, or carry an approval to new bytes (approval
is the operator's move to approved/; a changed plan only ever creates a pending review revision).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Protocol

SCHEMA = "sportreel.draft_ledger.v1"
LEDGER_PREFIX = "metadata/draft_ledger/"
NAME_PREFIX = "metadata/draft_ledger/names/"
REVISION_PREFIX = "metadata/draft_revisions/"
REVIEW_PREFIX = "review/"
APPROVED_PREFIX = "approved/"
META_CID = "sportreel-cid"
META_PLAN = "sportreel-plan"
META_REV = "sportreel-rev"
META_RUN = "sportreel-run"
_MAX_CAS_ATTEMPTS = 4


_UPLOAD_META = threading.local()


@contextmanager
def upload_metadata(meta: dict[str, str]):
    """Object metadata for the next REVIEW upload on this thread (read by integrations.r2_storage.upload_draft).

    Lets the ledger upload through ``orchestrator.upload_draft`` and so keep every wrapper on that path (publishable
    manifest, publishability revocation) instead of bypassing them.
    """
    previous = getattr(_UPLOAD_META, "value", None)
    _UPLOAD_META.value = dict(meta)
    try:
        yield
    finally:
        _UPLOAD_META.value = previous


def pending_upload_metadata() -> dict[str, str] | None:
    return getattr(_UPLOAD_META, "value", None)


class ConcurrentDraftWriter(RuntimeError):
    """Another run kept changing this reel's ledger; the caller stages the reel instead of guessing."""


def enabled() -> bool:
    return os.getenv("SPORTREEL_DRAFT_LEDGER", "1").strip().lower() not in {"0", "false", "no", "off"}


# ---------------------------------------------------------------------------------------------------------------
# identity of a reel and of its render plan
# ---------------------------------------------------------------------------------------------------------------

def _source(path: str) -> str:
    from pipeline import event_identity

    kind, value = event_identity.source_ref(str(path or ""))
    return f"{kind}:{value}"


def _person(app: dict[str, Any]) -> str:
    from pipeline import identity_evidence

    return identity_evidence.member_key(app).split("::", 1)[-1]


def canonical_reel_id(appearances: list[dict[str, Any]], *, part_index: int = 1, variant: str = "clean") -> str:
    """Id of the reel from the content of its sources and the person in each, never from a description or date."""
    members = sorted({f"{_source(a.get('path'))}::{_person(a)}" for a in appearances or []})
    payload = json.dumps({"schema": "sportreel.canonical_reel.v1", "members": members,
                          "part": int(part_index or 1), "variant": str(variant or "clean")}, sort_keys=True)
    return "cr_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def plan_digest(events: list[dict[str, Any]]) -> str:
    """What the render shows: per event its source content, window (10 ms) and tracked actor. Model text ignored."""
    rows = []
    for ev in events or []:
        src = ev.get("_source_path") or ev.get("source_path") or ev.get("source") or ev.get("path") or ""
        rows.append([_source(src) if src else str(ev.get("event_source_ref") or ""),
                     round(float(ev.get("start") or 0.0), 2), round(float(ev.get("end") or 0.0), 2),
                     str(ev.get("target_track_id") or ev.get("track_id") or "")])
    return hashlib.sha256(json.dumps(sorted(rows)).encode("utf-8")).hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------------------------------------------

class Store(Protocol):
    def get_json(self, key: str) -> tuple[dict | None, str | None]: ...
    def put_json(self, key: str, data: dict, *, if_match: str | None = None, if_none_match: bool = False) -> bool: ...
    def head(self, key: str) -> dict | None: ...
    def copy(self, src: str, dst: str) -> None: ...
    def upload_review(self, local_path: str, draft_name: str, metadata: dict[str, str]) -> str: ...


class R2Store:
    """The production R2 adapter (namespaced automatically inside a qualification run).

    ``uploader(local_path, draft_name)`` is the pipeline's upload entry point (``orchestrator.upload_draft`` with its
    manifest wrapper); the object metadata reaches R2 through ``upload_metadata``.
    """

    def __init__(self, uploader: Callable[[str, str], Any] | None = None):
        self._uploader = uploader

    def _c(self):
        from integrations import r2_storage

        return r2_storage._client(), r2_storage._bucket()

    def get_json(self, key):
        from botocore.exceptions import ClientError

        client, bucket = self._c()
        try:
            obj = client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404", "NotFound"):
                return None, None
            raise
        return json.loads(obj["Body"].read()), obj.get("ETag")

    def put_json(self, key, data, *, if_match=None, if_none_match=False):
        from botocore.exceptions import ClientError

        client, bucket = self._c()
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "ContentType": "application/json",
                                  "Body": json.dumps(data, sort_keys=True).encode("utf-8")}
        if if_match:
            kwargs["IfMatch"] = if_match
        elif if_none_match:
            kwargs["IfNoneMatch"] = "*"
        try:
            client.put_object(**kwargs)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in (409, 412):
                return False
            raise
        return True

    def head(self, key):
        from integrations import r2_storage

        head = r2_storage._head(key)
        if head is None:
            return None
        return {"size": head.get("ContentLength"), "etag": head.get("ETag"),
                "metadata": {str(k).lower(): v for k, v in (head.get("Metadata") or {}).items()}}

    def copy(self, src, dst):
        from integrations import r2_storage

        r2_storage.copy_object(src, dst)

    def upload_review(self, local_path, draft_name, metadata):
        from integrations import r2_storage

        uploader = self._uploader or r2_storage.upload_draft
        with upload_metadata(metadata):
            result = uploader(local_path, draft_name)
        return str(result or (REVIEW_PREFIX + draft_name))


def ledger_key(cid: str) -> str:
    return f"{LEDGER_PREFIX}{cid}.json"


def name_key(name: str) -> str:
    return f"{NAME_PREFIX}{hashlib.sha256(name.encode('utf-8')).hexdigest()}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------------------------------------------

def _variant_name(name: str, k: int) -> str:
    stem = name[:-4] if name.endswith(".mp4") else name
    return f"{stem}_{k}.mp4"


def assign_name(store: Store, cid: str, proposed: str, *, run_id: str = "", members: list[str] | None = None) -> str:
    """The reel's stable draft name: the name its ledger already holds, else the first free proposed name.

    The ledger entry is created atomically (If-None-Match) together with the name, so of two concurrent runs the
    first one's name wins and the second reads it. A name claimed by ANOTHER canonical reel is never reused.
    """
    entry, _ = store.get_json(ledger_key(cid))
    if entry and entry.get("draft_name"):
        return str(entry["draft_name"])
    candidate = os.path.basename(proposed)
    for k in range(1, 50):
        claimed = store.put_json(name_key(candidate), {"schema": SCHEMA, "name": candidate, "cid": cid,
                                                       "claimed_at": _now(), "run_id": run_id}, if_none_match=True)
        if not claimed:
            owner, _ = store.get_json(name_key(candidate))
            claimed = bool(owner and owner.get("cid") == cid)
        if claimed:
            fresh_entry = {"schema": SCHEMA, "cid": cid, "draft_name": candidate, "members": members or [],
                           "created_at": _now(), "created_by": run_id, "revisions": []}
            if store.put_json(ledger_key(cid), fresh_entry, if_none_match=True):
                return candidate
            entry, _ = store.get_json(ledger_key(cid))
            return str((entry or {}).get("draft_name") or candidate)
        candidate = _variant_name(os.path.basename(proposed), k + 1)
    raise ConcurrentDraftWriter(f"could not claim a draft name for {cid}")


# ---------------------------------------------------------------------------------------------------------------
# revisions
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    action: str            # UPLOADED | SKIPPED_SAME_PLAN | COMMITTED_PENDING
    draft_name: str
    revision: int
    key: str


def _object_for(store: Store, name: str) -> tuple[str, dict] | None:
    for prefix in (REVIEW_PREFIX, APPROVED_PREFIX):
        head = store.head(prefix + name)
        if head is not None:
            return prefix + name, head
    return None


def publish(store: Store, *, cid: str, draft_name: str, plan: str, render_path: str, run_id: str = "",
            qa_verdict: str = "", members: list[str] | None = None) -> Outcome:
    """Idempotently put the render for ``cid`` under its stable ``draft_name`` (see the module docstring)."""
    for _attempt in range(_MAX_CAS_ATTEMPTS):
        entry, etag = store.get_json(ledger_key(cid))
        entry = entry or {"schema": SCHEMA, "cid": cid, "draft_name": draft_name, "members": members or [],
                          "created_at": _now(), "revisions": []}
        name = str(entry.get("draft_name") or draft_name)
        revisions = list(entry.get("revisions") or [])
        found = _object_for(store, name)
        committed = [r for r in revisions if r.get("committed")]
        if committed and committed[-1].get("plan") == plan and found is not None:
            return Outcome("SKIPPED_SAME_PLAN", name, int(committed[-1]["rev"]), found[0])
        pending = [r for r in revisions if not r.get("committed") and r.get("plan") == plan]
        if pending and found is not None and found[0].startswith(REVIEW_PREFIX):
            meta = found[1].get("metadata") or {}
            if meta.get(META_CID) == cid and meta.get(META_PLAN) == plan and meta.get(META_REV) == str(pending[-1]["rev"]):
                pending[-1].update(committed=True, committed_at=_now(), committed_by=run_id,
                                   size=found[1].get("size"), etag=found[1].get("etag"))
                if store.put_json(ledger_key(cid), dict(entry, revisions=revisions), if_match=etag):
                    return Outcome("COMMITTED_PENDING", name, int(pending[-1]["rev"]), found[0])
                continue
        # Pending revisions that never produced this object (a crash before/while uploading) are closed as
        # abandoned, never silently reused. A concurrent run uploading the same reel writes the SAME object name,
        # serialised by the conditional ledger writes: one object, nothing lost.
        for r in revisions:
            if not r.get("committed") and not r.get("abandoned"):
                r["abandoned"] = True
                r["abandoned_at"] = _now()
                r["abandoned_by"] = run_id
        rev = 1 + max([int(r.get("rev") or 0) for r in revisions] or [0])
        render_sha = file_sha256(render_path)
        intent = {"rev": rev, "plan": plan, "render_sha256": render_sha, "run_id": run_id, "qa_verdict": qa_verdict,
                  "committed": False, "started_at": _now(),
                  "requires_new_approval": bool(committed) and committed[-1].get("plan") != plan}
        new_entry = dict(entry, draft_name=name, revisions=revisions + [intent])
        ok = (store.put_json(ledger_key(cid), new_entry, if_match=etag) if etag
              else store.put_json(ledger_key(cid), new_entry, if_none_match=True))
        if not ok:
            continue
        if found is not None and found[0].startswith(REVIEW_PREFIX):
            prev = (found[1].get("metadata") or {}).get(META_REV) or "legacy"
            store.copy(found[0], f"{REVISION_PREFIX}{cid}/r{prev}_{found[1].get('etag', '').strip(chr(34))[:12]}.mp4")
        key = store.upload_review(render_path, name, {META_CID: cid, META_PLAN: plan, META_REV: str(rev), META_RUN: run_id})
        for _commit in range(_MAX_CAS_ATTEMPTS):
            latest, latest_etag = store.get_json(ledger_key(cid))
            latest = latest or new_entry
            revs = list(latest.get("revisions") or [])
            for r in revs:
                if r.get("rev") == rev and r.get("run_id") == run_id:
                    r.update(committed=True, committed_at=_now(), committed_by=run_id)
            if store.put_json(ledger_key(cid), dict(latest, revisions=revs), if_match=latest_etag):
                return Outcome("UPLOADED", name, rev, key)
        raise ConcurrentDraftWriter(f"uploaded {name} revision {rev} but could not commit the ledger")
    raise ConcurrentDraftWriter(f"ledger for {cid} kept changing")


def default_store(uploader: Callable[[str, str], Any] | None = None) -> Store | None:
    """The R2 ledger store when drafts go to R2 and the ledger is enabled, else None (legacy behaviour)."""
    if not enabled() or os.getenv("STORAGE_BACKEND", "r2").strip().lower() != "r2":
        return None
    return R2Store(uploader)


Uploader = Callable[[str, str], str]
