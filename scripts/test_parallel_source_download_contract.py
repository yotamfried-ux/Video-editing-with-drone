#!/usr/bin/env python3
"""Sources download concurrently; admission decisions stay sequential and in input order.

Run 42857524999 spent 3.5 min downloading 29 sources (~7 GB) one after another before analysis started.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from pipeline.source_upload_dedup import prepare_canonical_sources

    os.environ["SPORTREEL_DOWNLOAD_WORKERS"] = "4"
    with tempfile.TemporaryDirectory() as tmp:
        videos = [{"id": f"raw/b/clip{i}.mp4", "name": f"clip{i}.mp4"} for i in range(8)]
        active = {"now": 0, "peak": 0}
        lock = threading.Lock()
        lookups: list[str] = []

        def download(video):
            with lock:
                active["now"] += 1
                active["peak"] = max(active["peak"], active["now"])
            # Later files finish first: results must still be consumed in input order.
            time.sleep(0.25 if video["name"] < "clip4" else 0.05)
            path = Path(tmp) / video["name"]
            path.write_bytes(video["name"].encode())
            with lock:
                active["now"] -= 1
            return None if video["name"] == "clip5.mp4" else {"path": str(path), "meta": video}

        def get_upload(key):
            lookups.append(key)
            return None  # legacy input: admitted without exact-upload dedup

        t0 = time.monotonic()
        out = prepare_canonical_sources(videos, download, storage_backend="r2", get_upload=get_upload, resolve_duplicate=lambda *a: {},
                                        mark_removed=lambda *a: None, mark_removal_error=lambda *a: None)
        elapsed = time.monotonic() - t0
        expected = [v["id"] for v in videos if v["name"] != "clip5.mp4"]
        if lookups != expected or [v["id"] for v in out] != expected:
            raise SystemExit(f"admission must follow the input order and skip failed downloads: {lookups}")
        if active["peak"] < 2 or elapsed > 1.0:
            raise SystemExit(f"downloads must overlap (peak {active['peak']}, {elapsed:.2f}s; sequential would be ~1.2s)")
        if active["peak"] > 4:
            raise SystemExit(f"at most SPORTREEL_DOWNLOAD_WORKERS downloads at once, saw {active['peak']}")

        def boom(video):
            if video["name"] == "clip2.mp4":
                raise RuntimeError("network down")
            return download(video)

        try:
            prepare_canonical_sources(videos, boom, storage_backend="r2", get_upload=get_upload, resolve_duplicate=lambda *a: {},
                                      mark_removed=lambda *a: None, mark_removal_error=lambda *a: None)
        except RuntimeError as exc:
            if "network down" not in str(exc):
                raise
        else:
            raise SystemExit("a download error must still propagate")
    print(f"parallel source download contract ok (peak {active['peak']} concurrent, {elapsed:.2f}s vs ~1.2s sequential)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
