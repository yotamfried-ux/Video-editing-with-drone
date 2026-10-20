#!/usr/bin/env python3
"""End-to-end test of the stage-folder flow against a real S3 protocol server (moto).

Runs the project's real boto3 storage code (integrations.r2_storage), the real batchless
admission/move hooks (pipeline.r2_batch_scope) and the real reset script
(scripts/reset_and_rerun.py). Nothing here touches production: the bucket lives in a local
moto server and source-provenance rows come from an in-memory stand-in for Supabase.

Intended behaviour (the operator's folder-per-stage model):
  * Run pipeline processes everything in the first folder (raw/, including raw/<batch>/ where
    the app uploads) and MOVES each source on to processed/, so a second run finds nothing new.
  * Reset returns every source to raw/, removes it from processed/, clears review/ drafts
    (and approved/ on full clean), after which the pipeline runs again from the first folder.
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
        return {"canonical": {"upload_id": first[0], "storage_key": first[1]}, "superseded": []}

    module.resolve_exact_source_duplicate = resolve_exact_source_duplicate
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


def seed_uploads(bucket: Bucket, count: int = 24, batch: str = BATCH, tag: str = "") -> dict[str, bytes]:
    """The app uploads into raw/<batch>/ and records a verified source_uploads row per file."""
    contents = {}
    for i in range(count):
        key = f"raw/{batch}/{tag}2026-10-03T12-19-{i:02d}_DJI_{i:04d}.mp4"
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
    import reset_and_rerun
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
        import pipeline.r2_batch_scope as scope
        scope.install()

        def check(name: str, condition: bool, detail: str = "") -> None:
            print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail and not condition else ""))
            if not condition:
                failures.append(name)

        # --- Scenario 1: first run processes all 24 uploads that live in raw/<batch>/ -------------
        original = seed_uploads(bucket)
        first = run_pipeline()
        check("run 1 admits all 24 videos from the first folder", len(first) == 24, f"admitted {len(first)}")
        check("run 1 moves every source out of raw/ into processed/",
              bucket.keys("raw/") == [] and len(bucket.keys("processed/")) == 24,
              f"raw={len(bucket.keys('raw/'))} processed={len(bucket.keys('processed/'))}")
        check("run 1 wrote a draft per source to review/", len(bucket.keys("review/")) == 24)
        if first:
            check("moved sources are byte-identical", all(
                bucket.get(k.replace("raw/", "processed/", 1)) == v for k, v in original.items()))

        # --- Scenario 2: a second run only handles what is new in the first folder ---------------
        second = run_pipeline()
        check("run 2 (nothing new in raw/) admits 0 videos", len(second) == 0, f"admitted {len(second)}")
        extra = seed_uploads(bucket, count=3, batch="batch_new_upload", tag="second_")
        third = run_pipeline()
        check("run 3 admits only the 3 newly uploaded videos", sorted(third) == sorted(extra), f"admitted {len(third)}")
        total_sources = 27

        # --- Scenario 3: standard reset puts everything back in raw/, clears the other folders ---
        approved_key = "approved/final_reel_keep.mp4"
        bucket.put(approved_key, b"approved output")
        delivered_key = "processed/delivered_reel.mp4"  # a generated output, not a source upload
        bucket.put(delivered_key, b"delivered output")
        reset()
        raw_after = bucket.keys("raw/")
        check("reset returns all 27 sources to raw/", len(raw_after) == total_sources, f"raw={len(raw_after)}")
        check("reset keeps each source at its original path", set(raw_after) == set(original) | set(extra))
        check("reset removes the sources from processed/",
              [k for k in bucket.keys("processed/") if k != delivered_key] == [],
              str(bucket.keys("processed/"))[:200])
        check("reset clears review/ drafts", bucket.keys("review/") == [])
        check("reset leaves approved/ outputs alone (standard reset)", bucket.keys("approved/") == [approved_key])
        check("reset never touches a non-source object in processed/", delivered_key in bucket.keys("processed/"))
        check("restored sources are byte-identical to the originals",
              all(bucket.get(k) == v for k, v in original.items()))

        # --- Scenario 4: rerun after reset runs everything again from the first folder -----------
        rerun = run_pipeline()
        check("rerun after reset processes all 27 again", len(rerun) == total_sources, f"admitted {len(rerun)}")
        check("rerun moves them on to processed/ again",
              bucket.keys("raw/") == [] and len([k for k in bucket.keys("processed/") if k != delivered_key]) == total_sources)

        # --- Scenario 5: repeated use (reset + run) stays stable -----------------------------------
        for cycle in (1, 2):
            reset()
            again = run_pipeline()
            check(f"reuse cycle {cycle}: reset + run processes all 27", len(again) == total_sources, f"admitted {len(again)}")
            check(f"reuse cycle {cycle}: no stray copies",
                  len(bucket.keys("raw/")) == 0 and len(bucket.keys("review/")) == total_sources)

        # --- Scenario 6: full clean also clears approved/ -----------------------------------------
        reset(full_clean=True)
        check("full clean returns all sources to raw/", len(bucket.keys("raw/")) == total_sources)
        check("full clean removes approved/ outputs", bucket.keys("approved/") == [])
        check("full clean still leaves non-source outputs in processed/ untouched", delivered_key in bucket.keys("processed/"))

        # --- Scenario 7: fail-closed on a name collision with different bytes ----------------------
        run_pipeline()
        victim = sorted(k for k in bucket.keys("processed/") if k != delivered_key)[0]
        raw_twin = victim.replace("processed/", "raw/", 1)
        bucket.put(raw_twin, b"DIFFERENT BYTES")
        before_processed = bucket.keys("processed/")
        try:
            reset()
            aborted = False
        except RuntimeError:
            aborted = True
        check("reset aborts when raw/ already holds different bytes at the same path", aborted)
        check("an aborted reset deleted nothing from processed/", bucket.keys("processed/") == before_processed)
        check("an aborted reset did not overwrite the existing raw object", bucket.get(raw_twin) == b"DIFFERENT BYTES")
    finally:
        server.stop()

    if failures:
        print(f"\n{len(failures)} check(s) FAILED:")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("\nPASS stage-folder flow e2e")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
