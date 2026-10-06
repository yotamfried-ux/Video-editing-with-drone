#!/usr/bin/env python3
"""Reconcile and verify the frozen R2 inputs of one durable upload batch.

Runs before any expensive pipeline work.  The frozen manifest is the only
authority: inputs that a previous attempt moved raw/ -> processed/ are restored
(exactly those objects, exactly that batch), then raw/<batch>/ is verified
against the manifest.  Fails closed on any missing/mismatched/unexpected input.

Phases
  run          (default) workflow phase: manifest comes from the pipeline run's
               frozen ``input_files`` (SPORTREEL_INPUT_MANIFEST_B64) and the
               batch must be locked ``running`` for this PIPELINE_RUN_ID.
  predispatch  operator preflight: batch must be ``ready`` and unlocked; the
               manifest comes from the same ``assert_upload_batch_ready`` gate
               the Run Pipeline button uses.  Combine with --audit to stay
               read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.r2_batch_restore import (  # noqa: E402
    FrozenInputError,
    R2Store,
    load_manifest_from_env,
    parse_manifest,
    reconcile_frozen_inputs,
    safe_batch_id,
)


def _supabase(method: str, path: str, body: dict | None = None):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    request = urllib.request.Request(
        f"{base}/rest/v1/{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode() or "null")


def _batch_row(batch: str) -> dict:
    rows = _supabase(
        "GET",
        "upload_batches?" + urllib.parse.urlencode({"batch_id": f"eq.{batch}", "select": "*", "limit": "1"}),
    )
    if not rows:
        raise FrozenInputError(f"upload batch {batch} does not exist")
    return rows[0]


def _db_hashes(manifest: list[dict]) -> dict[str, str]:
    ids = [str(m["upload_id"]) for m in manifest if m.get("upload_id")]
    if len(ids) != len(manifest):
        raise FrozenInputError("manifest entries lack upload ids; cannot resolve content identities")
    rows = _supabase(
        "GET",
        "source_uploads?" + urllib.parse.urlencode(
            {"id": f"in.({','.join(ids)})", "select": "id,storage_key,content_sha256,status,removed_at"}
        ),
    )
    by_id = {r["id"]: r for r in rows}
    out: dict[str, str] = {}
    for item in manifest:
        row = by_id.get(str(item["upload_id"]))
        if row is None or row.get("removed_at") or row.get("status") != "verified":
            raise FrozenInputError(f"manifest upload {item['upload_id']} is not an active verified source")
        if row["storage_key"] != item["storage_key"]:
            raise FrozenInputError(f"manifest upload {item['upload_id']} storage key differs from its row")
        if row.get("content_sha256"):
            out[row["storage_key"]] = row["content_sha256"]
    return out


def _check_eligibility(row: dict, manifest: list[dict], *, phase: str, run_id: str) -> None:
    if len(manifest) != int(row["expected_file_count"]):
        raise FrozenInputError(
            f"manifest has {len(manifest)} entries but batch expects {row['expected_file_count']}"
        )
    if phase == "run":
        if row["state"] != "running" or str(row.get("pipeline_run_id") or "") != run_id:
            raise FrozenInputError(
                f"batch is not locked to this run: state={row['state']} run={row.get('pipeline_run_id')}"
            )
    else:
        if row["state"] != "ready" or row.get("pipeline_run_id") or row.get("locked_at"):
            raise FrozenInputError(
                f"batch is not dispatchable: state={row['state']} run={row.get('pipeline_run_id')} "
                f"locked_at={row.get('locked_at')}"
            )
    db_keys = sorted(str(m.get("storage_key")) for m in (row.get("input_manifest") or []))
    if db_keys != sorted(str(m.get("storage_key") or m.get("key")) for m in manifest):
        raise FrozenInputError("frozen manifest differs from the batch's durable input_manifest")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", choices=["run", "predispatch"], default="run")
    parser.add_argument("--audit", action="store_true", help="read-only: never restore")
    parser.add_argument("--verify-sha256", action="store_true", help="stream every object and compare SHA-256")
    parser.add_argument("--batch-id", default=os.getenv("RAW_BATCH_ID", ""))
    args = parser.parse_args()

    backend = (os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive")
    run_id = os.getenv("PIPELINE_RUN_ID", "").strip()
    batch = safe_batch_id(args.batch_id)
    if backend != "r2":
        print(f"frozen-input preflight skipped: STORAGE_BACKEND={backend}")
        return 0
    if not batch:
        if run_id or args.phase == "predispatch":
            print("::error::tracked R2 pipeline run has no explicit RAW_BATCH_ID", file=sys.stderr)
            return 2
        print("frozen-input preflight skipped: untracked legacy run without a batch id")
        return 0

    try:
        if args.phase == "predispatch":
            manifest = _supabase_rpc_assert_ready(batch)["input_manifest"]
            row = _batch_row(batch)
        else:
            row = _batch_row(batch)
            if not run_id:
                raise FrozenInputError("PIPELINE_RUN_ID is required for the run phase")
            manifest = load_manifest_from_env()
        parse_manifest(manifest, batch)
        _check_eligibility(row, manifest, phase=args.phase, run_id=run_id)
        expected = _db_hashes(manifest) if args.verify_sha256 else None
        report = reconcile_frozen_inputs(
            R2Store(), manifest, batch,
            restore=not args.audit,
            verify_sha256=args.verify_sha256,
            expected_sha256=expected,
        )
    except FrozenInputError as exc:
        print(f"::error::frozen-input preflight FAILED: {exc}", file=sys.stderr)
        return 1

    for item in report.entries:
        print(f"  {item.state:<10} {item.filename}  expected={item.expected_size} raw={item.raw_size} processed={item.processed_size}")
    print("frozen-input preflight OK: " + json.dumps(report.summary()))
    return 0


def _supabase_rpc_assert_ready(batch: str) -> dict:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    request = urllib.request.Request(
        f"{base}/rest/v1/rpc/assert_upload_batch_ready",
        data=json.dumps({"p_batch_id": batch}).encode(),
        method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise FrozenInputError(f"assert_upload_batch_ready rejected {batch}: {exc.read().decode()[:300]}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
