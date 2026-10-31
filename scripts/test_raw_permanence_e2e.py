#!/usr/bin/env python3
"""End-to-end test of PERMANENT RAW against a real S3 protocol server (moto).

Runs the project's real boto3 storage code (integrations.r2_storage), the real admission/marker hooks
(pipeline.r2_batch_scope), the real dedup gate and the real reset script (scripts/reset_and_rerun.py).
Nothing here touches production: the bucket lives in a local moto server and source-provenance rows come
from an in-memory stand-in for Supabase.

Guarantees proven (every original source video keeps its exact bytes, in raw/, forever):
  * A pipeline run reads raw/, writes drafts to review/, records a tiny marker under metadata/ and
    NEVER moves, copies, replaces or deletes the source. A second run finds nothing new.
  * Reset / rerun forgets the markers (and clears review/); it never deletes or moves a source.
  * Deduplication excludes a duplicate from a run but never deletes it.
  * No code path can delete or move an original: direct attempts raise ProtectedSourceError.
  * A legacy source that only exists under processed/ is COPIED to raw/ (processed/ copy is kept).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_HOOKED = ("get_new_videos", "download_video", "mark_as_processed", "requeue_video", "restore_processed_to_raw")
_ORIGINALS: dict = {}
BUCKET = "stage-folder-e2e"
PORT = 5599
BATCH = "batch_2026-10-03T12-19-52_e2e"


def _setup_environment() -> dict:
    tmp = tempfile.mkdtemp(prefix="stage-flow-")
    os.environ.update({
        "STORAGE_BACKEND": "r2", "R2_BUCKET": BUCKET, "R2_ENDPOINT_URL": f"http://127.0.0.1:{PORT}",
        "R2_ACCESS_KEY_ID": "test", "R2_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1",
        "TMP_DIR": tmp, "PROCESSED_IDS_FILE": os.path.join(tmp, "processed.json"),
        "R2_MAX_ATTEMPTS": "1", "R2_CONNECT_TIMEOUT_SECONDS": "3", "R2_READ_TIMEOUT_SECONDS": "10",
    })
    for name in ("RAW_BATCH_ID", "BATCH_ID", "SPORTREEL_INPUT_MANIFEST_JSON", "SPORTREEL_INPUT_MANIFEST_B64"):
        os.environ.pop(name, None)
    return {"tmp": tmp}


# In-memory stand-in for the Supabase source_uploads table.
UPLOADS: dict[str, dict] = {}


# sha256 -> (upload_id, storage_key) of the first upload of those exact bytes.
CANONICAL_BY_HASH: dict[str, tuple[str, str]] = {}


def _install_fake_source_uploads() -> None:
    module = types.ModuleType("integrations.source_uploads")
    module.get_source_upload = lambda key, client=None: UPLOADS.get(key)

    def resolve_exact_source_duplicate(upload_id, content_sha256, client=None):
        key = next(k for k, row in UPLOADS.items() if row["id"] == upload_id)
        first = CANONICAL_BY_HASH.setdefault(content_sha256, (upload_id, key))
        # The real RPC joins the canonical upload's CURRENT storage_key from its row.
        current = next(k for k, row in UPLOADS.items() if row["id"] == first[0])
        return {"canonical": {"upload_id": first[0], "storage_key": current}, "superseded": []}

    module.resolve_exact_source_duplicate = resolve_exact_source_duplicate
    def rekey_source_upload(old_key, new_key, client=None):
        row = UPLOADS.get(old_key)
        if old_key == new_key or row is None:
            return False
        if new_key in UPLOADS:
            raise RuntimeError(f"duplicate storage_key {new_key}")
        UPLOADS[new_key] = {**row, "storage_key": new_key}
        del UPLOADS[old_key]
        return True

    module.rekey_source_upload = rekey_source_upload
    module.mark_source_removed = lambda *a, **k: None
    module.mark_source_removal_error = lambda *a, **k: None
    sys.modules["integrations.source_uploads"] = module


class Bucket:
    def __init__(self) -> None:
        import boto3
        self.client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                                   aws_access_key_id="test", aws_secret_access_key="test",
                                   region_name="us-east-1")
        self.client.create_bucket(Bucket=BUCKET)

    def put(self, key: str, body: bytes) -> None:
        self.client.put_object(Bucket=BUCKET, Key=key, Body=body)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=BUCKET, Key=key)["Body"].read()

    def keys(self, prefix: str) -> list[str]:
        out: list[str] = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            out += [item["Key"] for item in page.get("Contents", [])]
        return sorted(out)

    def wipe(self) -> None:
        for key in self.keys(""):
            self.client.delete_object(Bucket=BUCKET, Key=key)


def video(index: int) -> bytes:
    return (f"video-{index:03d}-".encode() * 2000)


def seed_uploads(bucket: Bucket, count: int = 24, batch: str | None = BATCH, tag: str = "") -> dict[str, bytes]:
    """Legacy uploads sit in raw/<batch>/; current uploads are flat (raw/<file>)."""
    contents = {}
    for i in range(count):
        folder = f"raw/{batch}/" if batch else "raw/"
        key = f"{folder}{tag}2026-10-03T12-19-{i:02d}_DJI_{i:04d}.mp4"
        bucket.put(key, video(i + (5000 if tag else 0)))
        contents[key] = bucket.get(key)
        UPLOADS[key] = {
            "id": f"u-{hashlib.md5(key.encode()).hexdigest()[:8]}", "status": "verified", "storage_key": key,
            "verified_at": "2026-10-03T12:20:00+00:00", "verified_size_bytes": len(contents[key]),
        }
    return contents


def run_pipeline() -> list[str]:
    """What one pipeline run does to storage: admit, download, write a draft, mark processed."""
    import integrations.r2_storage as r2
    admitted = r2.get_new_videos()
    for item in admitted:
        local = r2.download_video(item["id"], os.path.basename(item["id"]))
        assert os.path.getsize(local) > 0
        draft = os.path.join(os.environ["TMP_DIR"], f"draft_{item['name']}")
        Path(draft).write_bytes(b"draft:" + item["name"].encode())
        r2.upload_draft(draft, f"draft_{item['name']}")
        r2.mark_as_processed(item["id"])
    return [item["id"] for item in admitted]


def reset(*, full_clean: bool = False) -> None:
    """The workflow's Reset step is its own process: the pipeline's runtime storage hooks are
    not installed there, so run the reset against the unhooked storage module."""
    import integrations.r2_storage as r2
    import reset_and_rerun
    hooked = {name: getattr(r2, name) for name in _HOOKED if name in _ORIGINALS}
    for name in hooked:
        setattr(r2, name, _ORIGINALS[name])
    try:
        _reset_unhooked(reset_and_rerun, full_clean)
    finally:
        for name, value in hooked.items():
            setattr(r2, name, value)


def _reset_unhooked(reset_and_rerun, full_clean: bool) -> None:
    args = argparse.Namespace(no_restore=False, dry_run=False, full_clean=full_clean,
                              keep_drafts=False, reset_only=True)
    assert reset_and_rerun._reset_r2(args) is True


def main() -> int:
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    env = _setup_environment()
    _install_fake_source_uploads()
    from moto.server import ThreadedMotoServer
    server = ThreadedMotoServer(port=PORT, verbose=False)
    server.start()
    failures: list[str] = []
    try:
        bucket = Bucket()
        import integrations.r2_storage as r2_module
        _ORIGINALS.update({name: getattr(r2_module, name) for name in _HOOKED})
        import pipeline.r2_batch_scope as scope
        scope.install()

        def check(name: str, condition: bool, detail: str = "") -> None:
            print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
            if not condition:
                failures.append(name)

        def etags(prefix: str) -> dict[str, str]:
            out = {}
            for page in bucket.client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
                for item in page.get("Contents", []):
                    out[item["Key"]] = item["ETag"]
            return out

        markers = lambda: bucket.keys("metadata/source_state/")

        # --- 1. A run leaves every original untouched in raw/ ------------------------------------
        original = seed_uploads(bucket)                     # 24 legacy uploads under raw/<batch>/
        before = etags("raw/")
        first = run_pipeline()
        check("run 1 admits all 24 videos", len(first) == 24, f"admitted {len(first)}")
        check("run 1 leaves every source in raw/ at its own key", bucket.keys("raw/") == sorted(original), str(bucket.keys("raw/"))[:160])
        check("run 1 leaves the exact same bytes (ETags unchanged)", etags("raw/") == before)
        check("run 1 created no copy in processed/", bucket.keys("processed/") == [])
        check("run 1 wrote a draft per source to review/", len(bucket.keys("review/")) == 24)
        check("run 1 recorded one tiny marker per source", len(markers()) == 24)
        check("sources are byte-identical to what was uploaded", all(bucket.get(k) == v for k, v in original.items()))

        # --- 2. Re-runs skip processed sources; only new uploads are admitted ----------------------
        second = run_pipeline()
        check("run 2 (nothing new) admits 0 videos", len(second) == 0, f"admitted {len(second)}")
        check("run 2 still has all 24 originals in raw/", len(bucket.keys("raw/")) == 24 and etags("raw/") == before)
        extra = seed_uploads(bucket, count=3, batch=None, tag="second_")
        third = run_pipeline()
        check("run 3 admits only the 3 new uploads", sorted(third) == sorted(extra), f"admitted {len(third)}")
        total_sources = 27
        check("all 27 originals are in raw/ after three runs", len(bucket.keys("raw/")) == total_sources)

        # A re-uploaded file with different bytes at a processed key is NOT mistaken for the processed one.
        changed_key = sorted(original)[0]
        new_bytes = b"a different video entirely" * 100
        bucket.put(changed_key, new_bytes)
        UPLOADS[changed_key]["verified_size_bytes"] = len(new_bytes)   # the re-upload's provenance row
        fourth = run_pipeline()
        check("a changed object at a processed key is processed again (marker pins size+ETag)", fourth == [changed_key], str(fourth))
        bucket.put(changed_key, original[changed_key])      # put the original bytes back for the rest of the test
        UPLOADS[changed_key]["verified_size_bytes"] = len(original[changed_key])
        run_pipeline()

        # --- 3. Nothing can delete or move an original -------------------------------------------
        import integrations.r2_storage as r2
        some_raw = sorted(original)[1]
        bucket.put("processed/legacy_only.mp4", b"legacy-original")
        raw_snapshot = etags("raw/")
        processed_snapshot = etags("processed/")
        for label, action in [
            ("delete_object(raw)", lambda: r2.delete_object(some_raw)),
            ("delete_object(processed video)", lambda: r2.delete_object("processed/legacy_only.mp4")),
            ("move_object(raw)", lambda: r2.move_object(some_raw, "review/x.mp4")),
            ("move_object_verified(raw)", lambda: r2.move_object_verified(some_raw, "review/x.mp4")),
            ("move_to_pending_payment(raw)", lambda: r2.move_to_pending_payment(some_raw)),
        ]:
            try:
                action()
                refused = False
            except r2.ProtectedSourceError:
                refused = True
            check(f"{label} is refused", refused)
        check("refused attempts changed nothing", etags("raw/") == raw_snapshot and etags("processed/") == processed_snapshot)
        drafts_before = len(bucket.keys("review/"))
        removed = r2.delete_review_drafts()
        check("delete_review_drafts deletes exactly the review/ outputs and no source",
              removed == drafts_before and bucket.keys("review/") == [] and etags("raw/") == raw_snapshot and etags("processed/") == processed_snapshot,
              f"removed={removed} drafts_before={drafts_before}")

        # --- 4. Deduplication excludes a duplicate and deletes nothing --------------------------
        from pipeline.source_upload_dedup import prepare_canonical_sources
        dup_keys = sorted(original)[2:4]
        rows = {k: {"id": f"d-{i}", "status": "verified", "verified_at": f"2026-10-0{i + 1}T00:00:00+00:00", "verified_size_bytes": len(bucket.get(k))}
                for i, k in enumerate(dup_keys)}
        def resolve(upload_id, sha):
            old, new = rows[dup_keys[0]], rows[dup_keys[1]]
            return {"canonical": {"upload_id": new["id"], "storage_key": dup_keys[1]},
                    "superseded": [{"upload_id": old["id"], "storage_key": dup_keys[0]}]}
        def forbidden_delete(key):
            raise AssertionError(f"dedup attempted to delete {key}")
        before_raw = etags("raw/")
        kept = prepare_canonical_sources(
            [{"id": k, "key": k, "name": os.path.basename(k)} for k in dup_keys],
            _download_stub, storage_backend="r2", get_upload=rows.get, resolve_duplicate=resolve,
            delete_source=forbidden_delete, preserve_sources=False,   # even an explicit "delete" request is ignored
            mark_removed=lambda *a: (_ for _ in ()).throw(AssertionError("marked removed")),
            mark_removal_error=lambda *a: (_ for _ in ()).throw(AssertionError("removal error")))
        check("dedup returns only the canonical source", [v["id"] for v in kept] == [dup_keys[1]])
        check("dedup deleted nothing: both duplicates are still in raw/", etags("raw/") == before_raw)

        # --- 5. Reset forgets markers and clears drafts, never touches sources --------------------
        approved_key = "approved/final_reel_keep.mp4"
        bucket.put(approved_key, b"approved output")
        delivered_key = "processed/delivered_reel.mp4"      # a generated output, not a source upload
        bucket.put(delivered_key, b"delivered output")
        before_raw = etags("raw/")
        reset()
        check("reset keeps every original in raw/ with identical bytes", etags("raw/") == before_raw and len(before_raw) == total_sources)
        check("reset forgot every processed marker", markers() == [])
        check("reset clears review/ drafts", bucket.keys("review/") == [])
        check("reset leaves approved/ alone (standard reset)", bucket.keys("approved/") == [approved_key])
        check("reset leaves non-source outputs in processed/ untouched", delivered_key in bucket.keys("processed/"))
        rerun = run_pipeline()
        check("rerun after reset processes all 27 again", len(rerun) == total_sources, f"admitted {len(rerun)}")
        check("rerun leaves the originals exactly where they were", etags("raw/") == before_raw)
        for cycle in (1, 2):
            reset()
            again = run_pipeline()
            check(f"reuse cycle {cycle}: reset + run processes all 27", len(again) == total_sources, f"admitted {len(again)}")
            check(f"reuse cycle {cycle}: originals unchanged", etags("raw/") == before_raw)

        # --- 6. Full clean removes derived outputs only --------------------------------------------
        reset(full_clean=True)
        check("full clean removes approved/ outputs", bucket.keys("approved/") == [])
        check("full clean still leaves every original in raw/", etags("raw/") == before_raw)

        # --- 7. Legacy layout: 23 sources only in processed/<batch>/, 1 still in raw/<batch>/ --------
        bucket.wipe()
        UPLOADS.clear()
        CANONICAL_BY_HASH.clear()
        legacy = seed_uploads(bucket, count=24)
        for key in sorted(legacy)[:23]:
            bucket.put(key.replace("raw/", "processed/", 1), legacy[key])
            bucket.client.delete_object(Bucket=BUCKET, Key=key)   # simulates the OLD move-on behaviour
        processed_before = etags("processed/")
        reset()
        raw_flat = bucket.keys("raw/")
        check("legacy layout: the 23 processed sources are COPIED flat into raw/",
              sum(1 for k in raw_flat if k.count("/") == 1) == 23, str(raw_flat)[:200])
        check("legacy layout: the processed/ originals are KEPT (nothing deleted)", etags("processed/") == processed_before)
        check("legacy layout: the one raw source is untouched", sorted(legacy)[23] in raw_flat)
        check("legacy layout: restored bytes are identical", all(bucket.get(f"raw/{os.path.basename(k)}") == legacy[k] for k in sorted(legacy)[:23]))
        again = run_pipeline()
        check("legacy layout: run processes all 24 from raw/", len(again) == 24, f"admitted {len(again)}")
        check("legacy layout: raw/ still holds all 24 and processed/ is unchanged", len(bucket.keys("raw/")) == 24 and etags("processed/") == processed_before)

        # --- 8. Fail closed on a different-bytes collision, changing nothing ----------------------
        reset()
        victim = sorted(k for k in bucket.keys("processed/"))[0]
        raw_twin = f"raw/{os.path.basename(victim)}"
        bucket.client.delete_object(Bucket=BUCKET, Key=raw_twin)   # test fixture manipulation only
        bucket.put(raw_twin, b"DIFFERENT BYTES")
        before_all = {**etags("raw/"), **etags("processed/")}
        try:
            reset()
            aborted = False
        except RuntimeError:
            aborted = True
        check("reset aborts when raw/ already holds different bytes at the same path", aborted)
        check("an aborted reset changed nothing and did not overwrite the existing raw object",
              {**etags("raw/"), **etags("processed/")} == before_all and bucket.get(raw_twin) == b"DIFFERENT BYTES")
    finally:
        server.stop()

    if failures:
        print(f"\n{len(failures)} check(s) FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("\nPASS raw permanence e2e")
    return 0


def _download_stub(video: dict) -> dict:
    """The dedup gate hashes a local download of each source; fetch the real bytes from the bucket."""
    import integrations.r2_storage as r2
    return {"path": r2.download_object(video["id"], os.path.join(os.environ["TMP_DIR"], f"dd_{os.path.basename(video['id'])}")), "meta": video}


if __name__ == "__main__":
    raise SystemExit(main())
