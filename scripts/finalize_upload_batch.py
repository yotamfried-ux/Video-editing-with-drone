#!/usr/bin/env python3
"""Finalize the durable upload batch that belongs to a tracked pipeline run.

This is intentionally stdlib-only so it can run even when dependency setup or
pipeline execution fails. It never deletes source objects. A successful
pipeline closes its batch as completed; any terminal non-success result closes
it as failed. Non-terminal runs are left untouched. Cancelled and timed-out
workflows close as failed so the batch can be retried instead of staying locked.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SUCCESS = {"succeeded"}
# Cancellation/timeouts are normally rewritten to "failed" by finalize_unfinished_run.py
# before this runs; the synonyms keep a batch from staying "running" forever if a
# cancelled run row is ever written with its own status.
FAILURE = {
    "failed", "dispatch_failed", "no_input", "no_reviewable_drafts",
    "cancelled", "canceled", "timed_out", "cancelling",
}


def request_json(method: str, url: str, key: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8") or "[]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="")
    parser.add_argument("--batch-id", default="")
    args = parser.parse_args()

    run_id = args.run_id.strip()
    batch_id = args.batch_id.strip()
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not run_id or not batch_id:
        print("batch-finalize: missing tracked run id or batch id; nothing to do")
        return 0
    if not base or not key:
        print("batch-finalize: Supabase credentials missing; cannot finalize")
        return 0

    query = urllib.parse.urlencode({"select": "id,status", "id": f"eq.{run_id}", "limit": "1"})
    try:
        rows = request_json("GET", f"{base}/rest/v1/pipeline_runs?{query}", key)
        if not rows:
            print(f"batch-finalize: pipeline run {run_id} absent; leaving batch untouched")
            return 0
        status = str(rows[0].get("status") or "")
        if status in SUCCESS:
            target = "completed"
        elif status in FAILURE:
            target = "failed"
        else:
            print(f"batch-finalize: pipeline run {run_id} is non-terminal ({status}); leaving batch untouched")
            return 0

        q = urllib.parse.urlencode({
            "batch_id": f"eq.{batch_id}",
            "pipeline_run_id": f"eq.{run_id}",
            "state": "eq.running",
        })
        changed = request_json("PATCH", f"{base}/rest/v1/upload_batches?{q}", key, {
            "state": target,
        })
        if changed:
            print(f"batch-finalize: {batch_id} -> {target} for pipeline {run_id}")
        else:
            print(f"batch-finalize: no matching running batch to update for {run_id}")
    except (urllib.error.URLError, ValueError) as exc:
        print(f"batch-finalize: best-effort finalization failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
