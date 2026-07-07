#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    import sys
    sys.path.insert(0, str(ROOT))
    from pipeline.teaser_policy_runtime import is_teaser_event, strip_teaser_events, strip_teasers_from_events_out

    teaser = {"type": "highlight", "start": 10.0, "end": 12.5, "_teaser": True}
    normal = {"type": "highlight", "start": 20.0, "end": 35.0}
    require(is_teaser_event(teaser), "teaser event not detected")
    require(not is_teaser_event(normal), "normal event misdetected as teaser")
    require(strip_teaser_events([teaser, normal]) == [normal], "strip_teaser_events must remove only teasers")

    events_out = [("reel.mp4", [teaser, normal])]
    strip_teasers_from_events_out(events_out)
    require(events_out == [("reel.mp4", [normal])], "events_out must be stripped before QA/metadata")

    runtime = (ROOT / "pipeline/teaser_policy_runtime.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    for token in ["Skipping cold-open teaser", "editor._cut_clip_with_qa", "strip_teasers_from_events_out"]:
        require(token in runtime, f"teaser runtime missing {token}")
    require("_install_teaser_policy_runtime()" in run_tracked, "run_tracked must install teaser policy before orchestrator import")
    require(run_tracked.index("_install_teaser_policy_runtime()") < run_tracked.index("import pipeline.orchestrator"), "teaser policy must install before orchestrator import")

    print("teaser policy contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
