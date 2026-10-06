#!/usr/bin/env python3
"""Read-only forensic: locate every active verified source of a batch in R2.

Never writes to R2 or Supabase.  Prints, per source, where the object lives
(raw/<batch>/, processed/<batch>/, legacy flat processed/ or raw/), its size
against the verified size, and (with --sha256) its SHA-256 against the durable
content identity.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.r2_batch_restore import R2Store, processed_key_for  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_id")
    parser.add_argument("--sha256", action="store_true")
    args = parser.parse_args()
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    q = urllib.parse.urlencode({
        "batch_id": f"eq.{args.batch_id}", "removed_at": "is.null", "superseded_at": "is.null",
        "select": "id,storage_key,source_filename,source_size_bytes,verified_size_bytes,content_sha256,status",
        "order": "created_at.asc,id.asc",
    })
    req = urllib.request.Request(f"{base}/rest/v1/source_uploads?{q}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
    store = R2Store()
    bad = 0
    print(f"batch={args.batch_id} active_sources={len(rows)}")
    for r in rows:
        k = r["storage_key"]
        name = k.rsplit("/", 1)[-1]
        cands = {
            "raw/<batch>": k,
            "processed/<batch>": processed_key_for(k),
            "processed/flat": "processed/" + name,
            "raw/flat": "raw/" + name,
        }
        found = {}
        for label, ck in cands.items():
            meta = store.head(ck)
            if meta is not None:
                found[label] = (ck, int(meta["ContentLength"]))
        line = {"file": r["source_filename"], "expected": r["verified_size_bytes"], "found": {l: v[1] for l, v in found.items()}}
        if args.sha256 and found:
            line["sha_match"] = {l: store.sha256(v[0]) == r["content_sha256"] for l, v in found.items()}
        print(json.dumps(line))
        good = [l for l, v in found.items() if v[1] == r["verified_size_bytes"]]
        if not good:
            bad += 1
    for prefix in (f"raw/{args.batch_id}/", f"processed/{args.batch_id}/"):
        objs = store.list(prefix)
        print(f"listing {prefix}: {len(objs)} objects")
    print(f"sources_without_matching_object={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
