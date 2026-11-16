"""Shared fixture: pairwise-consensus evidence produced with an injected fake verifier (no model, no media)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MATCH_SPECIFIC = json.dumps({"verdict": "MATCH", "matching_features": ["red board with white stripe", "blue rash guard"],
                             "contradicting_features": [], "generic_only": False})
MATCH_GENERIC = json.dumps({"verdict": "MATCH", "matching_features": ["pink board", "dark shorts"],
                            "contradicting_features": [], "generic_only": True})
NO_MATCH = json.dumps({"verdict": "NO_MATCH", "matching_features": [], "generic_only": False,
                       "contradicting_features": ["different board colour"]})
UNCERTAIN = json.dumps({"verdict": "UNCERTAIN", "matching_features": [], "contradicting_features": []})


def ask_with(answer: str):
    return lambda prompt, images: answer


def prove(cluster: dict, ask=None, *, image: str | None = None) -> dict:
    """A real pairwise verification of the cluster's current members through `verify_cluster` + `stamp_pairwise`."""
    from pipeline import identity_evidence as ev
    from pipeline import identity_pair_consensus as pc
    image = image or str(Path(__file__).resolve())
    for app in cluster["appearances"]:
        app.setdefault("thumbnail", image)
    result = pc.verify_cluster(cluster, ask or ask_with(MATCH_SPECIFIC))
    keys = [ev.member_key(a) for a in cluster["appearances"]]
    return ev.stamp_pairwise(cluster, result["pairs"], model="test-verifier",
                             member_images={k: a["thumbnail"] for k, a in zip(keys, cluster["appearances"])})
