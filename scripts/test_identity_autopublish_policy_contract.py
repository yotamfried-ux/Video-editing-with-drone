#!/usr/bin/env python3
"""Cycle 10 Gate B1 (FIX-PQ-10-001): a model's visual answer alone never makes a multi-source reel auto-publishable.

Root cause (EXP-09-002, run 44121013654): the pairwise verifier answered a both-orders, 6-crop MATCH for the 0143/0152
lookalikes (GT: two athletes); `real_identity_gate` turned that evidence into `pass` and the reel was publishable.
Agreement in both image orders does not help when the model is consistently wrong.

P1  multi-source cluster + valid pairwise_consensus evidence (model only) -> NOT pass: kept together UNCONFIRMED with
    reason visual_consensus_requires_operator_review (withheld; the existing identity review request applies).
P2  the same cluster with the owner's APPROVED operator_review evidence -> pass (a path to publication exists).
P3  single-source clusters and same-source stable tracks are untouched (no loss of single-source reels).
P4  the opt-in SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH=1 restores the old behaviour (for a future validated verifier only).
P5  tampered evidence still never passes.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline import identity_pair_consensus as pc  # noqa: E402
from pipeline.real_identity_gate import enforce_identity_gate  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


MATCH = json.dumps({"verdict": "MATCH", "matching_features": ["pink longboard with white rails", "white short-sleeve top"],
                    "contradicting_features": [], "generic_only": False})


def cluster(tmp: str, names: list[str], same_source: bool = False) -> dict:
    apps = []
    for i, n in enumerate(names):
        thumb = Path(tmp) / f"{n}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + n.encode())
        src = "/tmp/dtor/c0143.MP4" if same_source else f"/tmp/dtor/{n}.MP4"
        apps.append({"path": src, "_clip_index": 0 if same_source else i, "_person_id": f"person_{chr(65 + i)}",
                     "thumbnail": str(thumb), "_sheet_crops": 6,
                     "events": [{"type": "wave_catch", "start": 1.0, "end": 8.0, "track_id": "10001" if same_source else str(10001 + i)}]})
    return {"description": "Man in a white t-shirt on a pink surfboard", "appearances": apps}


def verified(c: dict) -> dict:
    out = pc.verify_multi_clusters([c], ask=lambda prompt, images: MATCH, split_to_singles=lambda cl, why: [cl])
    return out[0]


def gate(c: dict) -> dict:
    return enforce_identity_gate([c])[0]


def main() -> int:
    os.environ.pop("SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH", None)
    with tempfile.TemporaryDirectory() as tmp:
        c = verified(cluster(tmp, ["c0143", "c0152"]))
        check(ev.covers(c) and c[ev.EVIDENCE_KEY]["method"] == ev.PAIRWISE_CONSENSUS, "setup: model-only pairwise evidence covers the cluster")
        g = gate(c)
        check(g.get("_identity_gate") != "pass", f"P1 model-only evidence on a multi-source cluster is not a pass (got {g.get('_identity_gate')})")
        check(g.get("_identity_gate_reason") == "visual_consensus_requires_operator_review",
              f"P1 reason recorded ({g.get('_identity_gate_reason')})")
        check(all(e["identity_gate"]["decision"] != "pass" for a in g["appearances"] for e in a["events"]),
              "P1 no event carries a pass decision")

        c2 = cluster(tmp, ["c0097", "c0115"])
        c2 = ev.stamp_operator_review(c2, {"decision": "APPROVED", "reviewer": "owner", "decided_at": "2026-11-18T00:00:00Z"},
                                      request_id="a" * 64)
        check(gate(c2).get("_identity_gate") == "pass", "P2 owner-approved operator_review evidence passes")

        single = cluster(tmp, ["c0130"])
        check(gate(single) is not None and gate(single).get("_identity_gate") in (None, "pass"), "P3 single-source cluster untouched")
        same = cluster(tmp, ["c0143a", "c0143b"], same_source=True)
        check(gate(same).get("_identity_gate") == "pass", "P3 same-source stable track still passes")

        os.environ["SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH"] = "1"
        check(gate(verified(cluster(tmp, ["d0143", "d0152"]))).get("_identity_gate") == "pass", "P4 explicit opt-in restores the old pass")
        os.environ.pop("SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH")

        t = verified(cluster(tmp, ["e0143", "e0152"]))
        t[ev.EVIDENCE_KEY]["members"] = list(reversed(t[ev.EVIDENCE_KEY]["members"]))
        check(gate(t).get("_identity_gate") != "pass", "P5 tampered evidence never passes")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
