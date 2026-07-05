#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import tempfile
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import pipeline.source_evidence_runner as runner
    import pipeline.source_evidence_patch as patch
    import pipeline.context_qa_gate as gate

    f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    f.write(b"x")
    f.close()
    runner.make_source_clips = lambda _ctx: [f.name]
    base = lambda *_args, **_kwargs: {"verdict": "PASS", "defects": [], "engagement_score": 90}
    res = runner.with_source_evidence(object(), base, "reel.mp4", context={"source_windows": [{"source": f.name}]})
    if res.get("verdict") != "FAIL" or res.get("qa_review_required") is not True:
        raise SystemExit("not fail closed")
    if res.get("defects", [{}])[-1].get("type") != "QA_REVIEW_REQUIRED":
        raise SystemExit("missing defect")
    if os.path.exists(f.name):
        raise SystemExit("clip not cleaned")
    before = gate._qa_gate_with_edit_context
    patch.install()
    if gate._qa_gate_with_edit_context is before:
        raise SystemExit("patch not installed")
    if "pipeline.source_evidence_patch" not in (ROOT / "scripts/usercustomize.py").read_text(encoding="utf-8"):
        raise SystemExit("bootstrap missing")
    print("Source evidence contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
