#!/usr/bin/env python3
"""A long-sleeved wetsuit top and a black wetsuit are not an identity conflict.

Runs 42814819534 and 42857524999: Gemini clustered 0074 ("surfer in a black long-sleeved wetsuit top and dark
shorts on a white surfboard") with 0151 ("surfer in a black wetsuit on a white surfboard"), and the operator
confirms they are the same surfer. IdentityDecisionEngine split them as a hard conflict
"wetsuit_vs_bare_or_swimsuit_conflict" only because the text parser labelled one long_sleeve and the other
full_wetsuit, and any label difference counted as a conflict. Real coverage conflicts must stay hard.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def app(path: str, description: str) -> dict:
    return {"path": path, "_person_id": "person_A", "description": description,
            "events": [{"start": 2.0, "end": 9.0, "track_id": 10002}]}


def main() -> int:
    from pipeline.identity_decision_engine import IdentityDecisionEngine
    from pipeline.stages.identity import _sleeve_styles_compatible, extract_structured_attributes

    a = "surfer in a black long-sleeved wetsuit top and dark shorts on a white surfboard"
    b = "surfer in a black wetsuit on a white surfboard"
    styles = (extract_structured_attributes(a).get("sleeve_style"), extract_structured_attributes(b).get("sleeve_style"))
    if styles != ("long_sleeve", "full_wetsuit"):
        raise SystemExit(f"fixture no longer exercises the parser case, got {styles}")
    engine = IdentityDecisionEngine()
    decision = engine.evaluate_pair(app("DJI_0074_D.MP4", a), app("DJI_0151_D.MP4", b))
    if "wetsuit_vs_bare_or_swimsuit_conflict" in decision.reasons or (decision.decision == "NO_MATCH" and decision.uncertainty == 0.0):
        raise SystemExit(f"a wetsuit top vs a wetsuit was a hard identity conflict: {decision.decision} {decision.reasons}")

    # The clustering pass that split the production cluster must now keep it for the visual verifier.
    from pipeline.stages.identity import _split_impossible_clusters

    cluster = {"description": "man in a black long-sleeved wetsuit top on a white surfboard", "confidence": "high",
               "appearances": [app("DJI_0074_D.MP4", a), app("DJI_0151_D.MP4", b)]}
    kept = _split_impossible_clusters([cluster])
    if len(kept) != 1 or len(kept[0].get("appearances") or []) != 2:
        raise SystemExit(f"the 0074 + 0151 cluster was split before visual verification: {len(kept)} cluster(s)")
    shirtless = {**cluster, "appearances": [app("DJI_0074_D.MP4", a), app("DJI_0097_D.MP4", "shirtless surfer in dark shorts on a white surfboard")]}
    if len(_split_impossible_clusters([shirtless])) != 2:
        raise SystemExit("a wetsuit vs shirtless cluster must still be split")

    # Coverage that really differs stays a hard conflict.
    for left, right in (
        ("shirtless surfer in dark shorts on a white surfboard", b),
        ("surfer in a black bikini on a white surfboard", b),
        ("surfer in a black sleeveless top on a white surfboard", a),
        ("surfer in a white t-shirt on a white surfboard", a),
    ):
        d = engine.evaluate_pair(app("DJI_1_D.MP4", left), app("DJI_2_D.MP4", right))
        if d.decision != "NO_MATCH":
            raise SystemExit(f"real coverage conflict must stay NO_MATCH: {left!r} vs {right!r} -> {d.decision} {d.reasons}")
    if not _sleeve_styles_compatible("long_sleeve", "full_wetsuit") or _sleeve_styles_compatible("shirtless", "full_wetsuit"):
        raise SystemExit("sleeve compatibility table is wrong")
    print(f"wetsuit coverage identity contract ok (0074 vs 0151 -> {decision.decision}, reasons={decision.reasons})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
