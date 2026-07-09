#!/usr/bin/env python3
"""Regression test for the R2 requeue_video source-location bug found during
GAP-012 real-run validation (run 28976345305).

The operator "Send to re-edit" flow calls requeue_video() with the source id
recorded in the `drafts` table at draft-creation time — the object's raw/
key, captured *before* the original run's mark_as_processed moved it to
processed/. requeue_video must always move it back from processed/ to raw/
regardless of which prefix the caller's id happens to carry, mirroring how
the Drive adapter hardcodes PROCESSED_FOLDER_ID -> RAW_FOLDER_ID. Before the
fix, requeue_video treated the passed-in (stale, raw/-prefixed) key as the
current location, tried to copy from a key that no longer existed, and
silently returned False -- surfacing as "source videos not found" and a
reprocess_requests row stuck at status='source_not_found' even though the
video was sitting untouched in processed/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations import r2_storage  # noqa: E402


class _FakeR2Client:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.copy_calls: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def copy_object(self, Bucket, CopySource, Key):  # noqa: N803 - mirrors boto3 kwarg casing
        source_key = CopySource["Key"]
        if source_key not in self.objects:
            raise RuntimeError(f"NoSuchKey: {source_key}")
        self.copy_calls.append((source_key, Key))
        self.objects[Key] = self.objects[source_key]

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise RuntimeError(f"NoSuchKey: {Key}")

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)
        self.deleted.append(Key)


def main() -> int:
    basename = "2026-07-04T18-34-54_1000270686.mp4"
    # The video was already moved to processed/ by mark_as_processed during
    # the original run -- it no longer lives at raw/<basename>.
    objects = {f"processed/{basename}": b"video-bytes"}
    fake_client = _FakeR2Client(objects)
    r2_storage._client = lambda: fake_client

    # The caller passes back the *stale* raw/-prefixed id recorded in the
    # drafts table at draft-creation time, not the current processed/ key.
    stale_raw_prefixed_id = f"raw/{basename}"
    ok = r2_storage.requeue_video(stale_raw_prefixed_id)

    if not ok:
        raise SystemExit(
            "requeue_video returned False for a video that genuinely exists in processed/; "
            "it must locate the file there instead of trusting the caller's stale key prefix"
        )
    if f"raw/{basename}" not in fake_client.objects:
        raise SystemExit(f"expected raw/{basename} to exist after requeue, got {list(fake_client.objects)}")
    if f"processed/{basename}" in fake_client.objects:
        raise SystemExit(f"expected processed/{basename} to be removed after requeue, got {list(fake_client.objects)}")
    if fake_client.copy_calls != [(f"processed/{basename}", f"raw/{basename}")]:
        raise SystemExit(f"expected a single copy from processed/ to raw/, got {fake_client.copy_calls}")

    print("R2 requeue_video contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
