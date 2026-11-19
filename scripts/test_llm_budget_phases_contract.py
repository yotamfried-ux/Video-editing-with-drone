#!/usr/bin/env python3
"""MEM-04: analysis may not starve identity verification / final QA, and a budget-starved run never reads as done.

B1  cap $1.00, downstream reserve $0.35, $0.62 spent: an ANALYSIS call is refused (0.62+0.05 > 0.65) and recorded;
    a DOWNSTREAM (identity / QA) call is still allowed
B2  a downstream call is refused only at the full cap, and recorded with its phase
B3  reserve 0 = the previous single-cap behaviour
B4  integrations.gemini passes the calling step's label into the budget check (phase is decided per call)
B5  batch verdict: downstream refusals -> execution INCOMPLETE + product INCOMPLETE_QA (unjudged, not a failure);
    analysis-only refusals -> INCOMPLETE; no refusal -> unchanged (SUCCESS / FAIL)
B6  replay of cold run 44374982006 (42 recorded budget refusals, all 15 parts without QA): RED with the previous
    verdict (execution SUCCESS / product FAIL), GREEN INCOMPLETE / INCOMPLETE_QA  [uses the run's manifest when its
    diagnostics are present locally; otherwise a synthetic manifest with the same shape]
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mem04-"))
    os.environ["TMP_DIR"] = str(tmp)
    (tmp / "pipeline-debug").mkdir()
    os.environ.pop("SPORTREEL_QUALIFICATION_RUN_ID", None)
    from integrations import qualification as q

    def spent(usd):
        (tmp / "pipeline-debug" / "llm_cost_calls.jsonl").write_text(json.dumps({"cost_usd": usd}) + "\n")

    def allowed(label):
        try:
            q.check_llm_budget(label)
            return True
        except q.LlmBudgetExceeded:
            return False

    os.environ.update(SPORTREEL_LLM_BUDGET_USD="1.0", SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD="0.35")
    spent(0.62)
    a = allowed("analyzer._gemini_call_session")
    d = allowed("analyzer.qa_check_reel")
    rows = [json.loads(l) for l in open(q.refusals_path())] if os.path.exists(q.refusals_path()) else []
    check(a is False and d is True and rows and rows[-1]["phase"] == "analysis",
          f"B1 analysis refused at cap-reserve, downstream allowed, refusal recorded ({rows[-1] if rows else None})")
    spent(0.97)
    d2 = allowed("identity._gemini_call_cluster_visual")
    rows = [json.loads(l) for l in open(q.refusals_path())]
    check(d2 is False and rows[-1]["phase"] == "downstream", "B2 downstream refused only at the full cap, recorded as downstream")
    os.environ["SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD"] = "0"
    spent(0.62)
    check(allowed("analyzer._gemini_call_session") is True, "B3 reserve 0 keeps the single-cap behaviour")
    from integrations import gemini
    src = inspect.getsource(gemini)
    check("check_llm_budget(llm_cost.caller_label())" in src, "B4 gemini passes the calling step's label to the budget check")

    import write_batch_qualification as wbq
    manifest = {"pipeline_run_id": "r", "athletes": [{"athlete_key": f"a{i}", "eligible": True, "parts": [
        {"part_index": 1, "qa_verdict": "FAIL", "publishable": False,
         "output_qualification": {"product_state": "REVIEW_REQUIRED", "blocking": ["QA_REVIEW_REQUIRED"]}}]} for i in range(3)]}
    cov = {"summary": {"confirmed_athlete_cluster_count": 3, "covered_or_explicitly_explained_cluster_count": 3}}
    none = wbq.build(manifest, coverage=cov, exit_code=0, refusals=[])
    down = wbq.build(manifest, coverage=cov, exit_code=0, refusals=[{"phase": "downstream"}])
    ana = wbq.build(manifest, coverage=cov, exit_code=0, refusals=[{"phase": "analysis"}])
    check(none["execution_state"] == "SUCCESS" and none["product_state"] == "FAIL"
          and down["execution_state"] == "INCOMPLETE" and down["product_state"] == "INCOMPLETE_QA"
          and ana["execution_state"] == "INCOMPLETE" and ana["product_state"] == "FAIL",
          f"B5 verdicts: none={none['execution_state']}/{none['product_state']} downstream={down['execution_state']}/"
          f"{down['product_state']} analysis={ana['execution_state']}/{ana['product_state']}")

    cold = Path(os.getenv("COLD_RUN_DIAGNOSTICS", "/nonexistent"))
    real = cold.joinpath("publishable_reel_manifest.json").exists()
    m = json.loads(cold.joinpath("publishable_reel_manifest.json").read_text()) if real else manifest
    c = json.loads(cold.joinpath("athlete_coverage_report.json").read_text()) if real else cov
    refusals = [{"phase": "unknown"}] * 42
    before = wbq.build(m, coverage=c, exit_code=0, refusals=[])
    after = wbq.build(m, coverage=c, exit_code=0, refusals=refusals)
    check(before["execution_state"] == "SUCCESS" and before["product_state"] == "FAIL"
          and after["execution_state"] == "INCOMPLETE" and after["product_state"] == "INCOMPLETE_QA",
          f"B6 cold run 44374982006 ({'real manifest' if real else 'synthetic shape'}): before {before['execution_state']}/"
          f"{before['product_state']} -> after {after['execution_state']}/{after['product_state']}")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
