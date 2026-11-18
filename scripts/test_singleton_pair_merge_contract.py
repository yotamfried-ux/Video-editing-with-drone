#!/usr/bin/env python3
"""Singleton pair merge (PA-08, 0097+0115 split) — fake verifier, no model, no media.

 S1  RED on the old path: two single-source clusters of one athlete stay two clusters (verify_multi_clusters never
     sees the pair); GREEN: merge_verified_singletons merges them on a both-order MATCH and stamps pairwise evidence.
 S2  NO_MATCH or REVIEW (uncertain, error, thin sheet) -> no merge, clusters unchanged.
 S3  no transitive merge: A~B MATCH, B~C MATCH, A~C NO_MATCH -> at most one pair merged, never {A,B,C}.
 S4  three-way all-MATCH -> one group of three with evidence covering every member.
 S5  over the pair limit -> stage skipped, nothing merged; limit 0 disables.
 S6  multi-source clusters are not candidates (already verified by verify_multi_clusters).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _consensus_fixture import MATCH_SPECIFIC, NO_MATCH, UNCERTAIN  # noqa: E402
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline import identity_pair_consensus as pc  # noqa: E402

import tempfile
TMP = Path(tempfile.mkdtemp(prefix="singleton-merge-"))


def thumb_for(src: str) -> str:
    path = TMP / f"{src}.jpg"
    path.write_bytes(src.encode())          # the fake verifier reads the source name back from the bytes
    return str(path)
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def single(src, person, crops=6, thumb=None):
    return {"appearances": [{"path": f"/dtor/{src}.MP4", "_person_id": person, "thumbnail": thumb or thumb_for(src),
                             "_sheet_crops": crops, "events": [{"person_id": person}]}]}


class FakeImages:
    """Answer by which sources are compared: a dict {frozenset(src_a, src_b): answer}."""
    def __init__(self, table, default=NO_MATCH):
        self.table, self.default, self.calls = table, default, 0

    def __call__(self, prompt, images):
        self.calls += 1
        a, b = (img.decode() for img in images)
        return self.table.get(frozenset((a, b)), self.default)


def run(clusters, table, **kw):
    ask = FakeImages(table)
    return pc.merge_verified_singletons(clusters, ask=ask, model="test", **kw), ask


def main() -> int:
    a, b = single("0097", "person_A"), single("0115", "person_A")
    old = pc.verify_multi_clusters([a, b], ask=lambda p, i: MATCH_SPECIFIC, split_to_singles=lambda c, r: [c])
    check(len(old) == 2, "S1-red verify_multi_clusters keeps two single-source clusters apart (pair never proposed)")
    (out, rep), _ = run([single("0097", "person_A"), single("0115", "person_A")], {frozenset(("0097", "0115")): MATCH_SPECIFIC})
    check(len(out) == 1 and len(out[0]["appearances"]) == 2 and ev.covers(out[0]), f"S1 merged with covering evidence ({rep.get('merged_groups')})")
    for ans, name in ((NO_MATCH, "NO_MATCH"), (UNCERTAIN, "UNCERTAIN"), ("not json", "garbage")):
        (out, _), _ = run([single("0143", "p"), single("0152", "p")], {frozenset(("0143", "0152")): ans})
        check(len(out) == 2, f"S2 {name} -> no merge")
    (out, _), _ = run([single("0143", "p", crops=4), single("0152", "p", crops=4)], {frozenset(("0143", "0152")): MATCH_SPECIFIC})
    check(len(out) == 2, "S2 thin sheet (4 crops) -> REVIEW, no merge")
    t = {frozenset(("A", "B")): MATCH_SPECIFIC, frozenset(("B", "C")): MATCH_SPECIFIC, frozenset(("A", "C")): NO_MATCH}
    (out, rep), _ = run([single("A", "p"), single("B", "p"), single("C", "p")], t)
    sizes = sorted(len(c["appearances"]) for c in out)
    check(sizes in ([1, 2],) and max(sizes) < 3, f"S3 no transitive merge (sizes {sizes})")
    t = {frozenset(x): MATCH_SPECIFIC for x in (("A", "B"), ("B", "C"), ("A", "C"))}
    (out, _), _ = run([single("A", "p"), single("B", "p"), single("C", "p")], t)
    check(len(out) == 1 and len(out[0]["appearances"]) == 3 and ev.covers(out[0]), "S4 all-MATCH triple merged with full evidence")
    (out, rep), ask = run([single("A", "p"), single("B", "p"), single("C", "p")], t, max_pairs=2)
    check(len(out) == 3 and ask.calls == 0 and "over_limit" in rep["skipped"], f"S5 over limit skipped ({rep['skipped']})")
    (out, rep), ask = run([single("A", "p"), single("B", "p")], t, max_pairs=0)
    check(len(out) == 2 and ask.calls == 0, "S5 limit 0 disables")
    multi = {"appearances": single("X", "p")["appearances"] + single("Y", "p")["appearances"]}
    (out, rep), ask = run([multi, single("Z", "p")], {frozenset(("X", "Z")): MATCH_SPECIFIC, frozenset(("Y", "Z")): MATCH_SPECIFIC})
    check(len(out) == 2 and ask.calls == 0, "S6 multi-source cluster not a candidate")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
