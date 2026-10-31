#!/usr/bin/env python3
"""RAW inventory and safe recovery planner for original source videos in R2.

READ-ONLY by default. Three subcommands:

  inventory   List R2 (read-only) and join it with the durable source_uploads records; classify every
              tracked source: raw_ok / raw_alt_key / processed_only / elsewhere / missing. Writes a JSON report.
  plan        Same, and also verify SHA-256 of every source that would be copied; writes a dry-run plan.
              Nothing is changed.
  apply       Execute a previously written plan: COPY only (never move, never delete, never overwrite).
              Requires --plan FILE and --confirm RESTORE_RAW_COPIES. Re-validates every action first.

Rules (enforced here and by tests/scripts/test_raw_recovery.py):
  * copy only: no move, no delete; an existing destination is never overwritten;
  * a processed/ object is a candidate only if its SHA-256 equals the durable record's content_sha256
    (size alone never proves identity; a record without SHA-256 is reported "unverifiable", not copied);
  * nothing is assumed to be the source: an object in processed/ is just a candidate until proven;
  * a source that cannot be proven is reported MISSING, never "reconstructed".

Environment (read at run time, never printed): R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY /
R2_BUCKET (or R2_ENDPOINT_URL) for storage, and either --uploads-json FILE or SUPABASE_URL +
SUPABASE_SERVICE_ROLE_KEY (a read-only SELECT on source_uploads) for the durable records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIRM = "RESTORE_RAW_COPIES"
PLAN_FORMAT = "raw-recovery-plan/v1"
TRACKED_STATUSES = ("verified", "superseded")


def _r2():
    from integrations import r2_storage
    return r2_storage


def load_uploads(path: str | None) -> list[dict[str, Any]]:
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data["rows"] if isinstance(data, dict) else data
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/source_uploads"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    query = urllib.parse.urlencode({
        "select": "id,storage_key,source_filename,status,source_size_bytes,verified_size_bytes,content_sha256,verified_at,removed_at,batch_id,created_at",
        "order": "created_at.asc", "limit": "5000"})
    request = urllib.request.Request(f"{base}?{query}", headers={"apikey": key, "Authorization": f"Bearer {key}"})  # GET only
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https endpoint from env
        return json.loads(response.read())


def list_bucket(r2) -> list[dict[str, Any]]:
    out = []
    for prefix in ("raw/", "processed/", "review/", "approved/", "pending_payment/", "pending_uploads/", "previews/"):
        for obj in r2.list_objects(prefix):
            if r2._is_video_key(obj["Key"]):
                out.append({"key": obj["Key"], "size": int(obj["Size"]), "etag": obj.get("ETag"), "prefix": prefix})
    return out


def _name(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def classify(row: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Where are this source's bytes? Looks at the exact key first, then every alternative location."""
    key = row["storage_key"]
    size = row.get("verified_size_bytes") or row.get("source_size_bytes")
    exact = next((o for o in objects if o["key"] == key), None)
    same = [o for o in objects if _name(o["key"]) == _name(key) and (size is None or o["size"] == size)]
    in_raw = [o for o in same if o["prefix"] == "raw/"]
    if exact and exact["prefix"] == "raw/" and (size is None or exact["size"] == size):
        return {"state": "raw_ok", "where": exact["key"]}
    if in_raw:
        return {"state": "raw_alt_key", "where": in_raw[0]["key"]}
    processed = [o for o in same if o["prefix"] == "processed/"]
    if processed:
        return {"state": "processed_only", "where": processed[0]["key"], "size": processed[0]["size"]}
    if same:
        return {"state": "elsewhere", "where": same[0]["key"], "note": "only a derived-output location holds this name; not treated as the source"}
    return {"state": "missing"}


def sha256_of_object(r2, key: str) -> str:
    body = r2._client().get_object(Bucket=r2._bucket(), Key=key)["Body"]
    digest = hashlib.sha256()
    try:
        for chunk in body.iter_chunks(chunk_size=8 * 1024 * 1024):
            digest.update(chunk)
    finally:
        body.close()
    return digest.hexdigest()


