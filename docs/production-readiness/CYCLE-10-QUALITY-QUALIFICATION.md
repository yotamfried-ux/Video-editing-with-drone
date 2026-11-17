# Cycle 10 — Qualification gates, identity safety, controlled pipeline experiment, GO/NO-GO

**Production decision: NO-GO.** PR #391 stays a draft and is not merged.

**FIX-PQ-10-001 is `CANDIDATE_IMPROVED`:** with it, no reel becomes publishable on a model's visual answer alone. It was
verified on rendered MP4s from the exact tested commit. Several P0/P1 product gaps remain open: boundaries, 0155,
0115 paddle-in and the 0095 policy.

| Item | Value |
|---|---|
| Ground truth | GT-v1 ae844a94, digest `b31fd9b4…27c9`; 24 sources, 13 athletes, 24 rides. Never read by the pipeline; not changed. |
| Branch | `ccr-3f12fc2f-pdvirt`. Cycle-9 end: `f299a5a9`. Paid run SHA: `bf9c9024`. |
| Spend | $1.280 of $2: cycle 8 $0.380, q9-paid-01 $0.225, q9-paid-02 $0.469, **q10-paid-01 $0.206**. Remainder **$0.720**. Paid runs are closed: `run_config.json` paid budget is 0 and the workflow caps at 0.72. |

## 1. Gate A — isolation and recovery (free) — PASS, with recorded limits

The test harness runs the production entry point (`scripts/run_tracked.py`) in qualification namespaces at LLM budget
0:
- `integrations/qualification.fault` is a hard crash (`os._exit(97)`), honoured only in a qualification run.
- The driver is `scripts/qualification_gate_a.sh`; the evaluator is `scripts/qualification_gate_a.py`.
- The workflow is `.github/workflows/pipeline-qualification-gate-a.yml`, triggered by the `qualgate-a` label.

**Run 44140263067 (@82f8e544) — FAILED.** Two causes, both fixed in 80fc677b:
- The `before_qa` and `after_first_upload` fault points sat in `orchestrator._compile_clusters`. Production replaces
  that function with `context_qa_gate.compile_clusters_with_context_qa`, so the points never fired (PA-14).
- The evaluator keyed results by `Path.stem`.

**Run 44148876075 (@80fc677b, namespace q10-gate-a2):**

| Phase | Result |
|---|---|
| R0 retry into the completed q9-dry-02 namespace | no input, 0 writes, listing identical |
| F1 crash after analysis | exit 97; 0 drafts, 0 processed markers, 0 publishable records; raw unchanged |
| F2 crash before the QA gate | exit 97; 0 drafts, 0 markers, 0 publishable records; raw unchanged |
| F3 crash after the first upload | exit 97; 3 complete drafts (3 upload workers), 0 markers, 0 publishable records |
| R4 recovery, same namespace | 25 drafts, 24 markers, every F3 partial key rewritten, **0 orphans / duplicates**; raw unchanged |
| R5 retry after recovery | no input, 0 writes, listing identical |
| Production fingerprint | identical |

The evaluator was corrected after run 2 and re-applied to that run's own ledgers. Committed reports are under
`evaluation/qualification/gate_a/`. The two corrections:
- A substring match on "pass" had counted `qa_passed: false` records as passes.
- The partial-upload bound was 1; it is now the number of upload workers.

