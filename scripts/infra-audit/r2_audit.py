#!/usr/bin/env python3
"""Read-only Cloudflare R2 usage audit using your EXISTING credentials (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY).

Lists buckets (if the token allows it, otherwise only R2_BUCKET) and aggregates object count and bytes per top-level prefix.
Prints sizes and counts only (no object names). Uses List requests only (about one Class A request per 1000 objects).
Free tier (Standard): 10 GB-month storage, 1M Class A, 10M Class B per month; $0.015/GB-month beyond; egress is free (Cloudflare pricing page).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FREE_GB, PRICE_PER_GB = 10.0, 0.015


def main() -> int:
    try:
        from integrations.r2_storage import _client, _bucket
    except Exception as exc:  # noqa: BLE001
        print(f"cannot load the existing R2 client (pip install boto3?): {exc}")
        return 2
    client = _client()
    try:
        buckets = [b["Name"] for b in client.list_buckets().get("Buckets", [])]
    except Exception as exc:  # noqa: BLE001
        buckets = [_bucket()]
        print(f"ListBuckets not permitted for this token ({type(exc).__name__}); auditing only '{buckets[0]}'")
    grand = 0
    for name in buckets:
        per = defaultdict(lambda: [0, 0])
        pages = 0
        token = None
        while True:
            kw = {"Bucket": name, "MaxKeys": 1000, **({"ContinuationToken": token} if token else {})}
            res = client.list_objects_v2(**kw)
            pages += 1
            for obj in res.get("Contents", []):
                top = obj["Key"].split("/", 1)[0] + "/" if "/" in obj["Key"] else "<root>"
                per[top][0] += 1
                per[top][1] += obj["Size"]
            if not res.get("IsTruncated"):
                break
            token = res["NextContinuationToken"]
        total = sum(v[1] for v in per.values())
        grand += total
        print(f"\nbucket '{name}': {sum(v[0] for v in per.values())} objects, {total/1e9:.2f} GB  ({pages} list requests)")
        for top, (count, size) in sorted(per.items(), key=lambda kv: -kv[1][1]):
            print(f"  {top:<22} {count:>8} objects  {size/1e9:>9.2f} GB")
    gb = grand / 1e9
    over = max(0.0, gb - FREE_GB)
    print(f"\nACCOUNT-WIDE (listed buckets): {gb:.2f} GB stored (free allowance {FREE_GB:.0f} GB)")
    print(f"approx. current storage charge: ${over * PRICE_PER_GB:.2f}/month at ${PRICE_PER_GB}/GB-month  (check your Cloudflare billing page for the real figure)")
    print("rule of thumb: 1 hour of 4K30 drone footage is roughly 30-50 GB; archiving a COPY of N GB adds about N x $0.015/month")
    print("\nnext: list bucket lock rules with  npx wrangler r2 bucket lock list <bucket>   (not visible through the S3 API)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
