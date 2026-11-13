#!/usr/bin/env python3
"""Replay the identity rule engine on a run's per-person descriptions and score it against the manual catalog.

Input: docs/evidence/run-<id>-identity-descriptions.json (source, person, analyzer description, catalog athlete).
Every cross-source pair is judged by pipeline.identity_decision_engine on the descriptions alone (no tracks):

- false split: two persons the catalog calls one athlete, and the engine says a hard conflict (the cluster is split
  before the reel and the visual merge check never sees the pair);
- false match: two persons the catalog calls different athletes, and the engine says MATCH.

Usage: python3 scripts/eval_identity_vs_catalog.py [fixture.json] [--json]
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The reasons pipeline.stages.identity splits a cluster on before any visual check; other NO_MATCH reasons
# ("insufficient_identity_similarity") are only a missing text match and still reach the visual merge check.
HARD_CONFLICTS = {"same_source_clip_conflict", "conflicting_jersey_or_bib_numbers", "companion_solo_vs_tandem_conflict",
                  "incompatible_swimwear_or_category", "wetsuit_vs_bare_or_swimsuit_conflict",
                  "conflicting_equipment_color", "rejected_by_semantic_or_visual_verifier"}
DEFAULT = ROOT / "docs" / "evidence" / "run-43303438106-identity-descriptions.json"


def evaluate(path: Path) -> dict:
    from pipeline.identity_decision_engine import IdentityDecisionEngine

    persons = json.loads(path.read_text(encoding="utf-8"))["persons"]
    engine = IdentityDecisionEngine()

    def app(p: dict) -> dict:
        key = f"DJI_{p['source']}_D.MP4"
        return {"path": key, "_clip_index": key, "_person_id": p["person"], "description": p["description"],
                "_description": p["description"], "events": [{"start": 2.0, "end": 9.0, "track_id": 10002}]}

    false_splits, false_matches, same_pairs, diff_pairs = [], [], 0, 0
    for a, b in itertools.combinations(persons, 2):
        if a["source"] == b["source"]:
            continue
        same = a["catalog_athlete"] == b["catalog_athlete"]
        decision = engine.evaluate_pair(app(a), app(b))
        row = {"pair": f"{a['source']}/{a['person']} + {b['source']}/{b['person']}", "catalog": a["catalog_athlete"] if same else
               f"{a['catalog_athlete']} vs {b['catalog_athlete']}", "decision": decision.decision, "reasons": decision.reasons}
        if same:
            same_pairs += 1
            if HARD_CONFLICTS & set(decision.reasons):
                false_splits.append(row)
        else:
            diff_pairs += 1
            if decision.decision == "MATCH":
                false_matches.append(row)
    return {"same_athlete_pairs": same_pairs, "different_athlete_pairs": diff_pairs,
            "false_splits": false_splits, "false_matches": false_matches}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    result = evaluate(Path(args[0]) if args else DEFAULT)
    if "--json" in sys.argv:
        print(json.dumps(result, indent=1))
        return 0
    print(f"same-athlete pairs: {result['same_athlete_pairs']}  false splits (hard NO_MATCH): {len(result['false_splits'])}")
    for r in result["false_splits"]:
        print(f"  SPLIT  {r['pair']}  [{r['catalog']}]  {r['reasons']}")
    print(f"different-athlete pairs: {result['different_athlete_pairs']}  false matches: {len(result['false_matches'])}")
    for r in result["false_matches"]:
        print(f"  MATCH  {r['pair']}  [{r['catalog']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
