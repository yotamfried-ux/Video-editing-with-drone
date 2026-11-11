#!/usr/bin/env python3
"""Athletes split across clips whose descriptions agree get a second, side-by-side visual check.

Run 43013005072: with 4-crop contact sheets for both, the visual clusterer described one backlit surfer as
"silhouetted shirtless man on a light blue longboard" (0097) and "shirtless man in patterned shorts on a white
surfboard" (0115) and made two reels. The analyzer, which watched each whole clip, called both "on a light blue
longboard" (structured score 0.75, compatible, below the 0.85 text-merge threshold). Nothing re-checked such a
pair: the existing verifier only splits groups.

1. A pair with compatible analyzer descriptions is shown side by side; a confident "same athlete" merges it,
   and the merged cluster is marked visually verified (so the one-reel gate keeps it together).
2. A "same" answer with less than high confidence, or "different", keeps the pair apart.
3. A pair with a hard conflict in the analyzer's descriptions (shirtless vs. long-sleeved wetsuit) is never
   sent: no model answer can merge it. Two people from one clip are never merged.
4. The whole post-process keeps the merge.

No network: the Gemini client is a fake that records what it was asked.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"identity merge-check contract FAILED: {msg}")


class FakeGenai:
    def __init__(self, answer: dict):
        self.answer = answer
        self.calls: list[list] = []
        self.uploaded: list[str] = []

    def upload_file(self, path, mime_type=None):
        self.uploaded.append(path)
        return type("F", (), {"name": os.path.basename(path)})()

    def delete_file(self, name):
        pass

    def GenerativeModel(self, model_name):
        fake = self

        class Model:
            def generate_content(self, content, request_options=None):
                fake.calls.append(list(content))
                return type("R", (), {"text": json.dumps(fake.answer)})()

        return Model()


def app(tmp: str, source: str, description: str) -> dict:
    thumb = os.path.join(tmp, f"{source}.jpg")
    Path(thumb).write_bytes(b"\xff\xd8\xff")
    return {"path": f"/tmp/{source}.MP4", "_clip_index": source, "person_id": "person_A", "_description": description,
            "thumbnail": thumb, "events": [{"type": "wave_catch", "start": 1.0, "end": 8.0, "score": 9}]}


def run(identity, clusters: list[dict], answer: dict) -> tuple[list[dict], FakeGenai]:
    fake = FakeGenai(answer)
    identity.genai = fake
    identity._retry_gemini = lambda fn, attempts=3, base_delay=4: fn()
    return identity._verify_merge_candidates([dict(c, appearances=list(c["appearances"])) for c in clusters]), fake


def main() -> int:
    from pipeline.stages import identity

    with tempfile.TemporaryDirectory(prefix="merge-check-") as tmp:
        s0097 = {"description": "Silhouetted shirtless man on a light blue longboard",
                 "appearances": [app(tmp, "DJI_0097_D", "surfer in dark one-piece/wetsuit on light blue longboard")]}
        s0115 = {"description": "Shirtless man in patterned shorts on a white surfboard",
                 "appearances": [app(tmp, "DJI_0115_D", "surfer in dark shorts on a light blue longboard")]}
        wetsuit = {"description": "Man in a black long-sleeved wetsuit on a white surfboard",
                   "appearances": [app(tmp, "DJI_0074_D", "surfer in a black long-sleeved wetsuit on a red board")]}

        woman = {"description": "Woman in a patterned bikini on a turquoise longboard",
                 "appearances": [app(tmp, "DJI_0165_D", "surfer in a dark top on a light blue longboard")]}
        swimsuit = {"description": "Woman in a grey long-sleeved swimsuit on a blue longboard",
                    "appearances": [app(tmp, "DJI_0070_D", "surfer in dark top on light blue longboard")]}
        pairs = identity._merge_check_pairs([s0097, s0115, woman, swimsuit])
        if [(i, j) for _s, i, j in pairs] != [(0, 1)]:
            fail(f"a man and a woman, or shirtless and long-sleeved, are never sent even when colors match: {pairs}")

        out, fake = run(identity, [s0097, s0115, wetsuit],
                        {"same_person": True, "confidence": "high", "reason": "same build, board color shifts with backlight"})
        merged = [c for c in out if len(c["appearances"]) == 2]
        if len(out) != 2 or len(merged) != 1:
            fail(f"a confident 'same athlete' must merge 0097 and 0115 and leave the third alone: {[len(c['appearances']) for c in out]}")
        if {a["_clip_index"] for a in merged[0]["appearances"]} != {"DJI_0097_D", "DJI_0115_D"}:
            fail("the merged cluster must hold exactly the two checked appearances")
        if merged[0].get("_visual_verified") is not True:
            fail("a merged cluster is visually verified, so the one-reel-per-athlete gate keeps it together")
        if len(fake.calls) != 1:
            fail(f"only the compatible pair is checked; the wetsuit athlete conflicts and must not be sent ({len(fake.calls)} calls)")
        prompt = fake.calls[0][-1]
        if "lighting" not in prompt.lower() or "white in one clip and light blue" not in prompt:
            fail("the check must tell the model that light shifts colors between clips")

        for answer in ({"same_person": True, "confidence": "medium"}, {"same_person": False, "confidence": "high"}, {}):
            out, _ = run(identity, [s0097, s0115], answer)
            if len(out) != 2:
                fail(f"only a high-confidence 'same' merges, got a merge for {answer}")

        same_clip = {"description": "second surfer", "appearances": [dict(app(tmp, "DJI_0097_D", "surfer in dark shorts on a light blue longboard"), person_id="person_B")]}
        out, fake = run(identity, [s0097, same_clip], {"same_person": True, "confidence": "high"})
        if len(out) != 2 or fake.calls:
            fail("two people from the same clip are never sent or merged")

        # Through the whole post-process (the order production runs).
        identity._verify_multi_clusters = lambda clusters: clusters
        fake = FakeGenai({"same_person": True, "confidence": "high", "reason": "same surfer"})
        identity.genai = fake
        final = identity._post_process_clusters_inner([s0097, s0115], [])
        if len(final) != 1 or len(final[0]["appearances"]) != 2:
            fail(f"the merge must survive the safety passes after it: {[len(c['appearances']) for c in final]}")

    print("identity merge-check contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
