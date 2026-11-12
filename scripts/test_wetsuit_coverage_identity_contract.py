#!/usr/bin/env python3
"""A long-sleeved wetsuit top and a full black wetsuit are different coverage: 0074 and 0151 are two athletes.

#360 made "surfer in a black long-sleeved wetsuit top and dark shorts" (0074) and "surfer in a black wetsuit"
(0151) compatible on a reported operator confirmation that they were one surfer. The manual catalog
(ground_truth, the source of truth) has two athletes: 0074 "black clothing, white shorts, blond" and 0151 "shorts
with a black shirt". Run 43203677423 then cut 0151 into 0074's reel, and the reel was QA-blocked
(PRIMARY_ACTOR_UNCLEAR on the 0151 clip).

1. The pair is a hard identity conflict again: the engine says NO_MATCH, a cluster holding both is split before
   visual verification, and the visual merge check never sees the pair.
2. Coverage that really differs (shirtless, bikini, sleeveless, t-shirt) stays a hard conflict.
3. Coverage that is the same label stays compatible.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path: str, description: str) -> dict:
    return {"path": path, "_clip_index": path, "_person_id": "person_A", "description": description,
            "_description": description, "events": [{"start": 2.0, "end": 9.0, "track_id": 10002}]}


def main() -> int:
    from pipeline.identity_decision_engine import IdentityDecisionEngine
    from pipeline.stages.identity import (
        _merge_check_pairs, _sleeve_styles_compatible, _split_impossible_clusters, extract_structured_attributes)

    a = "surfer in a black long-sleeved wetsuit top and dark shorts on a white surfboard"
    b = "surfer in a black wetsuit on a white surfboard"
    styles = (extract_structured_attributes(a).get("sleeve_style"), extract_structured_attributes(b).get("sleeve_style"))
    if styles != ("long_sleeve", "full_wetsuit"):
        raise SystemExit(f"fixture no longer exercises the parser case, got {styles}")
    engine = IdentityDecisionEngine()
    decision = engine.evaluate_pair(app("DJI_0074_D.MP4", a), app("DJI_0151_D.MP4", b))
    if decision.decision != "NO_MATCH":
        raise SystemExit(f"catalog: 0074 and 0151 are two athletes, the engine must not match them: {decision.decision} {decision.reasons}")

    cluster = {"description": "man in a black long-sleeved wetsuit top on a white surfboard", "confidence": "high",
               "appearances": [app("DJI_0074_D.MP4", a), app("DJI_0151_D.MP4", b)]}
    if len(_split_impossible_clusters([cluster])) != 2:
        raise SystemExit("a 0074 + 0151 cluster must be split before it reaches the reel")
    left = {"description": "Man in a black long-sleeved wetsuit top on a white surfboard", "appearances": [app("DJI_0074_D.MP4", a)]}
    right = {"description": "Man in a black wetsuit on a white surfboard", "appearances": [app("DJI_0151_D.MP4", b)]}
    if _merge_check_pairs([left, right]):
        raise SystemExit("the visual merge check must not be offered the 0074/0151 pair")

    for one, other in (
        ("shirtless surfer in dark shorts on a white surfboard", b),
        ("surfer in a black bikini on a white surfboard", b),
        ("surfer in a black sleeveless top on a white surfboard", a),
        ("surfer in a white t-shirt on a white surfboard", a),
    ):
        d = engine.evaluate_pair(app("DJI_1_D.MP4", one), app("DJI_2_D.MP4", other))
        if d.decision != "NO_MATCH":
            raise SystemExit(f"real coverage conflict must stay NO_MATCH: {one!r} vs {other!r} -> {d.decision} {d.reasons}")
    if _sleeve_styles_compatible("long_sleeve", "full_wetsuit") or not _sleeve_styles_compatible("full_wetsuit", "full_wetsuit"):
        raise SystemExit("sleeve compatibility table is wrong")
    if not _sleeve_styles_compatible(None, "full_wetsuit"):
        raise SystemExit("an unknown sleeve style is no conflict")
    print(f"wetsuit coverage identity contract ok (0074 vs 0151 -> {decision.decision}, reasons={decision.reasons})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
