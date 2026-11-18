#!/usr/bin/env python3
"""Cycle 12 identity working decisions (mandate 4.1 / 4.2), bound to the REAL sources of GT-v1.

Positive: 0097 + 0115 are one athlete (request 758fe7783e9c...). Negative: 0074 + 0151 are two people (7b2a6964427f...).
Source identities are the real content SHA-256 values of the EXP-11-001 inputs (edl_clips.jsonl); the files here are
stand-ins carrying the production names, their content hash injected into event_identity's source cache.

W1  the request ids computed by the production code from the real sources equal the ones EXP-11-001 recorded
W2  qualification run + working file: the 0097+0115 grouping split on text attributes is kept together with
    operator_review evidence; the identity gate passes it (merge NOT based on text similarity: owner decision bound
    to the exact sources and people)
W3  0074+0151 split on text attributes, REJECTED -> stays split, no new request
W4  0074+0151 with a model verifier that says MATCH -> split anyway (owner rejection outranks model consensus)
    [RED on 3da09101: the MATCH branch kept the pair together with model evidence]
W5  a superset 0074+0151+0097 that even carries an owner approval -> split (no transitive merge through a rejected pair)
W6  singleton merge stage with a MATCH-everything verifier never groups 0074 with 0151
W7  the 0097+0115 approval does not extend: 0097+0151 and 0115+0074 are not approved (PENDING)
W8  outside a qualification run the working file is ignored (production identity decisions unchanged)
W9  no production decision file exists in the repository (a live owner action is separate)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import event_identity  # noqa: E402
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline import identity_pair_consensus as ipc  # noqa: E402
from pipeline import identity_review as review  # noqa: E402
from pipeline.real_identity_gate import enforce_identity_gate  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILS: list[str] = []
WORKING = ROOT / "evaluation" / "qualification" / "identity_working_decisions.json"
REAL = {  # EXP-11-001 (run 44252428407) edl_clips.jsonl source_sha256
    "0097": ("2026-10-03T12-19-53_DJI_20260720160658_0097_D.MP4", "548cf4ffb308cb65628cb2c5209027f65587f1d926a798a021038c097c2784eb"),
    "0115": ("2026-10-03T12-19-53_DJI_20260720161907_0115_D.MP4", "b62c8aa0cb140b103e40a2518c41c33f2081da41f0b7e0fe8b07405a41000740"),
    "0074": ("2026-10-03T12-19-53_DJI_20260720154350_0074_D.MP4", "f6ac72f8aeb5311993f61a78a55061506eae450fab15906815e9eca5f03ab74f"),
    "0151": ("2026-10-03T12-19-54_DJI_20260720164734_0151_D.MP4", "e01a614de6057284637f598c74004859ca144c9a3a8dea77c0ac64c466fd1da8"),
}
POS = "758fe7783e9c16dc579f0c951a556fc68b7dd94dea78ca9642cce7ed98873e60"
NEG = "7b2a6964427f5b96fe87311e310b01ae1739f59852b892bac42519024bd966b3"


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="idw-"))
    paths = {}
    for k, (name, sha) in REAL.items():
        p = tmp / name
        p.write_bytes(b"stand-in")
        event_identity._SOURCE_REF_CACHE[os.path.abspath(str(p))] = ("sha256", sha)
        paths[k] = str(p)

    def app(k, desc, idx):
        thumb = tmp / f"{k}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + k.encode())
        return {"path": paths[k], "_clip_index": idx, "_person_id": "person_A", "thumbnail": str(thumb), "_sheet_crops": 6,
                "_description": desc, "events": [{"type": "wave_catch", "person_id": "person_A", "start": 1.0, "end": 8.0, "track_id": str(10001 + idx)}]}

    def pair(a, da, b, db):
        return {"description": "proposed one athlete", "appearances": [app(a, da, 0), app(b, db, 1)]}

    pos = lambda: pair("0097", "surfer in dark swimsuit on a light-colored surfboard", "0115", "surfer with dark shorts, no shirt, on a light blue surfboard")
    neg = lambda: pair("0074", "man in a black wetsuit top on a white surfboard", "0151", "man with no shirt in black shorts on a white surfboard")

    check(review.request_id(pos()) == POS and review.request_id(neg()) == NEG,
          f"W1 production request ids from the real sources = EXP-11-001 ids ({review.request_id(pos())[:12]}, {review.request_id(neg())[:12]})")

    os.environ[review.DECISIONS_ENV] = str(WORKING)
    os.environ["SPORTREEL_QUALIFICATION_RUN_ID"] = "q12-identity-contract"
    calls = []
    saved_ask = identity._consensus_ask
    identity._consensus_ask = lambda *a, **k: calls.append(1) or ""
    recorded = []
    orig_record = review.record_request
    review.record_request = lambda r: recorded.append(r)

    out = identity._split_impossible_clusters([pos()])
    check(len(out) == 1 and ev.covers(out[0]) and out[0][ev.EVIDENCE_KEY]["method"] == ev.OPERATOR_REVIEW
          and out[0][ev.EVIDENCE_KEY]["request_id"] == POS, "W2 0097+0115 kept together with operator_review evidence for request 758fe778...")
    check(enforce_identity_gate(out)[0].get("_identity_gate") == "pass", "W2 the identity gate passes the owner-approved pair")

    recorded.clear()
    out = identity._split_impossible_clusters([neg()])
    check(len(out) == 2 and not recorded, "W3 0074+0151 REJECTED: split, no new review request")

    split = lambda c, reason: [dict(c, appearances=[a], description=c.get("description", "")) for a in c["appearances"]]
    saved_verify = ipc.verify_cluster
    ipc.verify_cluster = lambda cluster, ask: {"verdict": "MATCH", "reason": "", "pairs": [
        {"a": ev.member_key(x), "b": ev.member_key(y), "decision": "MATCH", "forward_sha256": "f", "backward_sha256": "b"}
        for i, x in enumerate(cluster["appearances"]) for y in cluster["appearances"][i + 1:]]}
    out = ipc.verify_multi_clusters([neg()], ask=lambda *a, **k: "", split_to_singles=split)
    check(len(out) == 2, f"W4 a model MATCH on 0074+0151 is overridden by the owner rejection ({len(out)} clusters)")

    sup = {"description": "x", "appearances": [app("0074", "a", 0), app("0151", "b", 1), app("0097", "c", 2)]}
    sup_rid = review.request_id(sup)
    data = json.loads(WORKING.read_text())
    data["decisions"].append({"request_id": sup_rid, "decision": "APPROVED", "reviewer": "contract", "decided_at": "2026-11-18T00:00:00Z"})
    alt = tmp / "decisions_with_superset.json"
    alt.write_text(json.dumps(data))
    os.environ[review.DECISIONS_ENV] = str(alt)
    sup_c = ev.stamp_operator_review(dict(sup), review.load_decisions()[sup_rid], request_id=sup_rid)
    out = ipc.verify_multi_clusters([sup_c], ask=lambda *a, **k: "", split_to_singles=split)
    check(len(out) == 3, f"W5 superset with an approval but a rejected pair inside -> split ({len(out)} clusters)")
    os.environ[review.DECISIONS_ENV] = str(WORKING)

    singles = [{"description": k, "appearances": [app(k, k, i)]} for i, k in enumerate(("0074", "0151", "0097", "0115"))]
    merged, rep = ipc.merge_verified_singletons(singles, ask=lambda *a, **k: "", max_pairs=45)
    together = [sorted(Path(a["path"]).name[39:43] for a in c["appearances"]) for c in merged]
    check(not any({"0074", "0151"} <= set(g) for g in together), f"W6 singleton merge never groups 0074 with 0151 ({together})")
    ipc.verify_cluster = saved_verify

    recorded.clear()
    o1 = identity._split_impossible_clusters([pair("0097", "surfer in dark swimsuit", "0151", "surfer with no shirt")])
    o2 = identity._split_impossible_clusters([pair("0115", "surfer with no shirt", "0074", "surfer in a black wetsuit top")])
    check(len(o1) == 2 and len(o2) == 2 and len(recorded) == 2 and all(r["status"] == "PENDING" for r in recorded),
          "W7 the 0097+0115 approval does not extend to 0097+0151 or 0115+0074 (both PENDING requests)")

    os.environ.pop("SPORTREEL_QUALIFICATION_RUN_ID")
    out = identity._split_impossible_clusters([pos()])
    check(len(out) == 2 and review.load_decisions() == {}, "W8 outside a qualification run the working file is ignored (pair stays split, PENDING)")
    check(not (ROOT / "evaluation" / "identity_reviews" / "decisions.json").exists(),
          "W9 no production decision file in the repository (promotion is a separate owner action)")

    review.record_request = orig_record
    identity._consensus_ask = saved_ask
    os.environ.pop(review.DECISIONS_ENV, None)
    check(not calls, "no model call on any path")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
