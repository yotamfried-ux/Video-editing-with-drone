#!/usr/bin/env python3
"""Cycle 4: pairwise-consensus identity evidence at all three evidence-writing paths (injected fake verifier, no model).

C1  true pair, both orders specific MATCH -> pairwise evidence, the real identity gate passes it, also after
    `identity._strip_internal_fields` (the production hand-off).
C2  0143+0152-like lookalike: the old group prompt would answer "same person"; here a generic MATCH is REVIEW -> no
    evidence, the gate keeps the cluster together UNCONFIRMED (withheld). Same through the merge-check pair path.
C3  Forward MATCH / backward NO_MATCH (order bias), one-sided errors, empty answers -> REVIEW. Explicit contradiction in
    both orders -> the cluster is split.
C4  No transitive merge: A~B, B~C verified but A~C in doubt -> not stamped; all 3 pairs verified -> stamped; a 5-member
    cluster needs all 10 pairs.
C5  The legacy group-call route is dead: `stamp()` evidence (IMAGE_VERIFIER / PAIR_CHECK_SINGLETONS) never covers a
    multi-source cluster; the old group prompt is never sent by any verifier path; no file upload.
C6  member_key is stable before/after strip and independent of `_clip_index`; two members with one key are never covered.
C7  Evidence tampering (membership change, edited digest, missing order) -> not covered.
C8  Structural: ACCEPTED_METHODS == {pairwise_consensus, operator_review (owner decision)}; nothing but identity_evidence sets `_visual_verified = True`.
C9  A cluster whose verification was already stamped for exactly its members is not re-asked (no extra cost).
C10 A failure of the model call is REVIEW, not a split and not a merge.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import _consensus_fixture as fx  # noqa: E402
from pipeline import identity_evidence as ev  # noqa: E402
from pipeline import identity_pair_consensus as pc  # noqa: E402
from pipeline.real_identity_gate import enforce_identity_gate  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILURES: list[str] = []


def check(cond, msg):
    if not cond:
        FAILURES.append(msg)


def make(tmp: str, names: list[str]) -> dict:
    apps = []
    for i, name in enumerate(names):
        thumb = Path(tmp) / f"{name}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + name.encode())            # distinct bytes per member
        apps.append({"path": f"/tmp/dtor/{name}.MP4", "_clip_index": i, "_person_id": "person_A", "thumbnail": str(thumb),
                     "events": [{"type": "wave_catch", "person_id": "person_A", "start": 1.0, "end": 8.0,
                                 "track_id": str(10000 + i)}]})
    return {"description": "x", "appearances": apps}


def by_pair(answers: dict[frozenset, tuple[str, str]], default: str):
    """ask() that answers per (unordered) pair of images, and per image order (first image = forward)."""
    def ask(prompt, images):
        key = frozenset(img for img in images)
        forward = images[0] == sorted(images)[0]
        pair = answers.get(key)
        return (pair[0] if forward else pair[1]) if pair else default
    return ask


def run(verifier, clusters, ask):
    saved = identity._consensus_ask
    identity._consensus_ask = ask
    try:
        return verifier(clusters)
    finally:
        identity._consensus_ask = saved


def gate(clusters):
    return enforce_identity_gate(clusters)


def passed(out):
    return all(c.get("_identity_gate") == "pass" for c in out)


def paths():
    import pipeline.identity_failsafe as failsafe
    return (("stages.identity", identity._verify_multi_clusters),
            ("identity_failsafe", failsafe._wrap_verify_multi_clusters(identity)))


def c1():
    with tempfile.TemporaryDirectory() as tmp:
        for name, verifier in paths():
            out = run(verifier, [make(tmp, ["A_0097", "B_0115"])], fx.ask_with(fx.MATCH_SPECIFIC))
            check(len(out) == 1 and ev.covers(out[0]), f"C1 {name}: true pair must be stamped")
            check(out[0].get("_identity_evidence", {}).get("method") == "pairwise_consensus", f"C1 {name}: method")
            check(passed(gate(out)), f"C1 {name}: the identity gate must pass a consensus-verified pair")
            stripped = identity._strip_internal_fields(out)
            check(ev.covers(stripped[0]) and passed(gate(stripped)), f"C1 {name}: evidence must survive the strip")


def c2():
    with tempfile.TemporaryDirectory() as tmp:
        for name, verifier in paths():
            out = run(verifier, [make(tmp, ["A_0143", "B_0152"])], fx.ask_with(fx.MATCH_GENERIC))
            check(len(out) == 1 and not ev.covers(out[0]) and not out[0].get("_visual_verified"), f"C2 {name}: lookalike stamped")
            g = gate(out)
            check(g[0].get("_identity_gate") == "kept_together_unconfirmed", f"C2 {name}: gate {g[0].get('_identity_gate')}")
            g2 = gate(identity._strip_internal_fields(out))
            check(g2[0].get("_identity_gate") == "kept_together_unconfirmed", f"C2 {name}: stripped gate")
        # merge-check path (two singletons)
        s1, s2 = make(tmp, ["A_0143"]), make(tmp, ["B_0152"])
        saved = identity._consensus_ask
        identity._consensus_ask = fx.ask_with(fx.MATCH_GENERIC)
        try:
            merged = identity._verify_merge_candidates([s1, s2])
        finally:
            identity._consensus_ask = saved
        check(len(merged) == 2, "C2 merge-check: a generic lookalike must stay apart")


def c3():
    with tempfile.TemporaryDirectory() as tmp:
        cl = make(tmp, ["A_0097", "B_0115"])
        order_bias = lambda prompt, images: fx.MATCH_SPECIFIC if images[0] == b"\xff\xd8\xffA_0097" else fx.NO_MATCH
        for name, verifier in paths():
            reads = {}
            calls = []

            def ask(prompt, images, _calls=calls):
                _calls.append(len(images))
                # first call = forward (A first) says MATCH, second = backward says NO_MATCH
                return fx.MATCH_SPECIFIC if len(_calls) % 2 == 1 else fx.NO_MATCH
            out = run(verifier, [dict(cl)], ask)
            check(len(out) == 1 and not ev.covers(out[0]), f"C3 {name}: order disagreement must be REVIEW")
            out = run(verifier, [dict(cl)], fx.ask_with(""))
            check(len(out) == 1 and not ev.covers(out[0]), f"C3 {name}: empty answers must be REVIEW")
            out = run(verifier, [dict(cl)], fx.ask_with(fx.NO_MATCH))
            check(len(out) == 2 and not any(ev.covers(c) for c in out), f"C3 {name}: contradiction in both orders splits")

            def boom(prompt, images):
                raise RuntimeError("api down")
            out = run(verifier, [dict(cl)], boom)
            check(len(out) == 1 and not ev.covers(out[0]), f"C10 {name}: a model failure is REVIEW, not a merge or a split")


def c4():
    with tempfile.TemporaryDirectory() as tmp:
        cl = make(tmp, ["A", "B", "C"])
        keys = [ev.member_key(a) for a in cl["appearances"]]
        imgs = {k: a["thumbnail"] for k, a in zip(keys, cl["appearances"])}
        data = {k: Path(imgs[k]).read_bytes() for k in keys}
        ac = frozenset((data[keys[0]], data[keys[2]]))
        doubt = by_pair({ac: (fx.UNCERTAIN, fx.UNCERTAIN)}, fx.MATCH_SPECIFIC)
        for name, verifier in paths():
            out = run(verifier, [dict(cl)], doubt)
            check(len(out) == 1 and not ev.covers(out[0]), f"C4 {name}: A~B, B~C verified but A~C in doubt must NOT merge")
            check(gate(out)[0].get("_identity_gate") == "kept_together_unconfirmed", f"C4 {name}: gate")
            out = run(verifier, [dict(cl)], fx.ask_with(fx.MATCH_SPECIFIC))
            check(len(out) == 1 and ev.covers(out[0]) and len(out[0]["_identity_evidence"]["pairwise"]) == 3,
                  f"C4 {name}: all 3 pairs verified must stamp 3 edges")
        five = make(tmp, ["a", "b", "c", "d", "e"])
        out = run(identity._verify_multi_clusters, [five], fx.ask_with(fx.MATCH_SPECIFIC))
        check(ev.covers(out[0]) and len(out[0]["_identity_evidence"]["pairwise"]) == 10, "C4: 5 members need all 10 pairs")
        d = {k: Path(a["thumbnail"]).read_bytes() for k, a in zip([ev.member_key(x) for x in five["appearances"]], five["appearances"])}
        ks = list(d)
        one_bad = by_pair({frozenset((d[ks[1]], d[ks[4]])): (fx.UNCERTAIN, fx.MATCH_SPECIFIC)}, fx.MATCH_SPECIFIC)
        out = run(identity._verify_multi_clusters, [make(tmp, ["a", "b", "c", "d", "e"])], one_bad)
        check(not ev.covers(out[0]), "C4: one doubtful pair of ten must keep the whole cluster unconfirmed")


def c5():
    with tempfile.TemporaryDirectory() as tmp:
        for method in (ev.IMAGE_VERIFIER, ev.PAIR_CHECK_SINGLETONS):
            cl = make(tmp, ["A", "B"])
            image = cl["appearances"][0]["thumbnail"]
            ev.stamp(cl, method, images=[image, image], model="m", raw_response='{"same_person": true}')
            check(not ev.covers(cl) and ev.coverage_problem(cl) == "unaccepted_method", f"C5: legacy {method} evidence covers")
            check(gate([cl])[0].get("_identity_gate") == "kept_together_unconfirmed", f"C5: legacy {method} passed the gate")
        prompts = []

        def spy(prompt, images):
            prompts.append(prompt)
            return fx.MATCH_SPECIFIC
        uploads = []
        saved = identity.genai
        identity.genai = type("G", (), {"upload_file": lambda *a, **k: uploads.append(1), "delete_file": lambda *a, **k: None,
                                       "GenerativeModel": lambda *a, **k: (_ for _ in ()).throw(AssertionError("group call"))})()
        try:
            for name, verifier in paths():
                run(verifier, [make(tmp, ["A", "B"])], spy)
            identity._verify_merge_candidates  # noqa: B018
            run(lambda c: identity._verify_merge_candidates(c), [make(tmp, ["A"]), make(tmp, ["B"])], spy)
        finally:
            identity.genai = saved
        check(prompts and all(p == pc.M1_PROMPT for p in prompts), "C5: only the consensus prompt may be sent")
        check(not uploads, "C5: no Files API upload on any verifier path")
        src = (ROOT / "pipeline" / "stages" / "identity.py").read_text(encoding="utf-8")
        fail = (ROOT / "pipeline" / "identity_failsafe.py").read_text(encoding="utf-8")
        check("_VERIFY_PROMPT)" not in fail and "content.append(_VERIFY_PROMPT" not in src, "C5: group prompt still sent by a verifier")
        check("_MERGE_CHECK_PROMPT)" not in src, "C5: the single-order merge prompt is still sent")


def c6():
    with tempfile.TemporaryDirectory() as tmp:
        cl = make(tmp, ["A_0097", "B_0115"])
        before = [ev.member_key(a) for a in cl["appearances"]]
        stripped = identity._strip_internal_fields([cl])[0]
        after = [ev.member_key(a) for a in stripped["appearances"]]
        check(before == after, f"C6: key changed by the strip: {before} -> {after}")
        check(ev.member_key({"path": "/x/A.MP4", "_clip_index": 7, "_person_id": "p"}) == ev.member_key({"path": "/y/A.MP4", "events": [{"person_id": "p"}]}),
              "C6: key must not depend on _clip_index or the directory")
        dup = make(tmp, ["A", "A2"])
        dup["appearances"][1]["path"] = "/other/dir/A.MP4"          # same basename, other directory
        out = run(identity._verify_multi_clusters, [dup], fx.ask_with(fx.MATCH_SPECIFIC))
        check(not ev.covers(out[0]), "C6: two members with one key must never be covered")
        forced = fx.prove(make(tmp, ["A", "B"]))
        forced["appearances"][1]["path"] = "/other/A.MP4"
        check(ev.coverage_problem(forced) in {"ambiguous_member_keys", "evidence_does_not_cover_current_members"}, "C6: collision")


def c7():
    with tempfile.TemporaryDirectory() as tmp:
        good = fx.prove(make(tmp, ["A", "B"]))
        check(ev.covers(good), "C7 fixture")
        c = json.loads(json.dumps(good)); c["_identity_evidence"]["pairwise"][0]["verdict"] = "MATCH"; c["_identity_evidence"]["pairwise"][0]["backward_sha256"] = ""
        c["_identity_evidence"]["evidence_digest"] = ev._evidence_digest(c["_identity_evidence"])
        check(ev.coverage_problem(c) == "pair_not_examined_in_both_orders", f"C7 one order missing: {ev.coverage_problem(c)}")
        c = json.loads(json.dumps(good)); c["_identity_evidence"]["pairwise"][0]["forward_sha256"] = "0" * 64
        check(ev.coverage_problem(c) == "evidence_record_altered", "C7 digest edit")
        c = json.loads(json.dumps(good)); c["appearances"].append(make(tmp, ["Z"])["appearances"][0])
        check(not ev.covers(c), "C7 member added after verification")
        # stamp_pairwise refuses non-MATCH / incomplete results
        cl = make(tmp, ["A", "B"])
        keys = [ev.member_key(a) for a in cl["appearances"]]
        res = [{"a": keys[0], "b": keys[1], "decision": "REVIEW", "forward_sha256": "1" * 64, "backward_sha256": "2" * 64}]
        out = ev.stamp_pairwise(cl, res, model="m", member_images={k: a["thumbnail"] for k, a in zip(keys, cl["appearances"])})
        check(not ev.covers(out) and not out.get("_visual_verified"), "C7 stamp_pairwise must refuse a REVIEW pair")
        out = ev.stamp_pairwise(cl, [], model="m", member_images={})
        check(not ev.covers(out), "C7 stamp_pairwise must refuse a missing pair")


def c8():
    check(ev.ACCEPTED_METHODS == {ev.PAIRWISE_CONSENSUS, ev.OPERATOR_REVIEW}, f"C8 accepted methods {ev.ACCEPTED_METHODS}")
    # the owner's decision is the only other proof; it is covered by scripts/test_identity_review_contract.py
    writers = []
    for folder in ("pipeline", "integrations", "scripts"):
        for f in (ROOT / folder).rglob("*.py"):
            if f.name.startswith("test_") or f.name in {"_consensus_fixture.py"}:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if re.search(r"\[\s*[\"']_visual_verified[\"']\s*\]\s*=\s*True|_visual_verified\W+True\)", line) and "assert" not in line:
                    writers.append(f"{f.relative_to(ROOT)}:{n}")
    allowed = {"pipeline/identity_evidence.py", "pipeline/stages/identity.py"}   # stamp(s) and the strip copy
    bad = [w for w in writers if w.split(":")[0] not in allowed]
    check(not bad, f"C8: other writers of _visual_verified: {bad}")


def c9():
    with tempfile.TemporaryDirectory() as tmp:
        cl = fx.prove(make(tmp, ["A", "B"]))
        calls = []
        out = run(identity._verify_multi_clusters, [cl], lambda p, i: calls.append(1) or fx.MATCH_SPECIFIC)
        check(not calls and ev.covers(out[0]), "C9: an already covered cluster must not be re-asked")


for case in (c1, c2, c3, c4, c5, c6, c7, c8, c9):
    try:
        case()
    except Exception as exc:
        import traceback
        FAILURES.append(f"{case.__name__} crashed: {exc!r}\n{traceback.format_exc()[-600:]}")
if FAILURES:
    print("\n".join("FAIL " + f for f in FAILURES))
    sys.exit(1)
print("identity consensus integration contract: all cases passed")
