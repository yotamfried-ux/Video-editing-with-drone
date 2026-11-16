#!/usr/bin/env python3
"""Evidence level of frozen Ground Truth (RC-10): what each kind of label can and cannot prove. Read-only.

Levels, from weakest: SUGGESTED (model box, no review), MARKED_VERIFIED (a status set without recorded reviewer and
time), ATTRIBUTED_VERIFIED (verified_by and verified_at recorded), ADJUDICATED (a second, blind reviewer). Only
ATTRIBUTED_VERIFIED or better may support a claim of per-frame tracker accuracy; anything else is UNVERIFIED_GT for
that purpose. Segment decisions (include/exclude) are the video-level approval and are reported separately.

usage: gt_evidence_levels.py FROZEN_DATASET_EXPORT.json
"""
from __future__ import annotations

import json
import sys
from typing import Any


def keyframe_level(k: dict[str, Any]) -> str:
    if k.get("adjudicated_by") and k.get("adjudicated_at"):
        return "ADJUDICATED"
    if k.get("verified_by") and k.get("verified_at") and k.get("verification_status") == "verified_correct":
        return "ATTRIBUTED_VERIFIED"
    if k.get("verification_status") == "verified_correct":
        return "MARKED_VERIFIED"
    return "SUGGESTED" if k.get("origin") == "suggested" else "UNREVIEWED"


def classify(dataset: dict[str, Any]) -> dict[str, Any]:
    levels: dict[str, int] = {}
    origins: dict[str, int] = {}
    segments = {"include": 0, "exclude": 0}
    for member in dataset.get("members", []) or []:
        content = member.get("content")
        content = json.loads(content) if isinstance(content, str) else (content or {})
        for k in content.get("keyframes", []) or []:
            levels[keyframe_level(k)] = levels.get(keyframe_level(k), 0) + 1
            origins[str(k.get("origin"))] = origins.get(str(k.get("origin")), 0) + 1
        for s in content.get("segments", []) or []:
            if s.get("decision") in segments:
                segments[s["decision"]] += 1
    strong = levels.get("ATTRIBUTED_VERIFIED", 0) + levels.get("ADJUDICATED", 0)
    total = sum(levels.values())
    return {"keyframes": total, "levels": levels, "origins": origins, "segments": segments,
            "tracker_accuracy_claim": "SUPPORTED" if total and strong == total else "UNVERIFIED_GT",
            "strong_box_evidence_share": round(strong / total, 4) if total else None}


if __name__ == "__main__":
    print(json.dumps(classify(json.load(open(sys.argv[1], encoding="utf-8"))), indent=2))
