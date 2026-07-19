#!/usr/bin/env python3
"""Regression: final QA evidence is explicit, fail-closed, and invocation-scoped."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.publishable_pending_scope as pending_scope
import pipeline.publishable_qa_evidence as evidence
import pipeline.publishable_reel_policy as policy
import pipeline.silent_output_policy as silent

EVIDENCE_PATH = ROOT / "pipeline/publishable_qa_evidence.py"
PENDING_SCOPE_PATH = ROOT / "pipeline/publishable_pending_scope.py"


def specs() -> dict[str, Any]:
    return {
        "has_audio": False,
        "duration": 36.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }


def event() -> dict[str, Any]:
    return {
        "athlete_id": "athlete_qa_7",
        "type": "goal",
        "sport": "football",
        "start": 10.0,
        "end": 19.0,
        "score": 9,
        "_src": "match.mp4",
    }


def qa(verdict: str, score: int, overall: str) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "engagement_score": score,
        "overall": overall,
        "defects": [] if verdict == "PASS" else [{"type": "FRAMING", "severity": "minor"}],
    }


def read_athlete(manifest: Path) -> dict[str, Any]:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return payload["athletes"][0]


def main() -> int:
    policy.social_ready_issues = silent.silent_social_ready_issues
    pending_scope.install()

    # Two renders with the same human-readable identity must receive distinct tokens.
    pending_one = policy._pending_key("football", "player #7 in red")
    pending_two = policy._pending_key("football", "player #7 in red")
    if pending_one == pending_two:
        raise SystemExit("matching athlete labels reused one pending invocation token")
    active_one = pending_scope.activate_next_scope("football", "player #7 in red")
    if active_one != pending_one or policy._pending_key("football", "player #7 in red") != pending_one:
        raise SystemExit("the QA gate did not reactivate the matching render token")
    pending_scope.release_scope(active_one)
    active_two = pending_scope.activate_next_scope("football", "player #7 in red")
    if active_two != pending_two:
        raise SystemExit("pending render invocations were not consumed in order")
    pending_scope.release_scope(active_two)

    with tempfile.TemporaryDirectory(prefix="sportreel-qa-evidence-") as directory:
        tmp = Path(directory)
        manifest = tmp / "publishable_reel_manifest.json"
        reel = str(tmp / "athlete_primary.mp4")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(manifest)
        policy.reset_manifest()

        policy.record_athlete_outcome(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
            events_by_reel={reel: [event()]},
            flagged_paths=set(),
            specs_getter=lambda _path: specs(),
        )

        # An empty result bucket is not positive evidence. Missing model grading
        # must fail closed before upload.
        missing_token = "qa_missing_invocation"
        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
            invocation_token=missing_token,
        )
        if blocked != {reel}:
            raise SystemExit(f"missing QA evidence did not block the part: {blocked}")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_evidence_recorded") is not False:
            raise SystemExit("manifest did not explicitly record missing QA evidence")
        if part.get("qa_passed") is not False or part.get("render_ready") is not False:
            raise SystemExit("ungraded part remained render-ready")
        if "missing_final_qa_evidence" not in part.get("technical_issues", []):
            raise SystemExit("missing QA evidence reason was not persisted")
        if part.get("has_audio") is not False:
            raise SystemExit("QA fixture did not preserve the silent output contract")

        # Record conflicting results for the same athlete and local path under two
        # invocations. Applying PASS must not consume or overwrite the other FAIL.
        pass_token = "qa_pass_invocation"
        fail_token = "qa_fail_invocation"
        evidence.record_qa_result(reel, qa("PASS", 82, "Clear personal sports reel."), invocation_token=pass_token)
        evidence.record_qa_result(reel, qa("FAIL", 44, "Weak framing."), invocation_token=fail_token)

        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
            invocation_token=pass_token,
        )
        if blocked:
            raise SystemExit(f"recorded PASS remained blocked: {blocked}")
        if evidence.get_recorded_qa(reel, invocation_token=fail_token) is None:
            raise SystemExit("consuming PASS deleted another invocation's QA evidence")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_invocation_token") != pass_token:
            raise SystemExit("manifest did not retain the QA invocation identity")
        if part.get("qa_evidence_recorded") is not True or part.get("qa_verdict") != "PASS":
            raise SystemExit("positive QA evidence was not stored in the manifest")
        if part.get("qa_passed") is not True or part.get("render_ready") is not True:
            raise SystemExit("recorded PASS did not restore render readiness")
        if part.get("qa_engagement_score") != 82:
            raise SystemExit("QA score was not retained as evidence")

        blocked = evidence.apply_final_qa_evidence(
            sport="football",
            athlete_label="player #7 in red",
            final_reels=[reel],
            invocation_token=fail_token,
        )
        if blocked != {reel}:
            raise SystemExit("explicit QA FAIL did not block the part")
        part = read_athlete(manifest)["parts"][0]
        if part.get("qa_invocation_token") != fail_token:
            raise SystemExit("the FAIL invocation identity was not persisted")
        if part.get("qa_verdict") != "FAIL" or part.get("qa_passed") is not False:
            raise SystemExit("QA FAIL evidence was not persisted")
        if "final_qa_failed" not in part.get("technical_issues", []):
            raise SystemExit("QA FAIL reason was not persisted")

        keep_token = "qa_keep_invocation"
        clear_token = "qa_clear_invocation"
        evidence.record_qa_result(reel, qa("PASS", 80, "Keep me."), invocation_token=keep_token)
        evidence.record_qa_result(reel, qa("FAIL", 40, "Clear me."), invocation_token=clear_token)
        evidence.clear_recorded_qa(clear_token)
        if evidence.get_recorded_qa(reel, invocation_token=keep_token) is None:
            raise SystemExit("clearing one invocation deleted another invocation's evidence")
        if evidence.get_recorded_qa(reel, invocation_token=clear_token) is not None:
            raise SystemExit("invocation-scoped clear left its own evidence behind")
        evidence.clear_recorded_qa(keep_token)

    source = EVIDENCE_PATH.read_text(encoding="utf-8")
    pending_source = PENDING_SCOPE_PATH.read_text(encoding="utf-8")
    bootstrap = (ROOT / "pipeline/bootstrap.py").read_text(encoding="utf-8")
    run_tracked = (ROOT / "scripts/run_tracked.py").read_text(encoding="utf-8")
    required_source = [
        "qa_evidence_recorded",
        "missing_final_qa_evidence",
        "gate_with_required_evidence",
        "_QA_RESULTS_BY_INVOCATION",
        "consume_recorded_qa",
        "activate_next_scope",
        "install_pending_scope",
    ]
    missing = [token for token in required_source if token not in source]
    if missing:
        raise SystemExit(f"QA evidence runtime missing contract tokens: {missing}")
    if "_QA_RESULTS_BY_PATH" in source or "_QA_RESULTS_BY_INVOCATION.clear()" in source:
        raise SystemExit("QA evidence runtime still contains a process-global clear path")
    for token in ("uuid.uuid4", "contextvars.ContextVar", "create_pending_scope", "activate_next_scope"):
        if token not in pending_source:
            raise SystemExit(f"pending invocation scope missing token: {token}")
    if "pipeline.publishable_qa_evidence" not in bootstrap:
        raise SystemExit("shared bootstrap does not install explicit QA evidence")
    if "pipeline.silent_output_policy" not in bootstrap:
        raise SystemExit("shared bootstrap does not install the silent output policy")
    for token in (
        "from pipeline.bootstrap import install_post_orchestrator_patches, install_pre_orchestrator_patches",
        "install_pre_orchestrator_patches()",
        "install_post_orchestrator_patches()",
    ):
        if token not in run_tracked:
            raise SystemExit(f"production runner missing canonical bootstrap token: {token}")

    print("Invocation-scoped silent publishable final QA evidence contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