def build_report(rows: list[dict[str, Any]], objects: list[dict[str, Any]], *, verify_sha: bool, r2=None) -> dict[str, Any]:
    tracked = [r for r in rows if r.get("status") in TRACKED_STATUSES]
    entries, actions = [], []
    raw_names = {_name(o["key"]): o for o in objects if o["prefix"] == "raw/"}
    for row in tracked:
        c = classify(row, objects)
        entry = {"upload_id": row["id"], "status": row["status"], "storage_key": row["storage_key"],
                 "size": row.get("verified_size_bytes") or row.get("source_size_bytes"),
                 "sha256": row.get("content_sha256"), **c}
        if c["state"] == "processed_only":
            dest = f"raw/{_name(c['where'])}"
            if dest in {o["key"] for o in objects}:
                entry["state"], entry["note"] = "conflict", f"{dest} already exists with a different size; never overwritten"
            elif not row.get("content_sha256"):
                entry["state"], entry["note"] = "unverifiable", "no durable SHA-256 on record: size alone does not prove identity, not copied"
            elif verify_sha:
                actual = sha256_of_object(r2, c["where"])
                entry["verified_sha256"] = actual
                if actual != row["content_sha256"]:
                    entry["state"], entry["note"] = "sha_mismatch", "processed object bytes differ from the durable record; not copied"
                else:
                    actions.append({"action": "copy", "from": c["where"], "to": dest, "size": c["size"], "sha256": actual})
                    entry["planned_copy_to"] = dest
            else:
                entry["note"] = "SHA-256 not verified in this run (use `plan`)"
        entries.append(entry)
    aborted = [r for r in rows if r.get("status") == "aborted"]
    summary: dict[str, int] = {}
    for e in entries:
        summary[e["state"]] = summary.get(e["state"], 0) + 1
    return {
        "format": PLAN_FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "dry_run": True,
        "r2_video_objects_by_prefix": {p: sum(1 for o in objects if o["prefix"] == p) for p in sorted({o["prefix"] for o in objects})},
        "tracked_sources": len(entries), "summary": summary,
        "aborted_or_removed_records": {"count": len(aborted), "removed_marked": sum(1 for r in aborted if r.get("removed_at"))},
        "unmatched_raw_objects": sorted(k for k, o in raw_names.items() if not any(_name(e["storage_key"]) == k for e in entries)),
        "entries": entries, "actions": actions,
        "rules": ["copy only", "never overwrite", "never delete or move", "SHA-256 must match the durable record"],
    }


def apply_plan(plan: dict[str, Any], r2) -> dict[str, Any]:
    """Re-validate every action against live storage, then COPY. Aborts before the first copy on any doubt."""
    if plan.get("format") != PLAN_FORMAT:
        raise SystemExit("not a raw-recovery plan")
    todo = plan["actions"]
    for a in todo:
        if a["action"] != "copy" or not a["to"].startswith("raw/") or not a["from"].startswith("processed/"):
            raise SystemExit(f"refusing unexpected action: {a}")
        if r2._head(a["from"]) is None:
            raise SystemExit(f"source vanished: {a['from']}; nothing was changed")
        if r2._head(a["to"]) is not None:
            raise SystemExit(f"destination exists: {a['to']}; refusing to overwrite; nothing was changed")
        if sha256_of_object(r2, a["from"]) != a["sha256"]:
            raise SystemExit(f"source bytes changed since the plan: {a['from']}; nothing was changed")
    done = []
    for a in todo:
        outcome = r2.copy_object_verified(a["from"], a["to"])           # never overwrites, verifies identical bytes
        if sha256_of_object(r2, a["to"]) != a["sha256"]:
            raise SystemExit(f"copy verification failed for {a['to']}: stopping (the source was not touched)")
        done.append({**a, "outcome": outcome})
    return {"applied": done, "deleted": 0, "moved": 0}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("inventory", "plan", "apply"))
    ap.add_argument("--uploads-json", help="durable source_uploads records exported as JSON (otherwise read via Supabase REST)")
    ap.add_argument("--out", default="raw-recovery-report.json")
    ap.add_argument("--plan", help="plan file produced by `plan` (apply only)")
    ap.add_argument("--confirm", help=f"must be {CONFIRM} (apply only)")
    args = ap.parse_args(argv)
    r2 = _r2()
    if args.command == "apply":
        if args.confirm != CONFIRM or not args.plan:
            raise SystemExit(f"apply requires --plan FILE and --confirm {CONFIRM}; nothing was changed")
        result = apply_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")), r2)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({"applied": len(result["applied"]), "deleted": 0, "moved": 0}))
        return 0
    report = build_report(load_uploads(args.uploads_json), list_bucket(r2), verify_sha=args.command == "plan", r2=r2)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"tracked_sources": report["tracked_sources"], "summary": report["summary"],
                      "planned_copies": len(report["actions"]), "dry_run": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