**Limits (not proven):**
- At budget 0 QA cannot pass, so a publishable partial is not exercised.
- A paid retry whose draft names drift (new model descriptions, or the next day's date) could leave duplicates
  (PA-13).

## 2. Gate B — identity safety — PASS

| Case | Finding | Change |
|---|---|---|
| 0143 vs 0152 (two GT athletes) | EXP-09-002: a both-orders, 6-crop model MATCH made the reel publishable | **FIX-PQ-10-001** `real_identity_gate._evidence_may_autopublish`: model-only pairwise consensus on a multi-source cluster → kept together **unconfirmed** (withheld); only an owner `operator_review` passes. Red 4 / green 0. |
| `_stable_track`, clip index 0 | `str(0 or "") == ""`: a same-source same-track cluster from clip 0 never passed | **FIX-PQ-10-002** |
| 0097 vs 0115 (one GT athlete) | model grouped them; split on text ("dark swimsuit" / "no shirt") with no review path | **FIX-PQ-10-003** `identity._text_attribute_split_reviewed`: PENDING owner review request; APPROVED → kept together with operator evidence. No model call. Red 4 / green 0. |
| 0094 (two riders in one source) | crop shows 9524ac02 in 195/203 audited frames, 0 other GT athletes, 0 switches. The scorecard's "mixed" is a time overlap of the window with d805a9b1's ride (PA-16). The defect is the end, 9.3 s late (PA-15). | none (boundary gap) |
| 0095 (wrong primary) | drone centres track 10003, an uncatalogued rider. GT athlete 6c84aed0 is track 10007 on the same wave, his take GT-excluded. No switch. | none: owner decision PA-01. Scored as incorrect. |
| 0151, lookalikes, lighting | covered by the contracts above and by EXP-10-001 (0074+0151 raised a review request, not a merge) | — |

Older plumbing contracts now check the pass path only under the explicit opt-in
`SPORTREEL_VISUAL_CONSENSUS_AUTOPUBLISH=1` (reserved for a validated verifier).

## 3. Gate C — replay on every stored run — PASS

`scripts/identity_policy_replay.py` uses the same scorer and GT:

| Run | Under FIX-PQ-10-001 |
|---|---|
| q9-paid-02 | published 10 → 8; wrong identity 1 → **0**; non-ride 2 → 1; **correct 7 → 7**; coverage unchanged |
| 43920602179, q9-dry-02, q9-paid-01 | unchanged (no image-evidence passes) |
| 43583126199 | NOT_REPLAYABLE (legacy manifest without per-event inputs) |

## 4. Quality fixes attempted

| Problem | Result |
|---|---|
| 0097+0115 merge | No trustworthy verifier, so no automatic merge. A reasoned transfer to owner review exists (FIX-PQ-10-003) and was **observed in the real run** (request `758fe7783e9c`). The 45-pair singleton stage stays inactive; extending it would only spend model calls on a verifier that is not trusted. |
| 0155 failed take-off | No general signal (cycle 8: analyzer score 7 for 0155 and for the valid 0143; box shape does not separate). Not changed; no fit to the single negative. Open. |
| 0115 paddle-in | No rule found that keeps the paddle-in without bringing back the 0140 wait. Open. |
| 0108 / 0094 ends (and wider) | **EXP-10-002 rejected.** The pre-chosen board-loss rule removed 6.2 s of non-include but cut **44.0 s** of GT include. Overruns are wider than 0094/0108: 0142 +10.0 s, 0126 +3.5 s, 0146 +3.2 s; pre-roll 0146 4.9 s, 0118 4.7 s, 0142 4.6 s (PA-15). GT-v1 is unchanged; 0094 13.2–16 s is still the owner's call. |

Changes reverted or rejected in this cycle:
- **EXP-10-002:** not committed to the pipeline.
- **FIX-PQ-09-001/002:** stay reverted; not re-applied.

## 5. Controlled pipeline experiment EXP-10-001 — conditions met

- **Pre-registration:** `evaluation/qualification/PREREGISTRATION-EXP-10-001.md`, committed before launch.
- **Run:** 44166232265, head `bf9c9024`, namespace `q10-paid-01`.
- **Cost:** $0.206 for 15 model calls (14 flash source-evidence, 1 pro clustering; 0 verifier calls). Cap $0.40.

| Pre-registered condition | Result |
|---|---|
| Production fingerprint identical | **identical** |
| 0 publishable multi-source reels without operator evidence; 0 publishable visible mixes | **0 / 0** (5 multi-source reels unconfirmed and withheld) |
| 0143+0152 not publishable | **withheld** (rendered as one reel; viewed) |
| Spend ≤ $0.40 | **$0.206** |
| FULL ≥ 14, missing ≤ 21.4 s, correct published ≥ 4, QA false passes ≤ 1 | **14, 20.4 s, 4, 1** |
| MP4s decode; multi-source and 0143+0152 identity viewed | **14/14 decode, 0 errors / freezes / black**; viewed below |
| FIX-PQ-10-003 in situ (evaluated if 0097+0115 grouped) | **grouped and split on text → PENDING request for exactly 0097+0115** |

### Rendered MP4s (decoded; SHA-256 prefix)

| Reel | Sources | Identity verdict | State |
|---|---|---|---|
| 1ae08503dc19 | 0112, 0126, 0131, 0140, 0104 | one athlete in all five clips (green t-shirt, red board) | correct, **withheld** (unconfirmed) |
| 3df8c2fb84b4 | 0160, 0163 | one woman | correct, withheld |
| 30a2aed300b7 | 0143, 0152 | two lookalike riders | **mixed, withheld** (not publishable) |
| c704b2278366 | 0070, 0108 | one woman; 0108 shore tail rendered (144 excluded frames) | withheld |
| cf6dcb1781f7 | 0094, 0118, 0142, 0146, 0155 | one rider; 0155 failed take-off, 0094/0142 tails | withheld |
| 7a9280cbde56 / 767ecae02f52 | 0097 / 0115 | same athlete in two reels; 0115 starts at pop-up | 0097 publishable correct; 0115 not published |
| ca1813e1e0bd | 0095 | uncatalogued rider (PA-01) | **publishable** (the one QA false pass) |
| 0130, 0162, 0165 reels | single source | correct | publishable correct |

## 6. Results matrix (same scorer, same GT; "published" = publishable in the isolated run, nothing was published)

Best historical is 43583126199 on correct publishable reels and q9-paid-01/02 on coverage.

| Metric | 43583126199 | 43920602179 | q9-paid-02 | **EXP-10-001** | Change vs q9-paid-02 |
|---|---|---|---|---|---|
| FULL rides (of 24) | 7 | 7 | 14 | **14** | = |
| Missing include seconds | 29.8 | 26.1 | 20.4 | **20.4** | = |
| Mixed reels (time-attributed / visible) | 2 / – | 2 / – | 2 / 1 | **2 / 1** | = (visible mix now withheld) |
| Split athletes | 1 | 2 | 3 | **2** | −1 |
| **False merges auto-publishable** | – | – | **1** | **0** | **−1** |
| Correct ready-for-Review (publishable correct) | 9 | 4 | 7 | **4** | −3 |
| Excluded frames rendered | 517 | 999 | 999 | **999** | = |
| QA false passes (publishable, not correct) | 3 | 1 | 3 | **1** | −2 |
| Correct reels withheld | 0 | 6 | 6 | **6** | = |
| Model cost | – | ~$0.23 | $0.469 | **$0.206** | −$0.263 |

Correct publishable reels fall 7 → 4 against q9-paid-02. That run's live verifier wrongly split the 0112 athlete into
single-source reels that could each publish. Here that athlete is one correct reel, withheld for owner confirmation,
alongside 0070+0108 and 0160+0163. The safety gate costs no rides (coverage is identical) but holds correct
multi-source reels for review.

### Per athlete (FULL rides / reels; P = correct publishable)

| GT athlete | GT rides | q9-paid-02 | EXP-10-001 | First point of loss / error |
|---|---|---|---|---|
| 0d12c8b8 (0143) + 42f8772b (0152) | 1 + 1 | 1/1 mixed, **publishable** | 1/1 mixed, withheld | identity clustering (lookalikes) |
| 144c217d (0070, 0108) | 3 | 2/1 P* | 2/1 withheld | window end (0108 tail) |
| 6c84aed0 (5 sources) | 5 | 4/4 P3 | 4/1 withheld | identity confirmation (needs owner) |
| 6e81fe5b (0074) | 1 | 1/1 | 1/1 | correct but not publishable (final QA/publish gate) |
| 8627f3bf (0151) | 1 | 0/1 | 0/1 | boundary (end 1.47 s) |
| 8b1c2b0e (0160, 0163) | 2 | 2/1 | 2/1 withheld | identity confirmation |
| 8ef1161d (0130) | 1 | 1/1 P | 1/1 P | — |
| 9524ac02 (0094, 0118, 0142, 0146) | 4 | 2/1 | 2/1 withheld | windows (pre-roll / tails), 0155 inside the reel |
| b9818a21 (0165) | 1 | 1/1 P | 1/1 P | — |
| c53ef74d (0097, 0115) | 2 | 0/2 P1 | 0/2 P1 | identity split (review request), 0115 paddle-in |
| d805a9b1 (0094 tandem) | 1 | 0/2 | 0/2 | start boundary |
| ed0d45c3 (0162) | 1 | 0/1 P | 0/1 P | start boundary (1.47 s) |

\* published but not correct (excluded frames).

## 7. Code ↔ experiment ↔ output

| ID | Commit | Test / replay | Run | Output |
|---|---|---|---|---|
| Gate A harness | 82f8e544, 80fc677b, bf9c9024 | Q11/Q12 contracts | 44140263067, 44148876075 | `qualification-gate-a-*` artifacts, `evaluation/qualification/gate_a/` |
| FIX-PQ-10-001 / 002 / 003 | 8992e067 (+ contract updates 5c79e59f) | `test_identity_autopublish_policy_contract.py`, `test_text_split_review_request_contract.py`, Gate C replay | 44166232265 | reels above; `qualification-diagnostics-q10-paid-01-44166232265` |
| EXP-10-002 (rejected) | — (session replay) | board-loss replay | — | — |

Registry: EVD-10-001…006, FIX-PQ-10-001…003, gaps PA-11 (patched: mitigated), PA-12 (tested), PA-13…16 (new), BLK-10-001.
Each MP4 maps back through `qualification_reels.json` (SHA-256 to key) and `publishable_reel_manifest.json` (part
`content_sha256`, event `source_sha256`, interval) to run 44166232265, then to commit `bf9c9024`.

## 8. GO / NO-GO

**Met:**
- No auto-publishable false merge.
- No publishable mixed reel.
- No publication, and no production change.
- No new P0.
- Rides preserved.
- MP4s viewed.
- Evidence tied to the tested commit.

**Not met, so production is NO-GO:**
- Excluded content is still rendered (999 frames: 0155, the 0108 tail, 0095).
- Large boundary overruns (PA-15).
- 0097+0115 still two reels until the owner decides.
- 0095 is a publishable reel of an uncatalogued rider (PA-01).
- Correct multi-source reels need manual identity confirmation.

## 9. Open gaps and owner decisions

1. **Owner decisions:**
   - Identity review requests `758fe7783e9c` (0097+0115: approve) and `7b2a6964427f` (0074+0151: reject).
   - PA-01: reels for uncatalogued riders (0095).
   - PA-03: 0094 13.2–16 s.
2. **PA-15:** a validated end-of-action and pre-roll signal (per-frame ride state). The board-loss approach failed.
3. **PA-11:** a verifier that is reliable on lookalike negatives before any multi-source auto-publish.
4. **0155 and 0115:** failed take-off and paddle-in; no general signal yet.
5. **PA-13:** paid-retry duplicate risk from draft-name drift.
6. **PA-14:** remove the shadowed `orchestrator._compile_clusters` copy.
7. **PA-16:** a crop-aware mixed-reel metric.
