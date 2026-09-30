#!/usr/bin/env python3
"""Inventory / delete old SportReel *video* objects through each backend's own API.

R2      : integrations.r2_storage.list_objects / delete_object (video keys only) under every
          pipeline prefix; incomplete multipart uploads are inventoried and aborted via S3 API.
Supabase: Storage API (client.storage.from_('reels').remove) - never SQL on storage.objects.
Never touched: athlete_photos bucket, non-video objects, metadata/ prefix, DB rows, auth, config.

MODE=inventory (default) only lists. MODE=delete requires CONFIRM_DELETE_OLD_VIDEOS=DELETE_OLD_VIDEOS.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations import r2_storage  # noqa: E402

R2_PREFIXES = [
    r2_storage.RAW_PREFIX, r2_storage.PROCESSED_PREFIX, r2_storage.REVIEW_PREFIX,
    r2_storage.APPROVED_PREFIX, r2_storage.PENDING_PAYMENT_PREFIX,
    r2_storage.PENDING_UPLOADS_PREFIX, r2_storage.PREVIEWS_PREFIX,
]
SUPABASE_VIDEO_BUCKET = "reels"
CONFIRMATION = "DELETE_OLD_VIDEOS"
VIDEO_EXTS = r2_storage._VIDEO_EXTS


def r2_inventory() -> dict:
    client = r2_storage._client()
    bucket = r2_storage._bucket()
    out = {"bucket": bucket, "video": {}, "non_video": {}, "other_prefixes": {}, "multipart": []}
    for prefix in R2_PREFIXES:
        objs = r2_storage.list_objects(prefix)
        out["video"][prefix] = [(o["Key"], o["Size"]) for o in objs if r2_storage._is_video_key(o["Key"])]
        out["non_video"][prefix] = [(o["Key"], o["Size"]) for o in objs if not r2_storage._is_video_key(o["Key"])]
    # whole-bucket sweep so unknown prefixes holding videos are not missed
    known = tuple(R2_PREFIXES) + (r2_storage.METADATA_PREFIX,)
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for o in page.get("Contents", []):
            if not o["Key"].startswith(known):
                out["other_prefixes"][o["Key"]] = o["Size"]
    for page in client.get_paginator("list_multipart_uploads").paginate(Bucket=bucket):
        for u in page.get("Uploads", []):
            out["multipart"].append((u["Key"], u["UploadId"]))
    return out


def sb_client():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def sb_list_all(client, bucket: str, path: str = "") -> list[dict]:
    items = []
    offset = 0
    while True:
        page = client.storage.from_(bucket).list(path, {"limit": 100, "offset": offset})
        if not page:
            break
        for e in page:
            full = f"{path}/{e['name']}" if path else e["name"]
            if e.get("id") is None:  # folder
                items.extend(sb_list_all(client, bucket, full))
            else:
                items.append({"path": full, "size": (e.get("metadata") or {}).get("size")})
        if len(page) < 100:
            break
        offset += 100
    return items


def sb_inventory(client) -> dict:
    return {b: sb_list_all(client, b) for b in (SUPABASE_VIDEO_BUCKET, "athlete_photos")}


def summarize(r2: dict, sb: dict) -> dict:
    return {
        "r2_video_counts": {p: len(v) for p, v in r2["video"].items()},
        "r2_video_total": sum(len(v) for v in r2["video"].values()),
        "r2_video_bytes": sum(s for v in r2["video"].values() for _, s in v),
        "r2_non_video_counts": {p: len(v) for p, v in r2["non_video"].items()},
        "r2_other_prefix_objects": len(r2["other_prefixes"]),
        "r2_multipart_in_progress": len(r2["multipart"]),
        "supabase_reels_objects": len(sb[SUPABASE_VIDEO_BUCKET]),
        "supabase_athlete_photos_objects": len(sb["athlete_photos"]),
    }


EVIDENCE: dict = {}


def show(title: str, r2: dict, sb: dict) -> dict:
    print(f"\n===== {title} =====")
    for p, v in r2["video"].items():
        for k, s in v:
            print(f"R2 VIDEO  {k}  {s}")
    for p, v in r2["non_video"].items():
        for k, s in v:
            print(f"R2 non-video (kept)  {k}  {s}")
    for k, s in r2["other_prefixes"].items():
        print(f"R2 other-prefix object  {k}  {s}")
    for k, u in r2["multipart"]:
        print(f"R2 incomplete multipart  {k}  {u}")
    for b, items in sb.items():
        for i in items:
            print(f"SUPABASE {b}  {i['path']}  {i['size']}")
    summ = summarize(r2, sb)
    print(json.dumps(summ, indent=2))
    EVIDENCE[title] = {"summary": summ, "r2": r2, "supabase": sb}
    path = os.getenv("EVIDENCE_PATH")
    if path:
        Path(path).write_text(json.dumps(EVIDENCE, indent=2, default=str))
    return summ


def main() -> int:
    mode = os.getenv("MODE", "inventory").strip()
    sb_c = sb_client()
    before_r2, before_sb = r2_inventory(), sb_inventory(sb_c)
    before = show("INVENTORY BEFORE", before_r2, before_sb)
    if mode != "delete":
        return 0
    if os.getenv("CONFIRM_DELETE_OLD_VIDEOS") != CONFIRMATION:
        raise RuntimeError(f"CONFIRM_DELETE_OLD_VIDEOS must equal {CONFIRMATION}")

    deleted_r2 = 0
    for prefix, vids in before_r2["video"].items():
        for key, _ in vids:
            r2_storage.delete_object(key)
            deleted_r2 += 1
    client, bucket = r2_storage._client(), r2_storage._bucket()
    for key, upload_id in before_r2["multipart"]:
        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
    reel_paths = [i["path"] for i in before_sb[SUPABASE_VIDEO_BUCKET]
                  if Path(i["path"]).suffix.lower() in VIDEO_EXTS]
    for i in range(0, len(reel_paths), 50):
        sb_c.storage.from_(SUPABASE_VIDEO_BUCKET).remove(reel_paths[i:i + 50])
    print(f"\nDeleted: R2 videos={deleted_r2}, R2 multipart aborted={len(before_r2['multipart'])}, "
          f"Supabase reels={len(reel_paths)}")

    after = show("INVENTORY AFTER", r2_inventory(), sb_inventory(sb_c))
    ok = (after["r2_video_total"] == 0 and after["r2_multipart_in_progress"] == 0
          and after["supabase_reels_objects"] == 0
          and after["supabase_athlete_photos_objects"] == before["supabase_athlete_photos_objects"]
          and after["r2_non_video_counts"] == before["r2_non_video_counts"])
    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
