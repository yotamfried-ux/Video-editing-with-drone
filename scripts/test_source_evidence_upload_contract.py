#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import pipeline.source_evidence_runner as runner
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    f.write(b"x")
    f.close()
    runner.make_source_clips = lambda _ctx: [f.name]
    class R:
        text = json.dumps({"content": {}, "defects": [], "engagement_score": 90, "overall": "ok"})
    class M:
        def generate_content(self, parts, request_options=None):
            if len(parts) < 3:
                raise RuntimeError("missing source upload")
            return R()
    class G:
        def GenerativeModel(self, model_name):
            return M()
    class A:
        _QA_REEL_PROMPT = "qa"
        _QA_REEL_MODEL = "model"
        genai = G()
        def _check_technical_compliance(self, reel): return {}, True, []
        def _upload_video(self, path): return {"name": path}
        def _delete_video(self, item): pass
        def _with_retry(self, fn): return fn()
        def _persist_qa_result(self, result, reel, sport): pass
    base = lambda *_args, **_kwargs: {"verdict": "PASS"}
    res = runner.with_source_evidence(A(), base, "reel.mp4", sport="surfing", context={"source_windows": [{"source": f.name}]})
    if res.get("source_evidence_visual_uploaded") is not True:
        raise SystemExit("source evidence not uploaded")
    if os.path.exists(f.name):
        raise SystemExit("source clip not cleaned")
    print("Source evidence upload contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
