#!/usr/bin/env python3
"""Independent E2E harness for the Operator "Clean Video Storage" feature.

Everything here talks to storage/DB directly (boto3 + Supabase REST), *not* through the
TypeScript cleanup service, so it can independently prove what the service did.

Subcommands
  seed        create clearly tagged test video objects, non-video "keep" objects, an incomplete
              multipart upload, Supabase reels/athlete_photos objects and active DB references
  state       print/store an independent inventory + active-DB snapshot
  assert-populated  the seeded objects/rows exist and are active
  assert-clean      video scope is empty, keep-set intact, active refs neutralized, baselines equal
  isolation         upload a NEW test batch through the real operator API and prove that only the
                    new batch is selectable input (no old key/id/path anywhere in input selection)
  api-security      unauthenticated / wrong-secret / injection probes against the cleanup endpoint

Secrets come from the environment only and are never printed or written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".mxf")
PREFIXES = ["raw/", "processed/", "review/", "approved/", "pending_payment/", "pending_uploads/", "previews/"]
PROTECTED_PREFIX = "metadata/"
ACTIVE_UPLOAD = ("uploading", "paused", "completing", "verified", "superseded", "size_mismatch")
ACTIVE_BATCH = ("collecting", "uploading", "ready", "running")
ACTIVE_REEDIT = ("pending", "queued", "qa_blocked")
BASELINE_TABLES = ["athlete_profiles", "pricing", "payments", "purchases", "drafts", "pipeline_runs", "delivery_runs"]


def env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def r2():
    import boto3
    from botocore.config import Config
    account = env("R2_ACCOUNT_ID")
    endpoint = env("R2_ENDPOINT_URL") or f"https://{account}.r2.cloudflarestorage.com"
    client = boto3.client(
        "s3", endpoint_url=endpoint, region_name="auto",
        aws_access_key_id=env("R2_ACCESS_KEY_ID", "ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY", "SECRET_KEY_ID"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )
    return client, env("R2_BUCKET") or "sportreel"


def sb():
    from supabase import create_client
    return create_client(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"))


def is_video(name: str) -> bool:
    return name.lower().endswith(VIDEO_EXTS)


def in_scope(key: str) -> bool:
    return is_video(key) and key.startswith(tuple(PREFIXES)) and ".." not in key


def sb_list(client, bucket: str, path: str = "") -> list[str]:
    out: list[str] = []
    offset = 0
    while True:
        try:
            page = client.storage.from_(bucket).list(path, {"limit": 100, "offset": offset})
        except Exception as e:  # bucket missing => empty
            if "not found" in str(e).lower():
                return out
            raise
        if not page:
            break
        for e in page:
            full = f"{path}/{e['name']}" if path else e["name"]
            if e.get("id") is None:
                out.extend(sb_list(client, bucket, full))
            else:
                out.append(full)
        if len(page) < 100:
            break
        offset += 100
    return out


def count(client, table: str) -> int:
    return client.table(table).select("*", count="exact", head=True).execute().count or 0


def count_in(client, table: str, col: str, values: tuple[str, ...]) -> int:
    return client.table(table).select("*", count="exact", head=True).in_(col, list(values)).execute().count or 0


def snapshot(tag: str | None = None) -> dict[str, Any]:
    client, bucket = r2()
    db = sb()
    keys: list[str] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys += [o["Key"] for o in page.get("Contents", []) if not o["Key"].endswith("/")]
    multipart = []
    for page in client.get_paginator("list_multipart_uploads").paginate(Bucket=bucket):
        multipart += [(u["Key"], u["UploadId"]) for u in page.get("Uploads", [])]
    reels = sb_list(db, "reels")
    photos = sb_list(db, "athlete_photos")
    try:
        users = len(db.auth.admin.list_users(per_page=1000))
    except Exception:
        users = None
    snap = {
        "r2_video_in_scope": sorted(k for k in keys if in_scope(k) and not k.startswith(PROTECTED_PREFIX)),
        "r2_video_by_prefix": {p: sum(1 for k in keys if in_scope(k) and k.startswith(p)) for p in PREFIXES},
        "r2_unscoped_video": sorted(k for k in keys if is_video(k) and not in_scope(k) and not k.startswith(PROTECTED_PREFIX)),
        "r2_non_video": sorted(k for k in keys if not is_video(k)),
        "r2_metadata_video": sorted(k for k in keys if k.startswith(PROTECTED_PREFIX) and is_video(k)),
        "r2_multipart": sorted(f"{k}#{u}" for k, u in multipart if not k.startswith(PROTECTED_PREFIX)),
        "reels_video": sorted(p for p in reels if is_video(p)),
        "reels_non_video": sorted(p for p in reels if not is_video(p)),
        "athlete_photos": sorted(photos),
        "db_active": {
            "source_uploads": count_in(db, "source_uploads", "status", ACTIVE_UPLOAD),
            "upload_batches": count_in(db, "upload_batches", "state", ACTIVE_BATCH),
            "reprocess_requests": count_in(db, "reprocess_requests", "status", ACTIVE_REEDIT),
            "reels_rows": count_in(db, "reels", "status", ("published", "viewed")),
        },
        "baseline": {t: count(db, t) for t in BASELINE_TABLES} | {"auth_users": users},
    }
    if tag:
        snap["tag_r2_video"] = [k for k in snap["r2_video_in_scope"] if f"e2e_clean_{tag}" in k]
    return snap


def cmd_seed(args) -> int:
    tag = args.tag or uuid.uuid4().hex[:10]
    client, bucket = r2()
    db = sb()
    m: dict[str, Any] = {"tag": tag, "r2_video": [], "r2_keep": [], "multipart": None}
    payload = b"e2e-cleanup-test-video-" + tag.encode()
    for i, prefix in enumerate(PREFIXES):
        key = f"{prefix}e2e_clean_{tag}/old_{i}.mp4"
        client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="video/mp4")
        m["r2_video"].append(key)
    key = f"raw/e2e_clean_{tag}/old_upper.MOV"
    client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="video/quicktime")
    m["r2_video"].append(key)
    for key in (f"raw/e2e_clean_{tag}/notes.txt", f"previews/e2e_clean_{tag}/thumb.jpg",
                f"metadata/e2e_clean_{tag}/keep.json", f"config/e2e_clean_{tag}/x.json",
                f"assets/e2e_clean_{tag}/unscoped.mp4", f"metadata/e2e_clean_{tag}/protected.mp4"):
        client.put_object(Bucket=bucket, Key=key, Body=b"keep-me-" + tag.encode())
        m["r2_keep"].append(key)
    mp_key = f"raw/e2e_clean_{tag}/incomplete.mp4"
    up = client.create_multipart_upload(Bucket=bucket, Key=mp_key, ContentType="video/mp4")
    client.upload_part(Bucket=bucket, Key=mp_key, UploadId=up["UploadId"], PartNumber=1, Body=b"x" * (5 * 1024 * 1024))
    m["multipart"] = {"key": mp_key, "upload_id": up["UploadId"]}

    db.storage.from_("reels").upload(f"e2e_clean_{tag}/old.mp4", payload, {"content-type": "video/mp4"})
    db.storage.from_("reels").upload(f"e2e_clean_{tag}/thumb.jpg", b"keep", {"content-type": "image/jpeg"})
    db.storage.from_("athlete_photos").upload(f"e2e_clean_{tag}/photo.jpg", b"photo", {"content-type": "image/jpeg"})
    m["reels_video"] = [f"e2e_clean_{tag}/old.mp4"]
    m["reels_keep"] = [f"e2e_clean_{tag}/thumb.jpg"]
    m["athlete_photo"] = f"e2e_clean_{tag}/photo.jpg"

    batch_id = f"e2e_clean_old_{tag}"
    db.rpc("register_upload_batch", {"p_batch_id": batch_id, "p_additional_file_count": 1, "p_source_kind": "api"}).execute()
    old_key = m["r2_video"][0]
    row = db.table("source_uploads").insert({
        "batch_id": batch_id, "storage_key": old_key, "source_filename": "old_0.mp4", "mime_type": "video/mp4",
        "source_size_bytes": len(payload),
    }).execute().data[0]
    db.rpc("verify_source_upload", {"p_storage_key": old_key, "p_verified_size_bytes": len(payload)}).execute()
    reel = db.table("reels").insert({"sport": "e2e", "status": "published", "token": f"e2e_clean_{tag}",
                                     "storage_path": m["reels_video"][0], "source_video": old_key}).execute().data[0]
    reedit = db.table("reprocess_requests").insert({"draft_name": f"e2e_clean_{tag}.mp4", "status": "pending",
                                                    "notes": "e2e cleanup test"}).execute().data[0]
    m["db"] = {"batch_id": batch_id, "source_upload_id": row["id"], "reel_id": reel["id"], "reprocess_id": reedit["id"]}
    Path(args.manifest).write_text(json.dumps(m, indent=2))
    print(json.dumps({"seeded_tag": tag, "r2_video": len(m["r2_video"]), "keep": len(m["r2_keep"])}))
    return 0


def check(cond: bool, msg: str, errors: list[str]) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        errors.append(msg)


def cmd_state(args) -> int:
    snap = snapshot()
    if args.out:
        Path(args.out).write_text(json.dumps(snap, indent=2))
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in snap.items()}
    print(json.dumps(summary, indent=2))
    return 0


def cmd_assert_populated(args) -> int:
    m = json.loads(Path(args.manifest).read_text())
    snap = snapshot(m["tag"])
    db = sb()
    errors: list[str] = []
    for k in m["r2_video"]:
        check(k in snap["r2_video_in_scope"], f"seeded R2 video present: {k}", errors)
    check(any(m["multipart"]["key"] in x for x in snap["r2_multipart"]), "incomplete multipart present", errors)
    check(all(p in snap["reels_video"] for p in m["reels_video"]), "seeded reels video present", errors)
    check(m["athlete_photo"] in snap["athlete_photos"], "seeded athlete photo present", errors)
    for k in m["r2_keep"] + [f"raw/e2e_clean_{m['tag']}/notes.txt"]:
        check(k in snap["r2_non_video"] + snap["r2_unscoped_video"] + snap["r2_metadata_video"], f"keep object present: {k}", errors)
    d = m["db"]
    su = db.table("source_uploads").select("status").eq("id", d["source_upload_id"]).single().execute().data
    check(su["status"] in ACTIVE_UPLOAD, f"source_upload active ({su['status']})", errors)
    check(db.table("reels").select("status").eq("id", d["reel_id"]).single().execute().data["status"] == "published", "reel row published", errors)
    check(db.table("reprocess_requests").select("status").eq("id", d["reprocess_id"]).single().execute().data["status"] == "pending", "reprocess pending", errors)
    Path(args.baseline).write_text(json.dumps(snap, indent=2))
    return 1 if errors else 0


def cmd_assert_clean(args) -> int:
    m = json.loads(Path(args.manifest).read_text())
    before = json.loads(Path(args.baseline).read_text())
    snap = snapshot(m["tag"])
    db = sb()
    errors: list[str] = []
    check(snap["r2_video_in_scope"] == [], f"0 R2 in-scope video objects (found {len(snap['r2_video_in_scope'])})", errors)
    check(snap["r2_multipart"] == [], "0 incomplete multipart uploads", errors)
    check(snap["reels_video"] == [], "0 Supabase reels videos", errors)
    for k in m["r2_video"]:
        check(k not in snap["r2_video_in_scope"], f"seeded video removed: {k}", errors)
    for k in m["r2_keep"] + [f"raw/e2e_clean_{m['tag']}/notes.txt"]:
        check(k in snap["r2_non_video"] + snap["r2_unscoped_video"] + snap["r2_metadata_video"], f"keep object intact: {k}", errors)
    check(all(k in snap["reels_non_video"] for k in m["reels_keep"]), "reels non-video intact", errors)
    check(set(before["athlete_photos"]) <= set(snap["athlete_photos"]) and m["athlete_photo"] in snap["athlete_photos"], "athlete photos intact", errors)
    check(set(before["r2_non_video"]) <= set(snap["r2_non_video"]), "all pre-existing non-video R2 objects intact", errors)
    check(snap["db_active"] == {"source_uploads": 0, "upload_batches": 0, "reprocess_requests": 0, "reels_rows": 0},
          f"active DB references neutralized {snap['db_active']}", errors)
    d = m["db"]
    su = db.table("source_uploads").select("status,removed_at,verified_at").eq("id", d["source_upload_id"]).single().execute().data
    check(su["status"] == "aborted" and su["removed_at"] and su["verified_at"], "old source_upload aborted, audit fields kept", errors)
    check(db.table("reels").select("status").eq("id", d["reel_id"]).single().execute().data["status"] == "expired", "reel row expired (kept)", errors)
    check(db.table("reprocess_requests").select("status").eq("id", d["reprocess_id"]).single().execute().data["status"] == "cancelled", "reprocess cancelled (kept)", errors)
    for t, n in before["baseline"].items():
        after = snap["baseline"][t]
        if t == "pipeline_runs":  # live runs of other work may add rows; never fewer
            check(after >= n, f"baseline {t}: {n} -> {after} (not decreased)", errors)
        else:
            check(after == n, f"baseline {t} unchanged: {n} -> {after}", errors)
    Path(args.out).write_text(json.dumps(snap, indent=2))
    return 1 if errors else 0


def http(method: str, path: str, secret: str | None, body: Any = None, raw: bytes | None = None) -> tuple[int, Any, str]:
    url = os.environ["API_BASE"].rstrip("/") + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["x-operator-secret"] = secret
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None), text
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text), text
        except Exception:
            return e.code, None, text


def cmd_isolation(args) -> int:
    m = json.loads(Path(args.manifest).read_text())
    secret = env("OPERATOR_SECRET")
    db = sb()
    client, bucket = r2()
    errors: list[str] = []
    tag = m["tag"]
    batch_id = f"e2e_clean_new_{tag}"
    st, _, _ = http("POST", "/api/operator/upload/batch", secret, {"batch_id": batch_id, "additional_file_count": 2, "source_kind": "api"})
    check(st == 200, f"register new batch ({st})", errors)
    new_keys: list[str] = []
    for i in range(2):
        payload = f"e2e-new-video-{tag}-{i}".encode() * 10
        st, res, _ = http("POST", "/api/operator/upload", secret, {
            "client_upload_id": f"e2e_clean_new_{tag}_{i}_{uuid.uuid4().hex}"[:100], "filename": f"new_{i}.mp4",
            "mimeType": "video/mp4", "size": len(payload), "batch_id": batch_id})
        check(st == 200, f"upload init {i} ({st})", errors)
        if st != 200:
            continue
        put = urllib.request.Request(res["uploadUrl"], data=payload, method="PUT")
        urllib.request.urlopen(put, timeout=60).read()
        st, _, _ = http("POST", "/api/operator/upload/verify", secret, {"storage_key": res["storage_key"]})
        check(st == 200, f"verify upload {i} ({st})", errors)
        new_keys.append(res["storage_key"])
    ready = db.rpc("assert_upload_batch_ready", {"p_batch_id": batch_id}).execute().data
    manifest_keys = sorted(x["storage_key"] for x in ready["input_manifest"])
    check(manifest_keys == sorted(new_keys) and len(new_keys) == 2, "batch input manifest == exactly the 2 new keys", errors)
    # Every place the next run selects input from:
    raw_keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="raw/"):
        raw_keys += [o["Key"] for o in page.get("Contents", []) if is_video(o["Key"])]
    check(sorted(raw_keys) == sorted(new_keys), f"raw/ video listing == new keys only (found {len(raw_keys)})", errors)
    active_rows = db.table("source_uploads").select("id,storage_key,batch_id,status").in_("status", list(ACTIVE_UPLOAD)).execute().data
    check(sorted(r["storage_key"] for r in active_rows) == sorted(new_keys), "active source_uploads == new keys only", errors)
    active_batches = db.table("upload_batches").select("batch_id").in_("state", list(ACTIVE_BATCH)).execute().data
    check([b["batch_id"] for b in active_batches] == [batch_id], "active upload_batches == new batch only", errors)
    haystack = json.dumps([ready, active_rows, active_batches, raw_keys])
    old_tokens = m["r2_video"] + [m["db"]["batch_id"], m["db"]["source_upload_id"], m["db"]["reel_id"], m["db"]["reprocess_id"]] + m["reels_video"]
    leaked = [t for t in old_tokens if t in haystack]
    check(not leaked, f"no old key/id/path in new batch input or processing state (leaked={leaked})", errors)
    Path(args.out).write_text(json.dumps({"new_batch": batch_id, "new_keys": new_keys, "input_manifest": ready["input_manifest"], "raw_video_keys": raw_keys}, indent=2))
    return 1 if errors else 0


def cmd_api_security(args) -> int:
    secret = env("OPERATOR_SECRET")
    errors: list[str] = []
    path = "/api/operator/storage/clean"
    for label, s in (("missing", None), ("wrong", secret[:-1] + "X"), ("empty", ""), ("prefix", secret[:6])):
        for method in ("GET", "POST"):
            st, _, text = http(method, path, s, {"confirmation": "DELETE_OLD_VIDEOS"} if method == "POST" else None)
            check(st == 401, f"{method} {label} credential -> 401 (got {st})", errors)
            check(secret not in text, f"{method} {label}: no secret in response", errors)
    # authorized but malformed / injection: must be rejected before any deletion
    inj = [
        ("no confirmation", {}, 400), ("wrong confirmation", {"confirmation": "yes"}, 400),
        ("bad run_id", {"run_id": "../../etc/passwd"}, 400), ("bucket injection ignored/rejected", {"confirmation": "nope", "bucket": "athlete_photos", "key": "x"}, 400),
        ("key injection via run_id", {"run_id": "raw/foo.mp4"}, 400),
    ]
    for label, body, want in inj:
        st, _, text = http("POST", path, secret, body)
        check(st == want, f"{label} -> {want} (got {st})", errors)
        check(secret not in text, f"{label}: no secret in response", errors)
    st, _, _ = http("POST", path, secret, raw=b"{")
    check(st == 400, f"malformed JSON -> 400 (got {st})", errors)
    st, _, _ = http("DELETE", path, secret)
    check(st == 405, f"unsupported DELETE -> 405 (got {st})", errors)
    st, body, text = http("GET", path, secret)
    check(st == 200, f"authorized GET preview -> 200 (got {st})", errors)
    for i, needle in enumerate(("SECRET", "service_role", "R2_SECRET", "OPERATOR_SECRET", secret)):
        # label by index only: never put (part of) a credential into log text
        check(needle not in text, f"preview response free of sensitive marker #{i}", errors)
    return 1 if errors else 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--tag"); s.add_argument("--manifest", required=True); s.set_defaults(fn=cmd_seed)
    s = sub.add_parser("state"); s.add_argument("--out"); s.set_defaults(fn=cmd_state)
    s = sub.add_parser("assert-populated"); s.add_argument("--manifest", required=True); s.add_argument("--baseline", required=True); s.set_defaults(fn=cmd_assert_populated)
    s = sub.add_parser("assert-clean"); s.add_argument("--manifest", required=True); s.add_argument("--baseline", required=True); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_assert_clean)
    s = sub.add_parser("isolation"); s.add_argument("--manifest", required=True); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_isolation)
    s = sub.add_parser("api-security"); s.set_defaults(fn=cmd_api_security)
    args = p.parse_args()
    t = time.time()
    code = args.fn(args)
    print(f"{args.cmd}: {'PASS' if code == 0 else 'FAIL'} ({time.time() - t:.1f}s)")
    return code


if __name__ == "__main__":
    sys.exit(main())
