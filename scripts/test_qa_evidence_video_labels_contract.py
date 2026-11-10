#!/usr/bin/env python3
"""Source-evidence QA must tell the model which uploaded video is the draft.

Run 42814819534 sent [draft, source_1, ..., source_n, prompt] unlabeled. Gemini read the parts as one video:
a 5.0 s reel got findings @7s ("a wider shot featuring three different surfers" = its un-cropped source),
a 5.9 s reel "0:05-0:10 contains a clip not in the manifest", a 52.6 s reel "0:00-0:07 duplicated at
0:52-0:58, only reframed". Every video must be preceded by a label, the draft's label must give its length,
and a finding timestamped past the draft's end must not fail the draft (it is kept for review, not dropped).
No network or Gemini: the provider is a fake that records the request parts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import pipeline.source_evidence_runner as runner

    with tempfile.TemporaryDirectory(prefix="qa-labels-") as tmp:
        os.environ["TMP_DIR"] = tmp
        src = os.path.join(tmp, "DJI_20260720164734_0151_D.MP4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=12",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src], check=True)
        context = {"reel": "reel.mp4", "source_windows": [
            {"source": src, "source_start": 3.0, "source_end": 8.0, "rendered_timeline_start": 0.0, "rendered_timeline_end": 5.0}]}

        sent: list = []
        defects = [
            {"type": "IDENTITY_MISMATCH", "severity": "critical", "at_seconds": 7,
             "note": "transitions to a wider shot featuring three different surfers"},
            {"type": "PREMATURE_CUT", "severity": "minor", "at_seconds": 4, "note": "ride ends slightly early"},
        ]

        class Resp:
            text = json.dumps({"content": {}, "defects": defects, "engagement_score": 75, "overall": "ok"})

        class Model:
            def generate_content(self, parts, request_options=None):
                sent.append(list(parts))
                return Resp()

        class GenAI:
            def GenerativeModel(self, model_name):
                return Model()

        class Analyzer:
            _QA_REEL_PROMPT = "qa"
            _QA_REEL_MODEL = "fake"
            genai = GenAI()

            def _check_technical_compliance(self, reel):
                return {"duration": 5.0, "width": 2160, "height": 3840}, True, []

            def _upload_video(self, path):
                return {"uploaded": os.path.basename(path)}

            def _delete_video(self, item):
                pass

            def _with_retry(self, fn):
                return fn()

            def _persist_qa_result(self, *args):
                pass

        result = runner.with_source_evidence(Analyzer(), lambda *a, **k: {"verdict": "PASS"}, "reel.mp4",
                                             sport="surfing", context=context)
        if not sent:
            raise SystemExit("the model was not called")
        parts = sent[0]
        videos = [i for i, part in enumerate(parts) if isinstance(part, dict)]
        if len(videos) != 2:
            raise SystemExit(f"expected the draft and one source window uploaded, got {len(videos)}")
        for i in videos:
            if i == 0 or not isinstance(parts[i - 1], str):
                raise SystemExit("every uploaded video must be preceded by a text label (run 42814819534)")
        draft_label, source_label = parts[videos[0] - 1], parts[videos[1] - 1]
        if "FINAL DRAFT" not in draft_label or "5.0s" not in draft_label:
            raise SystemExit(f"the draft label must name the draft and its length: {draft_label!r}")
        if "NOT PART OF THE REEL" not in source_label or "3.0s-8.0s" not in source_label or "0.0s-5.0s" not in source_label:
            raise SystemExit(f"the source label must say it is evidence and which window/draft time it covers: {source_label!r}")
        if "16:47:37.0-16:47:42.0 (camera clock)" not in source_label:
            raise SystemExit(f"a DJI window must carry its capture time so two similar waves are not one ride: {source_label!r}")

        if result.get("verdict") != "PASS":
            raise SystemExit(f"a finding @7s on a 5.0 s draft must not fail it, got {result.get('verdict')} {result.get('defects')}")
        kept = [d.get("type") for d in result.get("defects", [])]
        ignored = result.get("out_of_draft_defects") or []
        if kept != ["PREMATURE_CUT"]:
            raise SystemExit(f"in-draft findings must be kept, got {kept}")
        if [d.get("type") for d in ignored] != ["IDENTITY_MISMATCH"] or ignored[0].get("discarded_reason") != "at_seconds_outside_draft":
            raise SystemExit(f"the out-of-draft finding must be recorded with its reason, got {ignored}")

    print("QA evidence video labels contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
