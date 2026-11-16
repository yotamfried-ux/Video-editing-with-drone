#!/usr/bin/env python3
"""batch_qualification.json keeps execution success and product success apart (RC-07, T10).

 BQ1 every eligible athlete verified and none unaccounted -> PASS; some -> PARTIAL; none -> FAIL.
 BQ2 a successful execution with withheld athletes is PARTIAL, never PASS.
 BQ3 a missing manifest or coverage report is BLOCKED, never PASS.
 BQ4 a part whose publishable flag was forged (proof does not verify) is not counted as verified.
 BQ5 an athlete whose shots are all INVALID is HARD_REJECTED; unaccounted athletes keep PASS away.
"""
from __future__ import annotations

import copy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))

from _qualification_fixture import qualified  # noqa: E402
from pipeline.output_qualification import build_inputs  # noqa: E402
from pipeline.publishable_reel_policy import _refresh_row_publishability  # noqa: E402
from write_batch_qualification import build  # noqa: E402


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def row(key: str, *, ok: bool = True, invalid: bool = False) -> dict:
    event = qualified({"type": "wave_catch", "start": 1.0, "end": 8.0, "score": 8, "description": "rides"})
    if invalid:
        event["description"] = "failed takeoff, never stood up"
    elif not ok:
        event["athlete_activity_state"] = None
    part = {"part_index": 1, "render_ready": True, "uploaded_to_review": True, "upload_error": None,
            "review_draft_name": f"{key}.mp4", "qa_evidence_recorded": True, "qa_verdict": "PASS", "qa_passed": True,
            "technical_issues": [], "content_sha256": "1" * 64, "content_sha256_kind": "bytes",
            "qualification_inputs": build_inputs([event], "surfing")}
    r = {"athlete_key": key, "eligible": True, "parts": [part]}
    _refresh_row_publishability(r)
    return r


COVERED = {"summary": {"confirmed_athlete_cluster_count": 3, "covered_or_explicitly_explained_cluster_count": 3}}


def main() -> int:
    good = build({"athletes": [row("a"), row("b")]}, coverage=COVERED, exit_code=0)
    check(good["product_state"] == "PASS" and good["execution_state"] == "SUCCESS", f"BQ1: {good['product_state']}")
    partial = build({"athletes": [row("a"), row("b", ok=False)]}, coverage=COVERED, exit_code=0)
    check(partial["product_state"] == "PARTIAL" and partial["execution_state"] == "SUCCESS",
          f"BQ2: a withheld athlete must make a successful execution PARTIAL: {partial['product_state']}")
    check(partial["counts"]["quarantined_athlete_count"] == 1 and partial["unresolved_critical"],
          "BQ2: the withheld athlete must be listed as unresolved")
    none = build({"athletes": [row("a", ok=False)]}, coverage=COVERED, exit_code=0)
    check(none["product_state"] == "FAIL", f"BQ1: no verified athlete must be FAIL: {none['product_state']}")
    check(build(None, coverage=COVERED, exit_code=0)["product_state"] == "BLOCKED", "BQ3: missing manifest passed")
    check(build({"athletes": [row("a")]}, coverage=None, exit_code=0)["product_state"] == "BLOCKED",
          "BQ3: missing athlete accounting passed")
    forged = row("a", ok=False)
    forged["parts"][0]["publishable"] = True
    forged["parts"][0]["output_qualification"] = copy.deepcopy(row("z")["parts"][0]["output_qualification"])
    forged["parts"][0]["output_qualification"]["events"] = []
    out = build({"athletes": [forged]}, coverage=COVERED, exit_code=0)
    check(out["counts"]["verified_publishable_athlete_count"] == 0, "BQ4: a forged publishable part was verified")
    rejected = build({"athletes": [row("a"), row("x", invalid=True)]}, coverage=COVERED, exit_code=0)
    check(rejected["counts"]["hard_rejected_athlete_count"] == 1 and rejected["product_state"] == "PARTIAL",
          f"BQ5: an all-INVALID athlete must be HARD_REJECTED: {rejected['counts']}")
    gap = build({"athletes": [row("a")]}, coverage={"summary": {"confirmed_athlete_cluster_count": 2,
                                                                 "covered_or_explicitly_explained_cluster_count": 1}},
                exit_code=0)
    check(gap["product_state"] == "PARTIAL" and gap["counts"]["unaccounted_athlete_count"] == 1,
          f"BQ5: an unaccounted athlete must keep PASS away: {gap['product_state']}")
    failed = build({"athletes": [row("a")]}, coverage=COVERED, exit_code=1)
    check(failed["execution_state"] == "FAILED", "execution failure must be reported separately")
    print("PASS: batch qualification separates execution from product state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
