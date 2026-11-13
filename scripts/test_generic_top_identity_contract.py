#!/usr/bin/env python3
"""A top whose sleeves are not named is no contradiction of a described sleeve length (0070 / 0108, one athlete).

Run 43303438106 (main@041eadb) compared with the manual catalog (docs/evidence/run-43303438106-catalog-comparison.md):
the analyzer described 0070 as "surfer in grey long-sleeve top and reddish bottoms on a light blue longboard" and 0108
as "surfer in grey top on a turquoise surfboard". The catalog has one woman in both. The parser filed the first under
long_sleeve and the second under shirt_top, the engine ruled a hard wetsuit_vs_bare_or_swimsuit_conflict, the model's
own visual cluster was split before the reel, and the visual merge check never saw the pair: one athlete, two reels.

1. A description with no sleeve length ("grey top", "white shirt") is covered_top and is compatible with a long-sleeved
   top, a t-shirt and another unnamed top.
2. Real differences stay hard conflicts: shirtless, sleeveless, swimwear, a full wetsuit, a t-shirt against long sleeves.
3. The replay of the run's descriptions against the catalog (scripts/eval_identity_vs_catalog.py) has no false split.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def app(path: str, description: str) -> dict:
    return {"path": path, "_clip_index": path, "_person_id": "person_A", "description": description,
            "_description": description, "events": [{"start": 2.0, "end": 9.0, "track_id": 10002}]}


def main() -> int:
    from pipeline.identity_decision_engine import IdentityDecisionEngine
    from pipeline.stages.identity import (
        _sleeve_styles_compatible, _split_impossible_clusters, extract_structured_attributes)
    import eval_identity_vs_catalog as replay

    a = "surfer in grey long-sleeve top and reddish bottoms on a light blue longboard"  # 0070
    b = "surfer in grey top on a turquoise surfboard"  # 0108
    styles = tuple(extract_structured_attributes(d).get("sleeve_style") for d in (a, b))
    if styles != ("long_sleeve", "covered_top"):
        raise SystemExit(f"fixture no longer exercises the parser case, got {styles}")
    if extract_structured_attributes("man in a white t-shirt on a white surfboard").get("sleeve_style") != "shirt_top":
        raise SystemExit("a t-shirt is a short-sleeved top, not an unnamed one")

    engine = IdentityDecisionEngine()
    decision = engine.evaluate_pair(app("DJI_0070_D.MP4", a), app("DJI_0108_D.MP4", b))
    if "wetsuit_vs_bare_or_swimsuit_conflict" in decision.reasons:
        raise SystemExit(f"catalog: 0070 and 0108 are one woman, an unnamed top is no sleeve conflict: {decision.reasons}")

    cluster = {"description": "Woman in a grey long-sleeve swimsuit on a light blue longboard.", "confidence": "high",
               "appearances": [app("DJI_0070_D.MP4", a), app("DJI_0108_D.MP4", b)]}
    if len(_split_impossible_clusters([cluster])) != 1:
        raise SystemExit("the model's 0070 + 0108 cluster must not be split on an unnamed top")

    for one, other in (
        ("shirtless surfer in dark shorts on a turquoise surfboard", b),
        ("surfer in a black bikini on a turquoise surfboard", b),
        ("surfer in a black sleeveless top on a turquoise surfboard", b),
        ("surfer in a black wetsuit on a turquoise surfboard", b),
        ("surfer in a white t-shirt on a turquoise surfboard", a),
    ):
        d = engine.evaluate_pair(app("DJI_1_D.MP4", one), app("DJI_2_D.MP4", other))
        if d.decision != "NO_MATCH":
            raise SystemExit(f"real coverage conflict must stay NO_MATCH: {one!r} vs {other!r} -> {d.decision} {d.reasons}")
    table = {
        ("covered_top", "long_sleeve"): True, ("covered_top", "shirt_top"): True, ("covered_top", "covered_top"): True,
        ("covered_top", "full_wetsuit"): False, ("covered_top", "sleeveless"): False,
        ("covered_top", "shirtless"): False, ("covered_top", "swimwear"): False,
        ("long_sleeve", "shirt_top"): False, ("long_sleeve", "full_wetsuit"): False,
    }
    for (x, y), want in table.items():
        if _sleeve_styles_compatible(x, y) is not want or _sleeve_styles_compatible(y, x) is not want:
            raise SystemExit(f"sleeve compatibility {x} / {y} should be {want}")

    result = replay.evaluate(replay.DEFAULT)
    if result["false_splits"]:
        raise SystemExit(f"run 43303438106 descriptions still hard-split a catalogued athlete: {result['false_splits']}")
    print(f"generic top identity contract ok (0070 vs 0108 -> {decision.decision}, "
          f"{result['same_athlete_pairs']} catalogued same-athlete pairs, {len(result['false_splits'])} false splits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
