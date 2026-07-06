#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.perception.runtime import ensure_sidecar_for_video


def _clear_env() -> None:
    for key in [
        "SPORTREEL_PERCEPTION_COMMAND",
        "SPORTREEL_PERCEPTION_SIDECAR_DIR",
        "SPORTREEL_REQUIRE_PERCEPTION",
    ]:
        os.environ.pop(key, None)


def main() -> int:
    tmp = ROOT / ".tmp_perception_producer_diagnostics"
    tmp.mkdir(exist_ok=True)
    producer = tmp / "failing_producer.py"
    video = tmp / "sample.mp4"
    producer.write_text(
        "import sys\n"
        "print('producer stdout marker')\n"
        "print('producer stderr marker', file=sys.stderr)\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    try:
        _clear_env()
        os.environ["SPORTREEL_REQUIRE_PERCEPTION"] = "1"
        os.environ["SPORTREEL_PERCEPTION_COMMAND"] = f"{sys.executable} {producer}"
        try:
            ensure_sidecar_for_video(str(video))
        except RuntimeError as exc:
            message = str(exc)
            for token in ["returncode=7", "producer stdout marker", "producer stderr marker"]:
                if token not in message:
                    raise SystemExit(f"missing diagnostic token: {token}")
        else:
            raise SystemExit("required perception should raise on failing producer")
    finally:
        _clear_env()
        for path in sorted(tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
        if tmp.exists():
            tmp.rmdir()
    print("Perception producer diagnostics contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
