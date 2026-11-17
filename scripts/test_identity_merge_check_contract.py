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
            "thumbnail": thumb, "_sheet_crops": 6, "events": [{"type": "wave_catch", "start": 1.0, "end": 8.0, "score": 9}]}


def run(identity, clusters: list[dict], answer) -> tuple[list[dict], FakeGenai]:
    """`answer` is the raw consensus-verifier text returned for BOTH image orders; calls are recorded."""
    fake = FakeGenai({})
    text = answer if isinstance(answer, str) else json.dumps(answer)

    def ask(prompt, images):
        fake.calls.append([prompt, len(images)])
        return text

    identity._consensus_ask = ask
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

        # Run 43203677423: the clusterer hedged on 0097's backlit outfit ("a dark one-piece or wetsuit"). Read as a
        # one-piece, that made him female in swimwear, so 0097/0115 was never checked and he got two reels again.
        hedged = {"description": "Silhouette of a surfer in a dark one-piece or wetsuit on a light blue longboard",
                  "appearances": s0097["appearances"]}
        shorts = {"description": "Silhouette of a shirtless surfer in dark shorts on a white or light blue surfboard",
                  "appearances": s0115["appearances"]}
        if [(i, j) for _s, i, j in identity._merge_check_pairs([hedged, shorts])] != [(0, 1)]:
            fail("a hedged garment ('one-piece or wetsuit') is no reading of sex or sleeves: 0097/0115 must be checked")
        bikini = {"description": "Woman in a dark green bikini on a white surfboard",
                  "appearances": [app(tmp, "DJI_0160_D", "surfer in a dark top on a white board")]}
        if identity._merge_check_pairs([bikini, shorts]):
            fail("an unhedged bikini against a shirtless man is still never sent")

        import _consensus_fixture as fx
        out, fake = run(identity, [s0097, s0115, wetsuit], fx.MATCH_SPECIFIC)
        merged = [c for c in out if len(c["appearances"]) == 2]
        if len(out) != 2 or len(merged) != 1:
            fail(f"a consensus MATCH must merge 0097 and 0115 and leave the third alone: {[len(c['appearances']) for c in out]}")
        if {a["_clip_index"] for a in merged[0]["appearances"]} != {"DJI_0097_D", "DJI_0115_D"}:
            fail("the merged cluster must hold exactly the two checked appearances")
        if merged[0].get("_visual_verified") is not True or merged[0].get("_identity_evidence", {}).get("method") != "pairwise_consensus":
            fail("a merged pair carries pairwise-consensus evidence, so the one-reel-per-athlete gate keeps it together")
        if len(fake.calls) != 2:
            fail(f"the compatible pair is checked once in BOTH image orders (2 calls), the wetsuit athlete conflicts ({len(fake.calls)} calls)")
        prompt = fake.calls[0][0]
        if "NOT" not in prompt or "contradiction" not in prompt.lower():
            fail("the check must reject generic traits and look for contradictions")

        # Any doubt, a one-sided answer, a generic lookalike or a contradiction: never merged.
        for answer in (fx.MATCH_GENERIC, fx.UNCERTAIN, fx.NO_MATCH, "", "{}", "not json"):
            out, _ = run(identity, [s0097, s0115], answer)
            if len(out) != 2:
                fail(f"only a consensus MATCH merges, got a merge for {answer!r}")
        answers = iter([fx.MATCH_SPECIFIC, fx.NO_MATCH])
        identity._consensus_ask = lambda prompt, images: next(answers)
        if len(identity._verify_merge_candidates([dict(s0097), dict(s0115)])) != 2:
            fail("two image orders that disagree must not merge")

        same_clip = {"description": "second surfer", "appearances": [dict(app(tmp, "DJI_0097_D", "surfer in dark shorts on a light blue longboard"), person_id="person_B")]}
        out, fake = run(identity, [s0097, same_clip], fx.MATCH_SPECIFIC)
        if len(out) != 2 or fake.calls:
            fail("two people from the same clip are never sent or merged")

        # Through the whole post-process (the order production runs).
        identity._verify_multi_clusters = lambda clusters: clusters
        identity._consensus_ask = lambda prompt, images: fx.MATCH_SPECIFIC
        final = identity._post_process_clusters_inner([s0097, s0115], [])
        if len(final) != 1 or len(final[0]["appearances"]) != 2:
            fail(f"the merge must survive the safety passes after it: {[len(c['appearances']) for c in final]}")

    print("identity merge-check contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
