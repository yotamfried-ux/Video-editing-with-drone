#!/usr/bin/env python3
"""RC-10: box labels without a recorded reviewer and time never support a per-frame tracker accuracy claim.

Fixture mirrors frozen GT-v1 (read 2026-11-16): 3,174 keyframes, 3,083 suggested + 91 manual, 3,173 marked
verified_correct, none with verified_by / verified_at; 42 include and 3 exclude segments.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gt_evidence_levels import classify  # noqa: E402

marked = [{"origin": "suggested", "verification_status": "verified_correct"}] * 3082
manual = [{"origin": "manual", "verification_status": "verified_correct"}] * 91
gtv1 = {"members": [{"content": {"keyframes": marked + manual + [{"origin": "suggested", "verification_status": "occluded"}],
                                 "segments": [{"decision": "include"}] * 42 + [{"decision": "exclude"}] * 3}}]}
r = classify(gtv1)
assert r["tracker_accuracy_claim"] == "UNVERIFIED_GT", r
assert r["levels"] == {"MARKED_VERIFIED": 3173, "SUGGESTED": 1}, r
assert r["segments"] == {"include": 42, "exclude": 3}, r
attributed = {"members": [{"content": {"keyframes": [{"origin": "manual", "verification_status": "verified_correct",
                                                      "verified_by": "reviewer-1", "verified_at": "2026-11-16T00:00:00Z"}]}}]}
assert classify(attributed)["tracker_accuracy_claim"] == "SUPPORTED"
mixed = {"members": [{"content": {"keyframes": attributed["members"][0]["content"]["keyframes"] + marked[:1]}}]}
assert classify(mixed)["tracker_accuracy_claim"] == "UNVERIFIED_GT", "one unattributed box keeps the claim unverified"
print("PASS: GT evidence levels (unattributed verification is UNVERIFIED_GT)")
