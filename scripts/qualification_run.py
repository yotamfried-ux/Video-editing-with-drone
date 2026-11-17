#!/usr/bin/env python3
"""Isolated qualification run helper (see integrations/qualification.py).

  seed      --run-id ID --batch B   verified server-side COPY of raw/<B>/ sources into qualification/<ID>/raw/<B>/
                                    (production read-only; same bytes, ETag and size checked; never overwrites)
  snapshot  --out FILE              read-only fingerprint of production state: R2 review/, approved/,
                                    pending_payment/, previews/, metadata/source_state/, raw/ and the Supabase tables
                                    the Review screen and Discover read (drafts, draft_publishability, reels,
                                    reprocess_requests, pipeline_status)
  compare   A B                     fail (exit 1) when two snapshots differ anywhere
  seed-check --run-id ID --batch B  every seeded object byte-identical (size + ETag) to its production source
  cleanup   --run-id ID             delete objects under qualification/<ID>/ ONLY (refuses any other key)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROD_PREFIXES = ("raw/", "review/", "approved/", "pending_payment/", "previews/", "metadata/source_state/")
REVIEW_TABLES = ("drafts", "draft_publishability", "reels", "reprocess_requests", "pipeline_status")
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{3,62}$")


def _raw_client():
    """Plain boto3 client (NOT the namespaced one): used only for read-only listing and namespace writes here."""
    os.environ.pop("SPORTREEL_QUALIFICATION_RUN_ID", None)
    from integrations import r2_storage
    return r2_storage._client(), r2_storage._bucket()


def _list(client, bucket, prefix):
    out = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        out += page.get("Contents", [])
    return out


def _ns(run_id: str) -> str:
    if not _RUN_ID_RE.match(run_id):
        raise SystemExit(f"invalid run id {run_id!r}")
    return f"qualification/{run_id}/"


def seed(run_id: str, batch: str) -> int:
    client, bucket = _raw_client()
    ns = _ns(run_id)
    src_prefix = f"raw/{batch.strip('/')}/"
    objs = [o for o in _list(client, bucket, src_prefix) if not o["Key"].endswith("/")]
    if not objs:
        raise SystemExit(f"no source objects under {src_prefix}")
    copied = present = 0
    for o in objs:
        dest = ns + o["Key"]
        assert dest.startswith(ns), dest
        try:
            head = client.head_object(Bucket=bucket, Key=dest)
            if head["ContentLength"] != o["Size"] or head.get("ETag") != o.get("ETag"):
                raise SystemExit(f"namespace object differs from source, refusing to overwrite: {dest}")
            present += 1
            continue
        except client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        client.copy_object(Bucket=bucket, Key=dest, CopySource={"Bucket": bucket, "Key": o["Key"]})
        head = client.head_object(Bucket=bucket, Key=dest)
        if head["ContentLength"] != o["Size"] or head.get("ETag") != o.get("ETag"):
            raise SystemExit(f"copy verification failed: {o['Key']} -> {dest}")
        copied += 1
    print(json.dumps({"seeded_prefix": ns + src_prefix, "objects": len(objs), "copied": copied, "already_present": present}))
    return 0


def seed_check(run_id: str, batch: str) -> int:
    client, bucket = _raw_client()
    ns = _ns(run_id)
    src = {o["Key"]: o for o in _list(client, bucket, f"raw/{batch.strip('/')}/")}
    dst = {o["Key"][len(ns):]: o for o in _list(client, bucket, ns + f"raw/{batch.strip('/')}/")}
    bad = [k for k in src if k not in dst or dst[k]["Size"] != src[k]["Size"] or dst[k].get("ETag") != src[k].get("ETag")]
    print(json.dumps({"sources": len(src), "seeded": len(dst), "mismatched_or_missing": bad[:10]}))
    return 1 if bad or not src else 0


def _supabase_rows(table: str) -> tuple[int, str]:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    rows, offset = [], 0
    while True:
        req = urllib.request.Request(f"{base}/rest/v1/{table}?select=*", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Range-Unit": "items", "Range": f"{offset}-{offset + 999}"})
        batch = json.loads(urllib.request.urlopen(req, timeout=60).read())
        rows += batch
        if len(batch) < 1000:
            break
        offset += 1000
    canon = json.dumps(sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str)), sort_keys=True, default=str)
    return len(rows), hashlib.sha256(canon.encode()).hexdigest()


def snapshot(out: Path) -> int:
    client, bucket = _raw_client()
    snap = {"r2": {}, "supabase": {}}
    for prefix in PROD_PREFIXES:
        objs = sorted((o["Key"], o["Size"], o.get("ETag")) for o in _list(client, bucket, prefix))
        snap["r2"][prefix] = {"objects": len(objs), "sha256": hashlib.sha256(json.dumps(objs).encode()).hexdigest()}
    for table in REVIEW_TABLES:
        try:
            n, digest = _supabase_rows(table)
            snap["supabase"][table] = {"rows": n, "sha256": digest}
        except Exception as exc:          # a table that cannot be read is reported, never assumed unchanged
            snap["supabase"][table] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    out.write_text(json.dumps(snap, indent=1, sort_keys=True))
    print(json.dumps(snap, sort_keys=True))
    return 0


def compare(a: Path, b: Path) -> int:
    sa, sb = json.loads(a.read_text()), json.loads(b.read_text())
    diffs = []
    for area in ("r2", "supabase"):
        for k in sorted(set(sa[area]) | set(sb[area])):
            if sa[area].get(k) != sb[area].get(k) or "error" in (sa[area].get(k) or {}):
                diffs.append({"area": area, "item": k, "before": sa[area].get(k), "after": sb[area].get(k)})
    print(json.dumps({"identical": not diffs, "differences": diffs}, indent=1))
    return 1 if diffs else 0


def cleanup(run_id: str) -> int:
    client, bucket = _raw_client()
    ns = _ns(run_id)
    objs = _list(client, bucket, ns)
    for o in objs:
        if not o["Key"].startswith(ns):
            raise SystemExit(f"refusing to delete {o['Key']!r} outside {ns}")
        client.delete_object(Bucket=bucket, Key=o["Key"])
    print(json.dumps({"deleted": len(objs), "namespace": ns}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--run-id", required=True); s.add_argument("--batch", required=True)
    s = sub.add_parser("seed-check"); s.add_argument("--run-id", required=True); s.add_argument("--batch", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("compare"); s.add_argument("a", type=Path); s.add_argument("b", type=Path)
    s = sub.add_parser("cleanup"); s.add_argument("--run-id", required=True)
    a = ap.parse_args()
    if a.cmd == "seed":
        return seed(a.run_id, a.batch)
    if a.cmd == "seed-check":
        return seed_check(a.run_id, a.batch)
    if a.cmd == "snapshot":
        return snapshot(a.out)
    if a.cmd == "compare":
        return compare(a.a, a.b)
    return cleanup(a.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
