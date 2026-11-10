#!/usr/bin/env python3
"""Visual identity clustering uploads and deletes thumbnails concurrently, with the request order unchanged.

Run 42857524999: 23 thumbnails were uploaded and then deleted one at a time around the clustering call,
~2.5 min of the critical path before the first reel render.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import pipeline.stages.identity as identity

    n = 12
    entries = [{"clip_index": i, "person_id": f"person_{chr(65 + i % 3)}", "thumbnail": f"/tmp/t{i}.jpg"} for i in range(n)]
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()
    deleted: list[str] = []
    sent: list = []

    class File:
        def __init__(self, name):
            self.name = name

    class FakeGenAI:
        def upload_file(self, path, mime_type):
            with lock:
                active["now"] += 1
                active["peak"] = max(active["peak"], active["now"])
            time.sleep(0.2 if path.endswith(("0.jpg", "1.jpg")) else 0.05)  # early files finish last
            with lock:
                active["now"] -= 1
            return File(f"files/{Path(path).stem}")

        def delete_file(self, name):
            time.sleep(0.2)
            with lock:
                deleted.append(name)

    identity.genai = FakeGenAI()
    identity._person_entries = lambda analyses, require_thumbnail=False: entries
    identity._gemini_call_cluster_visual = lambda content, model_name, n_clips: sent.extend(content) or "{}"
    identity._parse_json_response = lambda raw: {}
    identity._build_clusters_from_data = lambda data, analyses: [{"description": "x", "appearances": []}]

    t0 = time.monotonic()
    result = identity._try_visual_cluster([{"clip": 0}], [{}] * n)
    elapsed = time.monotonic() - t0
    if not result:
        raise SystemExit("clustering result lost")
    labels = [c for c in sent if isinstance(c, str) and c.startswith("[Clip")]
    files = [c.name for c in sent if isinstance(c, File)]
    expected = [f"[Clip {e['clip_index']}, {e['person_id']}]:" for e in entries]
    if labels != expected or files != [f"files/t{i}" for i in range(n)]:
        raise SystemExit("Gemini must receive the thumbnails in the original order")
    if sorted(deleted) != sorted(files):
        raise SystemExit("every uploaded thumbnail must be deleted")
    sequential = 2 * 0.2 + (n - 2) * 0.05 + n * 0.2
    if active["peak"] < 2 or elapsed > sequential * 0.6:
        raise SystemExit(f"uploads/deletes must overlap: {elapsed:.2f}s vs {sequential:.2f}s sequential, peak {active['peak']}")
    print(f"identity Files API concurrency contract ok ({elapsed:.2f}s vs {sequential:.2f}s sequential, order kept)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
