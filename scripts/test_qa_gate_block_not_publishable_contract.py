#!/usr/bin/env python3
"""A draft its own QA gate blocks is never recorded as publishable.

Run 43583126199 (main@7d6b544), diagnostics artifact:
- "Silhouette of a surfer ...": qa_gate.decision = blocked_review_required, PRIMARY_ACTOR_UNCLEAR (critical, added
  by the subject gate after final QA) -> manifest and public.draft_publishability said publishable = true;
- "Tandem surfers ...": final verdict PASS with an always-blocking PREMATURE_CUT, gate blocked_review_required
  -> publishable = true.
Only the final-QA verdict reached the manifest; the gate's decision did not.

1. A PASS draft with a clean gate is publishable after upload (control).
2. The same draft with a blocked gate is recorded as not publishable, in the manifest and in the row written to
   draft_publishability, and the row carries the gate's reason.
3. qa_gate_block_reasons reads the three ways a gate says "blocked".
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qualification_fixture import qualify_map  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPECS = {"duration": 8.0, "width": 1080, "height": 1920, "aspect": 9 / 16, "has_audio": False, "fps": 30.0}
BLOCKED_GATE = {
    "decision": "blocked_review_required", "final_verdict": "PASS", "qa_review_required": True,
    "review_required_reasons": ["PREMATURE_CUT"],
    "approval_blocked_reasons": ["PREMATURE_CUT: The ride is cut before its natural completion"],
}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sportreel-gate-block-") as d:
        folder = Path(d)
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(folder / "manifest.json")
        from pipeline import publishable_reel_policy as policy
        from pipeline.publishable_qa_evidence import apply_final_qa_evidence, record_qa_result

        written: list[dict] = []
        policy._persist_draft_publishability = written.append
        policy.reset_manifest()

        if policy.qa_gate_block_reasons([{"qa_gate": {"decision": "passed", "approval_blocked_reasons": []}}]):
            raise SystemExit("a passed gate has no block reasons")
        for gate in (
            {"decision": "blocked_review_required"},
            {"decision": "passed", "qa_review_required": True},
            {"decision": "passed", "approval_blocked_reasons": ["PRIMARY_ACTOR_UNCLEAR: cannot be followed"]},
        ):
            if not policy.qa_gate_block_reasons([{"qa_gate": gate}]):
                raise SystemExit(f"a blocked gate must give a reason: {gate}")

        rows = {}
        for label, gate in (("clean surfer", None), ("tandem surfers", BLOCKED_GATE)):
            path = str(folder / f"{label.replace(' ', '_')}.mp4")
            Path(path).write_bytes(label.encode())
            event = {"start": 0, "end": 8, "type": "surf_ride", "athlete_id": label, "event_uid": f"ev2_{label.replace(' ', '_')}"}
            if gate:
                event["qa_gate"] = gate
            policy.record_athlete_outcome(
                sport="surfing", athlete_label=label, final_reels=[path],
                events_by_reel=qualify_map({path: [event]}), flagged_paths=set(), specs_by_path={path: SPECS})
            token = "gate-" + label
            record_qa_result(path, {"verdict": "PASS", "overall": "verified fixture"}, invocation_token=token)
            if apply_final_qa_evidence(sport="surfing", athlete_label=label, final_reels=[path], invocation_token=token):
                raise SystemExit("fixture: a PASS verdict must not be blocked by the evidence step")
            reasons = policy.qa_gate_block_reasons([event])
            if reasons:
                if not policy.mark_qa_gate_blocked(path, reasons):
                    raise SystemExit("the blocked draft was not found in the manifest")
            policy.mark_upload_result(path, f"DRAFT_{label}.mp4", storage_object_id=f"obj-{label}")
            rows[label] = path

        manifest = json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())
        parts = {r["athlete_label"]: r["parts"][0] for r in manifest["athletes"]}
        records = {r["draft_name"]: r for r in written}

        clean, blocked = parts["clean surfer"], parts["tandem surfers"]
        if clean["publishable"] is not True or records["DRAFT_clean surfer.mp4"]["publishable"] is not True:
            raise SystemExit(f"control: a PASS draft with a clean gate is publishable: {clean}")
        if blocked["publishable"] is not False:
            raise SystemExit(f"a gate-blocked draft is publishable in the manifest: {blocked}")
        record = records["DRAFT_tandem surfers.mp4"]
        if record["publishable"] is not False or record["qa_passed"] is not False:
            raise SystemExit(f"a gate-blocked draft was written to draft_publishability as publishable: {record}")
        if policy.QA_GATE_BLOCK_ISSUE not in record["technical_issues"]:
            raise SystemExit(f"the row must name the gate block: {record['technical_issues']}")
        if not any("PREMATURE_CUT" in reason for reason in record["approval_blocked_reasons"]):
            raise SystemExit(f"the row must carry the gate's reason: {record['approval_blocked_reasons']}")

    print("PASS: a QA-gate-blocked draft is not publishable (manifest and draft_publishability)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
