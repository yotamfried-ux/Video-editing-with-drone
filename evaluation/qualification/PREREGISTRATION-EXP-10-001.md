# EXP-10-001 — paid isolated qualification run q10-paid-01 (pre-registered before launch)

Written and committed BEFORE the run. Success and failure conditions are fixed here and are not edited afterwards.

## Code under test
- Branch `ccr-3f12fc2f-pdvirt` (PR #391, draft). The run's head SHA is the commit that enables the paid budget (after Gate A passed, run 44148876075). Its
  pipeline code is `80fc677b` (= `5c79e59f` + the Gate A hook move into `pipeline/context_qa_gate.py`), plus this
  document, `run_config.json` and the Gate A evaluator. Verified after the run against the workflow
  run's `headSha`.
- Changes since cycle 9 (`f299a5a9`) under test:
  - **FIX-PQ-10-001** (`pipeline/real_identity_gate.py::_evidence_may_autopublish`): model-only pairwise consensus never
    makes a multi-source reel publishable.
  - **FIX-PQ-10-002** (`_stable_track`): clip index 0 is no longer treated as missing.
  - **FIX-PQ-10-003** (`pipeline/stages/identity.py::_text_attribute_split_reviewed`): a model-proposed grouping
    split only on text attributes records an owner review request.
  - **Gate A:** qualification-only fault hooks (inactive without `SPORTREEL_QUALIFICATION_FAULT`).
- Not changed: the reverted FIX-PQ-09-001/002 stay reverted. The pairwise verifier remains inactive on the
  model-clustering path, so no consensus calls are expected.

## Inputs
- **Batch:** `batch_2026-10-03T12-19-52_ttgvat95`, 24 verified sources (same SHA-256 as q9-paid-01/02):
  - 0070 `575a812d…`, 0074 `f6ac72f8…`, 0094 `250c3592…`, 0095 `6d57d383…`, 0097 `548cf4ff…`, 0104 `5f7ba69f…`
  - 0108 `3f1f5e84…`, 0112 `8a01bba4…`, 0115 `b62c8aa0…`, 0118 `58a990e5…`, 0126 `41e2f8bb…`, 0130 `a6835595…`
  - 0131 `c241b723…`, 0140 `82dd7349…`, 0142 `a1adfdae…`, 0143 `4e84086f…`, 0146 `2c7c9ee4…`, 0151 `e01a614d…`
  - 0152 `85aedb59…`, 0155 `a10e4151…`, 0160 `3095fb74…`, 0162 `207fe17c…`, 0163 `bfd005ab…`, 0165 `3311db2e…`
  - Full hashes are in cycle-9 diagnostics.
- **Ground truth:** GT-v1 `ae844a94`, digest `b31fd9b42bb248591f5a92c1aeadc7506c5bdf8826a5d392eff9e3f5e36927c9`. Used only
  after the run, for scoring.
- **Models:** source evidence `gemini-2.5-flash`, identity clustering `gemini-2.5-pro` (workflow defaults, unchanged),
  YOLO `yolo11s.pt`/OpenVINO, tracker `botsort.yaml`, stride 5.
- **Config digest:** SHA-256 of `evaluation/qualification/run_config.json` and
  `.github/workflows/pipeline-qualification-run.yml` at the run SHA (recorded in the cycle-10 report).
- **Namespace:** `qualification/q10-paid-01/`.

## Budget
- **Spent of the $2 total:** cycle 8 $0.380, q9-paid-01 $0.225, q9-paid-02 $0.469 = $1.074. Remainder $0.926.
- **Hard cap: $0.40.** `SPORTREEL_LLM_BUDGET_USD=0.40`, checked before every model call with a $0.05 reserve; the
  workflow asserts ≤ $0.92.
- **Estimate:** $0.20–0.30. q9-paid-01 cost $0.225 with the same identity path; source evidence varies with cache
  hits.
- **Margin:** at least $0.526 stays unspent for any follow-up.
- **Other limits:** wall clock 240 min (workflow); no QA re-edit beyond the pipeline's own bounded attempts.

## Baselines (same scorer, same GT)

| Metric | 43583126199 | 43920602179 | q9-paid-01 | q9-paid-02 |
|---|---|---|---|---|
| FULL rides | 7 | 7 | 14 | 14 |
| Missing include seconds | 29.8 | 26.1 | 20.4 | 20.4 |
| Published / correct | 12/9 | 5/4 | 5/4 | 10/7 |
| Published wrong identity | — | — | 0 | 1 |

## Success conditions (all required)
1. Production fingerprint identical before and after.
2. **Zero** publishable parts whose identity basis is image evidence across more than one source without operator
   evidence, and zero publishable visibly mixed reels (primary-athlete audit).
3. 0143+0152 not publishable.
4. Spend ≤ $0.40.
5. **Protected metrics** (no regression versus q9-paid-01, the same identity path): FULL rides ≥ 14, missing include
   seconds ≤ 21.4 (20.4 + 1.0), published correct ≥ 4, QA false passes ≤ 1.
6. MP4s decode cleanly; the identity of every multi-source reel and of the 0143+0152 reel is viewed.

## Evaluated, not pass/fail (nondeterministic model clustering)
- **FIX-PQ-10-003 in situ:**
  - If the clustering groups 0097+0115 and a text attribute splits them, a PENDING identity review request for
    exactly those two sources must appear in `identity_trace.json`; its absence in that case is a failure of
    FIX-PQ-10-003.
  - If the clustering does not group them, the item is NOT EVALUATED.

## Failure conditions
Any publishable mixed or false-merge reel, any production change, a cap breach, or a protected-metric regression.

## Rollback plan
- **On failure:** revert the failing FIX commit on the branch, set `llm_budget_usd_paid` back to 0, record the root
  cause, and run no further paid experiments.
- Nothing is merged to main and nothing is published in either case.
