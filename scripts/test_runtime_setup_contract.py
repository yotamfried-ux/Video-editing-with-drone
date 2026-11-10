#!/usr/bin/env python3
"""Runtime guards from run 42814819534 (no ffmpeg, no network).

* The reel encode timeout scales with the reel: a 53 s reel took 469 s and a 69 s reel 448 s, so the fixed
  600 s limit would have killed a reel near the 90 s maximum.
* Runner disk cleanup (2m04s per run) runs in the background and is awaited before "Run pipeline".
* The escalation stride default is unchanged; the env knob only enables a Ground-Truth A/B.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    from pipeline.stages.editor import _compile_timeout

    if _compile_timeout(5) != 600 or _compile_timeout(None) != 600:
        raise SystemExit("short reels keep the previous 600 s limit")
    for reel_sec, observed in ((53, 469), (69, 448)):
        if _compile_timeout(reel_sec) < 1.5 * observed:
            raise SystemExit(f"a {reel_sec}s reel took {observed}s in production; timeout {_compile_timeout(reel_sec)}s leaves no margin")
    if _compile_timeout(90) < 90 * 8.8 * 1.5:
        raise SystemExit("a 90 s reel at the worst observed 8.8 s per reel second must fit with margin")

    # Step order from the workflow text (the CI job has no YAML parser installed).
    text = (ROOT / ".github/workflows/pipeline-run.yml").read_text(encoding="utf-8")
    blocks = text.split("\n      - name: ")[1:]
    names = [b.split("\n", 1)[0].strip() for b in blocks]
    body = dict(zip(names, blocks))
    free = body["Free runner disk space"]
    if "setsid nohup" not in free or "/tmp/runner-disk-freed" not in free or "< /dev/null &" not in free:
        raise SystemExit("disk cleanup must run in the background and leave a completion marker")
    wait_at, run_at = names.index("Wait for runner disk cleanup"), names.index("Run pipeline")
    if not wait_at < run_at or "/tmp/runner-disk-freed" not in body["Wait for runner disk cleanup"]:
        raise SystemExit("the pipeline must wait for the disk cleanup before downloading sources")

    os.environ.pop("SPORTREEL_ESCALATION_STRIDE", None)
    import generate_perception_sidecar as gps

    if gps._escalation_stride(5) != 2 or gps._escalation_stride(1) != 1:
        raise SystemExit("the default escalation stride must stay half the primary stride")
    os.environ["SPORTREEL_ESCALATION_STRIDE"] = "5"
    if gps._escalation_stride(5) != 5:
        raise SystemExit("SPORTREEL_ESCALATION_STRIDE must override for A/B runs")
    os.environ.pop("SPORTREEL_ESCALATION_STRIDE")
    print("runtime setup contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
