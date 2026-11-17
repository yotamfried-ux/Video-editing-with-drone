#!/usr/bin/env python3
"""Cycle 9 (FIX-PQ-09-001 / FIX-PQ-09-002): identity verification on the PRODUCTION model-clustering path.

Qualification run q9-paid-01 (run 44085419164) made 0 pairwise-verifier calls: every appearance built from the model
clustering (`_resolve_model_appearance`) carried `_sheet_crops = 0`, so `verify_cluster` refused every pair as a thin
sheet. Five multi-source clusters stayed UNCONFIRMED and no singleton pair (0097+0115) was ever shown to the verifier.
The older contracts set `_sheet_crops: 6` by hand, which is why they did not see it.

S1  `_resolve_model_appearance` -> `_appearance_from_entry` keeps the sheet's crop count (6 crops -> 6).
S2  End to end through `_post_process_clusters_inner` (the real stage order): a model cluster of two clips whose TEXT
    descriptions conflict ("dark swimsuit" / "no shirt": wetsuit_vs_bare_or_swimsuit_conflict) and whose images are a
    both-orders specific MATCH ends as ONE cluster covered by pairwise evidence (the later description split no longer
    undoes the image evidence).
S3  Same conflict, verifier in doubt (UNCERTAIN) -> two clusters (the description split stands; no merge on text).
S4  A lookalike pair kept together by the model, both orders NO_MATCH with a contradiction -> split.
S5  A lookalike pair, verifier UNCERTAIN -> kept together WITHOUT evidence (withheld by the identity gate), never covered.
S6  Same-clip conflict still splits even when the image evidence would cover the members.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def clip(tmp: str, name: str, description: str, crops: int = 6, persons: int = 1) -> dict:
    out = []
    for p in range(persons):
        pid = f"person_{chr(65 + p)}"
        thumb = Path(tmp) / f"{name}_{pid}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + f"{name}{pid}".encode())
        out.append({"id": pid, "description": description, "thumbnail": str(thumb),
                    "identity_evidence": {"kind": "track_bbox_sheet", "crops": crops, "track_ids": ["10001"]},
                    "events": [{"type": "wave_catch", "person_id": pid, "start": 1.0, "end": 8.0, "track_id": "10001"}]})
    return {"path": f"/tmp/dtor/{name}.MP4", "analysis": {"persons": out}}


def model_cluster(clip_analyses, refs, description="x"):
    apps = []
    for idx, pid in refs:
        entry = identity._resolve_model_appearance({"clip_index": idx, "person_id": pid}, clip_analyses)
        app = identity._appearance_from_entry(entry)
        app["_description"] = entry["description"]
        apps.append(app)
    return {"description": description, "appearances": apps}


def answer(verdict: str) -> str:
    if verdict == "MATCH":
        return json.dumps({"verdict": "MATCH", "matching_features": ["light blue board with dark rails", "dark shorts"],
                           "contradicting_features": [], "generic_only": False})
    if verdict == "NO_MATCH":
        return json.dumps({"verdict": "NO_MATCH", "matching_features": [], "contradicting_features": ["board colour"],
                           "generic_only": False})
    return json.dumps({"verdict": "UNCERTAIN", "matching_features": [], "contradicting_features": [], "generic_only": True})


def run(clusters, clip_analyses, verdict: str):
    calls = []

    def ask(prompt, images):
        calls.append(len(images))
        return answer(verdict)
    saved = identity._consensus_ask
    saved_merge = identity._verify_merge_candidates
    identity._consensus_ask = ask
    identity._verify_merge_candidates = lambda c: c          # the separate merge-check path is covered elsewhere
    try:
        return identity._post_process_clusters_inner(clusters, clip_analyses), calls
    finally:
        identity._consensus_ask = saved
        identity._verify_merge_candidates = saved_merge


def sources(cluster):
    return sorted(Path(a["path"]).stem for a in cluster["appearances"])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        # S1
        cas = [clip(tmp, "c0097", "surfer in dark swimsuit on a light-colored surfboard"),
               clip(tmp, "c0115", "surfer with dark shorts, no shirt, on a light blue surfboard")]
        c = model_cluster(cas, [(0, "person_A"), (1, "person_A")], "Shirtless man in patterned shorts on a light blue surfboard.")
        check([a["_sheet_crops"] for a in c["appearances"]] == [6, 6],
              f"S1 model-path appearances must keep the sheet crop count, got {[a['_sheet_crops'] for a in c['appearances']]}")

        # S2
        out, calls = run([c], cas, "MATCH")
        check(calls, "S2 the verifier must be called on the model-path cluster")
        check(len(out) == 1 and sources(out[0]) == ["c0097", "c0115"] and ev.covers(out[0]),
              f"S2 image-verified pair must end as one covered cluster, got {[sources(x) for x in out]}")

        # S3
        c = model_cluster(cas, [(0, "person_A"), (1, "person_A")])
        out, _ = run([c], cas, "UNCERTAIN")
        check(len(out) == 2 and not any(ev.covers(x) for x in out),
              f"S3 doubt + description conflict must stay split, got {[sources(x) for x in out]}")

        # S4 / S5 lookalikes with compatible descriptions (0143+0152-like)
        cas2 = [clip(tmp, "c0143", "Man in a white t-shirt on a pink surfboard"),
                clip(tmp, "c0152", "Man in a white t-shirt on a pink surfboard")]
        out, _ = run([model_cluster(cas2, [(0, "person_A"), (1, "person_A")])], cas2, "NO_MATCH")
        check(len(out) == 2, f"S4 both-orders NO_MATCH must split, got {[sources(x) for x in out]}")
        out, _ = run([model_cluster(cas2, [(0, "person_A"), (1, "person_A")])], cas2, "UNCERTAIN")
        check(len(out) == 1 and not ev.covers(out[0]), "S5 doubt must keep the pair together WITHOUT evidence")

        # S6 same clip, two people
        cas3 = [clip(tmp, "c0200", "Man in a white t-shirt on a pink surfboard", persons=2)]
        c = model_cluster(cas3, [(0, "person_A"), (0, "person_B")])
        check(len(identity._split_impossible_clusters([c])) == 2, "S6 a same-clip pair must split")

    for f in FAILURES:
        print("FAIL", f)
    print(f"{'OK' if not FAILURES else 'FAILED'}: identity model-path sheet contract ({len(FAILURES)} failures)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
