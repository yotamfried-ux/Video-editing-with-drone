#!/usr/bin/env python3
"""Fail-fast storage access preflight for the pipeline.

Drive remains the default backend and is intentionally skipped here because its
existing credentials are validated separately. When STORAGE_BACKEND=r2, this
script verifies that the configured R2 credentials can write, read, and delete a
small object before the expensive video pipeline starts.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations.storage import get_backend_name


def _check_r2() -> None:
    from integrations import r2_storage

    key = f"review/_preflight_{uuid.uuid4().hex}.txt"
    body = b"sportreel storage preflight\n"
    downloaded = None
    with tempfile.NamedTemporaryFile(delete=False) as src:
        src.write(body)
        src_path = src.name
    try:
        print(f"🔎 R2 preflight: uploading {key}")
        r2_storage.upload_object(src_path, key, "text/plain")
        downloaded = tempfile.NamedTemporaryFile(delete=False)
        downloaded.close()
        print(f"🔎 R2 preflight: downloading {key}")
        r2_storage.download_object(key, downloaded.name)
        actual = Path(downloaded.name).read_bytes()
        if actual != body:
            raise RuntimeError("R2 preflight download content mismatch")
        print(f"🔎 R2 preflight: deleting {key}")
        r2_storage.delete_object(key)
        print("✅ R2 storage preflight passed")
    finally:
        try:
            r2_storage.delete_object(key)
        except Exception:
            pass
        for path in (src_path, downloaded.name if downloaded else None):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


def main() -> int:
    backend = get_backend_name()
    if backend == "drive":
        print("✅ Storage preflight skipped: STORAGE_BACKEND=drive")
        return 0
    if backend == "r2":
        _check_r2()
        return 0
    raise RuntimeError(f"Unsupported storage backend: {backend}")


if __name__ == "__main__":
    raise SystemExit(main())
