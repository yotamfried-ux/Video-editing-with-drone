#!/usr/bin/env python3
"""Independent evidence for Android background-upload qualification.

Maestro/adb prove what the device did. This tool proves what the backend and R2
recorded, without trusting any UI text, plus parses device-side durable state,
the part log and the foreground notification. Pure check functions are unit
tested (test_background_upload_evidence.py); the CLI wires them to Supabase REST,
the production operator API and R2. Secrets come from the environment only and are
never written to evidence files.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

PART_EVENT = re.compile(r"\b(part_put|part_ack)\s+(\S+)\s+(\d+)/(\d+)")
RECONCILE_EVENT = re.compile(r"\breconcile\s+(\S+)\s+server_parts=\[([^\]]*)\]")
ROW_COLUMNS = (
    "id,client_upload_id,batch_id,storage_key,source_filename,status,upload_protocol,source_size_bytes,"
    "verified_size_bytes,expected_part_count,completed_part_count,local_cleanup_status,verified_at,created_at"
)


# ---------- pure checks ----------

def analyze_part_log(lines: list[str]) -> dict[str, Any]:
    """An acknowledged (server-recorded) part must never be PUT again."""
    acked: dict[str, set[int]] = {}
    puts: dict[str, dict[int, int]] = {}
    resent: list[tuple[str, int]] = []
    reconciles = 0
    for line in lines:
        m = PART_EVENT.search(line)
        if m:
            kind, upload, num = m.group(1), m.group(2), int(m.group(3))
            if kind == "part_put":
                puts.setdefault(upload, {}).setdefault(num, 0)
                puts[upload][num] += 1
                if num in acked.get(upload, set()) and (upload, num) not in resent:
                    resent.append((upload, num))
            else:
                acked.setdefault(upload, set()).add(num)
            continue
        if RECONCILE_EVENT.search(line):
            reconciles += 1
    return {
        "acks": {u: sorted(n) for u, n in acked.items()},
        "puts": {u: {str(k): v for k, v in sorted(p.items())} for u, p in puts.items()},
        "resent_acknowledged": resent,
        "reconciles": reconciles,
    }


def check_final(
    rows: list[dict[str, Any]],
    parts_by_upload: dict[str, list[dict[str, Any]]],
    r2_heads: dict[str, int],
    r2_listing: dict[str, int],
    *,
    expected_count: int,
    batch_id: str,
    open_multipart_keys: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if len(rows) != expected_count:
        errors.append(f"expected exactly {expected_count} source_uploads rows in batch {batch_id}, found {len(rows)}")
    if len({r.get("storage_key") for r in rows}) != len(rows):
        errors.append("rows do not have distinct storage_key values (duplicate R2 object target)")
    if len({r.get("client_upload_id") for r in rows}) != len(rows):
        errors.append("rows do not have distinct client_upload_id values")
    for r in rows:
        label = r.get("id")
        if r.get("batch_id") != batch_id:
            errors.append(f"{label}: batch_id={r.get('batch_id')!r}, expected {batch_id!r}")
        if r.get("status") != "verified":
            errors.append(f"{label}: status={r.get('status')!r}, expected 'verified'")
        if r.get("upload_protocol") != "r2_multipart_v1":
            errors.append(f"{label}: upload_protocol={r.get('upload_protocol')!r}, expected 'r2_multipart_v1'")
        if r.get("local_cleanup_status") != "confirmed":
            errors.append(f"{label}: local_cleanup_status={r.get('local_cleanup_status')!r}, expected 'confirmed'")
        if r.get("verified_size_bytes") != r.get("source_size_bytes"):
            errors.append(f"{label}: verified_size_bytes={r.get('verified_size_bytes')!r} != source_size_bytes={r.get('source_size_bytes')!r}")
        nums = [p.get("part_number") for p in parts_by_upload.get(label, [])]
        expected_parts = r.get("expected_part_count")
        if len(nums) != len(set(nums)) or sorted(set(nums)) != list(range(1, int(expected_parts or 0) + 1)):
            errors.append(f"{label}: part rows {sorted(nums)} are not exactly 1..{expected_parts} once each")
        key = r.get("storage_key")
        if key not in r2_heads:
            errors.append(f"{label}: R2 object missing for {key}")
        elif r2_heads[key] != r.get("source_size_bytes"):
            errors.append(f"{label}: R2 object size {r2_heads[key]} != source size {r.get('source_size_bytes')}")
    expected_keys = {r.get("storage_key") for r in rows}
    if set(r2_listing) != expected_keys or len(r2_listing) != expected_count:
        errors.append(f"R2 prefix raw/{batch_id}/ holds {sorted(r2_listing)}, expected exactly {sorted(expected_keys)}")
    if open_multipart_keys:
        errors.append(f"incomplete R2 multipart uploads still open for {sorted(open_multipart_keys)}")
    return errors


def check_gate_rejected(status: int, body: dict[str, Any]) -> list[str]:
    """Pipeline start must be refused by the verified-batch gate (409), creating no run."""
    errors: list[str] = []
    if status != 409:
        errors.append(f"pipeline start returned HTTP {status}, expected gate rejection 409")
    if body.get("pipeline_run_id"):
        errors.append("pipeline start created a run for an incomplete batch")
    return errors


def check_gate_ready(result: dict[str, Any], *, expected_count: int) -> list[str]:
    errors: list[str] = []
    if result.get("state") != "ready":
        errors.append(f"batch state={result.get('state')!r}, expected 'ready'")
    for field in ("expected_file_count", "actual_file_count", "verified_file_count"):
        if result.get(field) != expected_count:
            errors.append(f"{field}={result.get(field)!r}, expected {expected_count}")
    if result.get("cleanup_pending_count") != 0:
        errors.append(f"cleanup_pending_count={result.get('cleanup_pending_count')!r}, expected 0")
    if len(result.get("input_manifest") or []) != expected_count:
        errors.append("input_manifest does not list exactly the verified files")
    return errors


def parse_prefs_xml(text: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for node in ET.fromstring(text).iter("string"):
        try:
            value = json.loads(html.unescape(node.text or ""))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "localId" in value:
            jobs.append(value)
    return jobs


def durable_progress(jobs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "verified": sum(1 for j in jobs if j.get("status") == "VERIFIED"),
        "total": len(jobs),
        "acked_parts": sum(len(j.get("completedParts") or []) for j in jobs if j.get("status") != "VERIFIED"),
    }


def parse_upload_notification(dump: str) -> dict[str, Any] | None:
    m = re.search(r"android\.title=String \((SportReel — Uploading (\d+)/(\d+) videos)\)", dump)
    if not m:
        return None
    progress = re.search(r"android\.progress=int \((\d+)\)", dump)
    return {"title": m.group(1), "verified": int(m.group(2)), "total": int(m.group(3)),
            "progress": int(progress.group(1)) if progress else None}


# ---------- CLI plumbing (network) ----------

def _http(method: str, url: str, headers: dict[str, str], body: Any | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null") or {}
        except json.JSONDecodeError:
            return e.code, {"error": raw[:300].decode("utf-8", "replace")}


def _supabase(path: str, method: str = "GET", body: Any | None = None) -> tuple[int, Any]:
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    base = os.environ["SUPABASE_URL"].rstrip("/")
    return _http(method, f"{base}/rest/v1/{path}", {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=representation"}, body)


def _r2():
    import boto3
    from botocore.config import Config
    account = os.environ.get("R2_ACCOUNT_ID", "")
    endpoint = os.environ.get("R2_ENDPOINT_URL") or f"https://{account}.r2.cloudflarestorage.com"
    client = boto3.client("s3", endpoint_url=endpoint, region_name="auto",
                          aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                          config=Config(signature_version="s3v4", retries={"max_attempts": 5}))
    return client, os.environ.get("R2_BUCKET") or "sportreel"


def _write(path: str | None, payload: dict[str, Any]) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True, default=str)


def cmd_final(a: argparse.Namespace) -> int:
    q = urllib.parse.urlencode({"select": ROW_COLUMNS, "batch_id": f"eq.{a.batch_id}", "order": "created_at.asc"})
    status, rows = _supabase(f"source_uploads?{q}")
    if status != 200:
        raise SystemExit(f"Supabase source_uploads read failed with HTTP {status}")
    parts: dict[str, list[dict[str, Any]]] = {}
    if rows:
        ids = ",".join(r["id"] for r in rows)
        status, plist = _supabase(f"source_upload_parts?select=source_upload_id,part_number&source_upload_id=in.({ids})")
        if status != 200:
            raise SystemExit(f"Supabase source_upload_parts read failed with HTTP {status}")
        for p in plist:
            parts.setdefault(p["source_upload_id"], []).append(p)
    client, bucket = _r2()
    heads: dict[str, int] = {}
    for r in rows:
        try:
            heads[r["storage_key"]] = client.head_object(Bucket=bucket, Key=r["storage_key"])["ContentLength"]
        except Exception:
            pass
    listing: dict[str, int] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"raw/{a.batch_id}/"):
        for obj in page.get("Contents", []):
            listing[obj["Key"]] = obj["Size"]
    open_keys = [u["Key"] for u in client.list_multipart_uploads(Bucket=bucket, Prefix=f"raw/{a.batch_id}/").get("Uploads", [])]
    errors = check_final(rows, parts, heads, listing, expected_count=a.expected, batch_id=a.batch_id, open_multipart_keys=open_keys)
    _write(a.out, {
        "check": "final", "result": "PASS" if not errors else "FAIL", "failures": errors, "batch_id": a.batch_id,
        "counts": {"source_uploads_rows": len(rows), "distinct_storage_keys": len({r["storage_key"] for r in rows}),
                   "r2_objects_under_batch_prefix": len(listing), "open_multipart_uploads": len(open_keys)},
        "rows": rows, "parts_per_upload": {k: sorted(p["part_number"] for p in v) for k, v in parts.items()},
        "r2_listing": listing, "secret_values_recorded": False,
    })
    for e in errors:
        print(f"FINAL check failed: {e}", file=sys.stderr)
    print(f"final backend evidence: {'PASS' if not errors else 'FAIL'}")
    return 0 if not errors else 1


def cmd_gate_incomplete(a: argparse.Namespace) -> int:
    status, body = _http("POST", f"{a.api_base.rstrip('/')}/api/operator/pipeline/start",
                         {"x-operator-secret": os.environ["OPERATOR_SECRET"], "Content-Type": "application/json"}, {"batch_id": a.batch_id})
    errors = check_gate_rejected(status, body or {})
    _write(a.out, {"check": "gate-incomplete", "result": "PASS" if not errors else "FAIL", "failures": errors, "http_status": status,
                   "error_message": (body or {}).get("error"), "batch_id": a.batch_id, "secret_values_recorded": False})
    for e in errors:
        print(f"gate-incomplete failed: {e}", file=sys.stderr)
    print(f"pipeline gate (incomplete batch): HTTP {status} -> {'PASS' if not errors else 'FAIL'}")
    return 0 if not errors else 1


def cmd_gate_ready(a: argparse.Namespace) -> int:
    # The route's own predicate (assert_upload_batch_ready) is evaluated read-only. A real pipeline dispatch is
    # intentionally not performed: it would launch a production pipeline run on test footage.
    status, body = _supabase("rpc/assert_upload_batch_ready", "POST", {"p_batch_id": a.batch_id})
    result = body[0] if isinstance(body, list) and body else body
    errors = [f"assert_upload_batch_ready HTTP {status}: {(result or {}).get('message') if isinstance(result, dict) else result}"] if status != 200 or not isinstance(result, dict) else check_gate_ready(result, expected_count=a.expected)
    _write(a.out, {"check": "gate-ready", "result": "PASS" if not errors else "FAIL", "failures": errors, "http_status": status,
                   "gate": {k: v for k, v in (result or {}).items() if k != "input_manifest"} if isinstance(result, dict) else None,
                   "input_manifest_files": len((result or {}).get("input_manifest") or []) if isinstance(result, dict) else None,
                   "batch_id": a.batch_id, "secret_values_recorded": False})
    for e in errors:
        print(f"gate-ready failed: {e}", file=sys.stderr)
    print(f"pipeline gate (full verified batch): {'PASS' if not errors else 'FAIL'}")
    return 0 if not errors else 1


def cmd_cancel_batch(a: argparse.Namespace) -> int:
    """Teardown only: stop a qualification batch from lingering as a 'ready' batch in production."""
    status, _ = _supabase(f"upload_batches?batch_id=eq.{urllib.parse.quote(a.batch_id)}&pipeline_run_id=is.null", "PATCH", {"state": "cancelled"})
    print(f"cancel-batch HTTP {status}")
    return 0


def cmd_part_log(a: argparse.Namespace) -> int:
    with open(a.logcat, encoding="utf-8", errors="replace") as fh:
        report = analyze_part_log(fh.read().splitlines())
    errors = [f"acknowledged part resent: upload {u} part {n}" for u, n in report["resent_acknowledged"]]
    _write(a.out, {"check": "part-log", "result": "PASS" if not errors else "FAIL", "failures": errors, **report})
    for e in errors:
        print(e, file=sys.stderr)
    print(f"multipart resume (no acknowledged part resent): {'PASS' if not errors else 'FAIL'}; reconciles={report['reconciles']}")
    return 0 if not errors else 1


def cmd_durable(a: argparse.Namespace) -> int:
    with open(a.prefs, encoding="utf-8", errors="replace") as fh:
        jobs = parse_prefs_xml(fh.read())
    out = {**durable_progress(jobs), "batch_ids": sorted({j.get("batchId") for j in jobs}), "statuses": {j["localId"]: j.get("status") for j in jobs}}
    print(json.dumps(out))
    return 0


def cmd_notification(a: argparse.Namespace) -> int:
    with open(a.dump, encoding="utf-8", errors="replace") as fh:
        parsed = parse_upload_notification(fh.read())
    print(json.dumps(parsed))
    return 0 if parsed else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("final"); f.add_argument("--batch-id", required=True); f.add_argument("--expected", type=int, required=True); f.add_argument("--out"); f.set_defaults(fn=cmd_final)
    g = sub.add_parser("gate-incomplete"); g.add_argument("--batch-id", required=True); g.add_argument("--api-base", required=True); g.add_argument("--out"); g.set_defaults(fn=cmd_gate_incomplete)
    r = sub.add_parser("gate-ready"); r.add_argument("--batch-id", required=True); r.add_argument("--expected", type=int, required=True); r.add_argument("--out"); r.set_defaults(fn=cmd_gate_ready)
    c = sub.add_parser("cancel-batch"); c.add_argument("--batch-id", required=True); c.set_defaults(fn=cmd_cancel_batch)
    l = sub.add_parser("part-log"); l.add_argument("--logcat", required=True); l.add_argument("--out"); l.set_defaults(fn=cmd_part_log)
    d = sub.add_parser("durable"); d.add_argument("--prefs", required=True); d.set_defaults(fn=cmd_durable)
    n = sub.add_parser("notification"); n.add_argument("--dump", required=True); n.set_defaults(fn=cmd_notification)
    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
