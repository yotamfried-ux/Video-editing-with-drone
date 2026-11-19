#!/usr/bin/env python3
"""FIX-PQ-14-003: the identity sheet size must survive the MODEL-clustering path, or no multi-source cluster is ever
visually verified.

Root cause (runs q10p, q12p, 44388634790 - every warm run since the 6-crop rule): identity sheets were built with 6
tracked crops (identity_trace: 25/25 `track_bbox_sheet`, crops 6), but `_resolve_model_appearance` built its entry
without `sheet_crops`, so every model-clustered appearance carried `_sheet_crops = 0`. identity_pair_consensus then
returned REVIEW "identity_sheet_has_fewer_than_6_crops" for 5/5 multi-source clusters WITHOUT any pairwise check:
correct same-athlete reels were withheld (6c84 x5, 8b1c 0160+0163, 144c 0070+0108, 9524 x5) and the 0143+0152
lookalike pair was never examined. Every existing identity test hand-built appearances with `_sheet_crops: 6`.

M1  production path: clip analyses (persons with a real 6-crop identity_evidence) -> model cluster data ->
    identity._build_clusters_from_data (fail-safe wrapper installed, as in production) -> appearances carry 6
M2  that cluster reaches the pairwise verifier: MATCH answers -> MATCH with pairs (not the thin-sheet REVIEW);
    NO_MATCH answers -> NO_MATCH (the lookalike can be split)
M3  fail-closed is preserved: a person whose sheet really has 4 crops (or none) -> REVIEW thin-sheet, no model call
M4  the unwrapped core resolver carries the same value (both code paths)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import _consensus_fixture as fx  # noqa: E402
from pipeline import identity_failsafe  # noqa: E402
from pipeline import identity_pair_consensus as pc  # noqa: E402
from pipeline.stages import identity  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def analyses(tmp: str, crops: list[int]) -> list[dict]:
    out = []
    for i, n in enumerate(crops):
        thumb = Path(tmp) / f"sheet_{i}.jpg"
        thumb.write_bytes(b"\xff\xd8\xff" + bytes([i]) * 32)
        evidence = {"kind": "track_bbox_sheet", "crops": n, "track_ids": [str(10000 + i)]} if n else {"kind": "none"}
        out.append({"path": f"/tmp/dtor/SRC_{i}_D.MP4", "analysis": {"persons": [{
            "id": "person_A", "description": "surfer on a blue board", "thumbnail": str(thumb),
            "identity_evidence": evidence,
            "events": [{"type": "wave_catch", "person_id": "person_A", "start": 1.0, "end": 8.0, "score": 9,
                        "target_track_id": str(10000 + i), "bbox_xyxy": [10, 10, 60, 120], "visible_ratio": 1.0}]}]}})
    return out


def model_data(n: int) -> dict:
    return {"clusters": [{"description": "surfer on a blue board", "confidence": "high",
                          "appearances": [{"clip_index": i, "person_id": "person_A"} for i in range(n)]}]}


def main() -> int:
    calls = []

    def counting(answer):
        def ask(prompt, images):
            calls.append(1)
            return answer
        return ask

    identity_failsafe.install()
    with tempfile.TemporaryDirectory() as tmp:
        ca = analyses(tmp, [6, 6])
        clusters = identity._build_clusters_from_data(model_data(2), ca)
        crops = [a.get("_sheet_crops") for c in clusters for a in c["appearances"]]
        check(len(clusters) == 1 and crops == [6, 6], f"M1 production model path keeps the sheet size: {crops}")
        if clusters:
            match = pc.verify_cluster(clusters[0], counting(fx.MATCH_SPECIFIC))
            check(match["verdict"] == "MATCH" and match["pairs"] and calls,
                  f"M2 verified pair reaches the verifier: {match['verdict']} {match.get('reason')}")
            diff = pc.verify_cluster(clusters[0], fx.ask_with(fx.NO_MATCH))
            check(diff["verdict"] == "NO_MATCH", f"M2 a different-athlete pair can be split: {diff['verdict']}")
        calls.clear()
        thin = identity._build_clusters_from_data(model_data(2), analyses(tmp, [6, 4]))
        none = identity._build_clusters_from_data(model_data(2), analyses(tmp, [6, 0]))
        rt = pc.verify_cluster(thin[0], counting(fx.MATCH_SPECIFIC)) if thin else {}
        rn = pc.verify_cluster(none[0], counting(fx.MATCH_SPECIFIC)) if none else {}
        check(rt.get("verdict") == "REVIEW" and "fewer_than_6" in rt.get("reason", "")
              and rn.get("verdict") == "REVIEW" and not calls,
              f"M3 a real 4-crop / no sheet stays REVIEW without a model call: {rt.get('reason')} / {rn.get('reason')}")
        entry = identity._resolve_model_appearance({"clip_index": 0, "person_id": "person_A"}, ca)
        check(entry is not None and entry.get("sheet_crops") == 6, f"M4 core resolver carries sheet_crops: {entry and entry.get('sheet_crops')}")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
