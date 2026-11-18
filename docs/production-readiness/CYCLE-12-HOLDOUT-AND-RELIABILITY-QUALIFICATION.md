# Cycle 12 — independent validation, retry reliability, multi-sport engine

**Production decision: NO-GO.** Reasons:
- no independent holdout exists, so FIX-PQ-11-001 is not generalisation-proven;
- action ends, validity and cross-source verifier precision are still open;
- EXP-12-001 failed a protected condition.

**Adopted on the branch (CANDIDATE, pending owner approval to merge):**
- PA-13 draft ledger: proven RED → GREEN in contracts and on real R2 storage (Gate A), and exercised in a paid run;
- owner-rejection precedence in identity: a safety fix, RED → GREEN, rendered.

**Spend:**
- **Campaign:** $4.
- **Before this cycle:** $1.508, verified as cycle 8 $0.380 + q9-paid-01 $0.225 + q9-paid-02 $0.469 + EXP-10-001 $0.206 +
  EXP-11-001 $0.228.
- **This cycle:** Gate A $0 (budget 0), EXP-12-001 **$0.219**.
- **Total spent:** **$1.727**. **Remaining:** **$2.273**.
- The paid budget is reset to 0 and the workflow refuses anything above $2.273.

## 1. Status of the cycle-11 fixes

| Fix | Status | Basis |
|---|---|---|
| FIX-PQ-11-001 motion-supported onset | CANDIDATE_IMPROVED / MEDIA_VERIFIED, **not** HOLDOUT_VERIFIED | EXP-11-001; reproduced unchanged in EXP-12-001: FULL 15, missing 16.2 s, starts 7 |
| FIX-PQ-11-002 sport profiles | adopted (architecture) | F1–F9 |
| PA-16 scorecard | adopted; extended for non-GT people (FIX-PQ-12-003) | EVD-12-005 |

## 2. Identity decisions and their limits

The owner's **working** decisions are used only in isolated runs:
- `evaluation/qualification/identity_working_decisions.json`, marked `qualification_only`;
- ignored outside qualification runs (W8).

They are bound to the real source content hashes. The request IDs reproduce exactly from them (W1):
- `758fe7783e9c…`: 0097+0115, **same athlete**;
- `7b2a6964427f…`: 0074+0151, **different athletes**.

**Bug found and fixed (FIX-PQ-12-002):**
- An owner REJECTED decision was consulted only on the REVIEW branch, so a model MATCH kept the rejected pair
  together.
- Now a rejection on any member pair outranks:
  - model consensus;
  - superset approvals;
  - the singleton merge (no transitive merge).
- RED on 3da09101: W4, W5, W6 and W8 fail. GREEN: 0 failing. 22 identity contracts are unchanged.

**Limits:**
- The approval does not extend to similar pairs (W7).
- Promoting the decisions to production is a separate owner action (OWNER-ACTIONS-CYCLE-12.md §1). It was not done.

## 3. People not in the catalogue (PA-01)

Policy proposal: `UNCATALOGUED-PERSON-POLICY.md`, contract U1–U6.
- **Candidate reel for anyone:**
  - the action needs its own evidence;
  - all QA gates still apply;
  - **approval, account binding and distribution are operator-only**;
  - there is no biometric matching.
- **0095:** the viewed MP4 shows a **valid ride of an uncatalogued person**.
  - It is never counted as a GT success or as the tagged athlete's reel.
  - The scorecard now reports it apart: the legacy QA false pass of 1 is that non-GT-person reel, and there are 0
    GT-cohort false passes.
- The policy is not activated as a production change.

## 4. 0094 decision state (PA-03)

Evidence: `PA-03-0094-BOUNDARY-EVIDENCE.md`.
- **Frames:**
  - green-face riding until 12.5 s;
  - standing in the whitewater from 13.0 to 14.5 s;
  - crouching at 15.0 s;
  - prone from 15.5 s.
- **Candidates:**
  - 13.23 s (GT-v1) corresponds to the wave breaking;
  - about 15.2 s is where the standing ride ends;
  - 16 s is not supported.
- **GT-v1 is unchanged.** A correction would be a separate GT version, decided by the owner.

## 5. PA-13 retry reliability

**Design:** `pipeline/draft_ledger.py`.
- `canonical_reel_id` is built from the source content SHA-256 and the person, part and variant. No model text and no
  date are used.
- A per-reel ledger lives in `metadata/draft_ledger/` and is written with conditional PUTs (If-Match /
  If-None-Match).
- Names are claimed, so two reels can never share a name.
- **Revisions** record the plan digest, render SHA-256, run and QA verdict, and are marked committed or abandoned.
- Earlier Review bytes are archived by copy. Nothing is ever deleted.
- The ledger never writes `approved/` or `raw/`.
- Uploads go through `orchestrator.upload_draft`, so the manifest and publishability-revocation wrappers stay.

**Free RED/GREEN contract** (`test_draft_ledger_retry_contract.py`) on the production hooks:
- **RED:** old names give 4 objects for 3 reels.
- **GREEN, all 10 mandated scenarios:**
  - crash after the first upload, and crash after an upload but before the ledger commit;
  - a crash during parallel uploads;
  - retry the same day, retry another day, retry with a new description;
  - retry after QA PASS, and after QA FAIL → PASS;
  - a changed render (revision 2, earlier bytes archived, new approval required);
  - retry after operator approval (approved untouched);
  - two concurrent runs.
- **Also checked:** no delete, writes confined to `review/` and `metadata/`, name perturbation only in qualification
  runs, the inventory check.

**Real R2, Gate A suite pa13** (run 44269495332, budget 0, EVD-12-008):
- **Old names:** crash, then a retry with another description and date: 26 Review objects, **2 duplicates**.
- **Ledger:** 25 objects = 25 canonical reels.
  - No renamed duplicate; every partial kept; the same count as the old-naming retry.
  - 2 reels were committed without re-upload (crash between upload and commit), 1 was skipped as unchanged.
- A retry after completion was a no-op, and production was identical.
- The workflow reported FAIL only because the evaluator demanded cycle-10 phases this suite does not run. After
  fixing that bug, re-scoring the run's own inventories gives PASS 16/16.

**Paid run (EXP-12-001):** 13 Review objects = 13 ledgers, 0 problems.

**Limits:**
- The long-video and staged pending-upload paths keep the old naming.
- A QA-label change keeps the first name (conservative).

## 6. Holdout

**BLOCKED (BLK-12-001).** The only drone footage in production is the 24 GT-v1 sources, all used in development.
They are not reused as a holdout.

Ready:
- `scripts/holdout_qualification.py`:
  - **freeze:** refuses development overlap; requires condition tags, a reviewed range, a budget cap and thresholds.
  - **lock:** immutable; records code SHA, threshold and prompt digests, sources and cap.
  - **verify-lock:** detects tuning after the freeze.
  - **evaluate:** normalised and stratified metrics plus the pre-registered table.
- Contract H1–H7 on synthetic fixtures.
- The metrics template and plan (`HOLDOUT-H1-PLAN.md`).

**Needed:** new footage from another day, labelling, and freezing in that order.

## 7. RED/GREEN experiments

| Contract | RED (base) | GREEN |
|---|---|---|
| Draft ledger D1–D10, S, Q, I | old naming: duplicates | 0 failing |
| Identity working decisions W1–W9 | 3da09101: W4, W5, W6, W8 fail | 0 failing |
| PA-01 policy U1–U6 | — (pins current behaviour) | 0 failing |
| Holdout tooling H1–H7 | — | 0 failing |
| Football architecture F1–F9 (F9 new) | — | 0 failing |

Plus 22 identity contracts and the qualification-isolation contract, all unchanged.

## 8. Replays

**E1 end rule (pre-declared, free; EVD-12-003):** the actor's speed stays below 0.35 body heights/s for 1.5 s.
- It would cut 31.9 s of GT include (0146 mid-ride 13.6 s) to remove 3.8 s of non-include, so it is **rejected**.
- A drone that follows the surfer keeps him still in the image.
- An end signal needs a profile-owned action-state evaluator and labelled data.

**ActionValidity (0155):** not attempted. GT-v1 has only 3 negatives, so any threshold would be fitted to the test
set. The case stays in review.

## 9. Real pipeline runs

| Run | What | Cost | Result |
|---|---|---|---|
| Gate A 44269495332 | PA-13 crash and retry suite, real R2 | $0 | PASS (re-scored); old naming RED 2 duplicates, ledger GREEN |
| EXP-12-001 44290916415 | identity working decisions + ledger, 24 sources | $0.219 | **FAILED** (protected condition); details below |

**EXP-12-001 against its pre-registration:**
- **S1 OBSERVED:** 0097+0115 are one cluster, and the identity gate passes on the owner approval.
- **S2:** 0074 and 0151 are separate.
- **S3:** split athletes 2 → 1.
- **S4:** ledger inventory clean.
- **Protected condition failed:** publishable correct went 4 → 3.
  - The merged reel inherits the subject gate `PRIMARY_ACTOR_UNCLEAR` on the 0115 clip.
  - That clip was already blocked as its own reel in EXP-11-001, while 0097's single reel was publishable.
  - QA verdict PASS, no defects.
- **Verdict:** failed. Nothing is adopted from it.
- **Free next candidate:** handle the subject gate per clip in multi-clip reels: hold the blocked clip for review
  instead of withholding the whole reel. Then replay.

## 10. MP4 results

- **Technical check:** all 13 EXP-12-001 reels are H.264 2160×3840 at 30 fps, with 0 decode errors and no freeze or
  black (EVD-12-010).
- **Merged 0097+0115:** one athlete in both clips. The 0115 block looks conservative.
- **0074 and 0151:** each a single athlete. These lookalikes stayed separate.
- **Earlier evidence:** 0094 and 0095 frames (EVD-12-004/005).

## 11. Multi-sport

Architecture document §8.
- All cycle-12 Core changes (ledger, identity rejection, non-GT scoring, holdout tooling) are sport-neutral. F9
  checks this: no surf terms, and the football reel ID is stable.
- The E1 rejection shows the end signal belongs in a profile evaluator, not a Core threshold.
- **Not proven:** any football accuracy.

## 12. Quality before and after (same scorer, GT-v1)

| Metric | EXP-11-001 | Candidate (EXP-12-001) | Independent holdout | Verdict |
|---|---:|---:|---:|---|
| FULL actions | 15/24 (rate 0.625) | 15/24 | not run (BLK-12-001) | unchanged |
| Missing include s | 16.2 (3.25 s per ride-minute) | 16.2 | — | unchanged |
| Wrong starts | 7 (0.292) | 7 | — | unchanged |
| Wrong ends | 1 | 1 | — | unchanged |
| Excluded frames | 999 | 999 | — | unchanged |
| Wrong-actor frames | 54 | 54 | — | unchanged |
| Identity false merges | 0 auto-publishable | 0; owner-rejected pair never merged (rendered) | — | safety fix verified |
| Split athletes | 2 | **1** | — | improved |
| Correct ready-for-Review | 4 | **3** | — | **regressed (0115 subject gate on the merged reel)** |
| QA false passes | 1 (GT cohort 0) | 1 (GT cohort 0) | — | unchanged |
| Duplicate drafts after retry | not fully proven | **0** (Gate A real R2; RED 2 with old naming) | — | proven (isolated) |
| Run cost | $0.228 | $0.219 | — | — |

## 13. Cost and balance

| Item | Amount |
|---|---:|
| Spent this cycle | $0.219 (EXP-12-001) |
| Total spent | $1.727 of $4 |
| Remaining | $2.273 |

## 14. Remaining gaps

| Gap | Status | What unblocks it |
|---|---|---|
| Holdout (generalisation of FIX-PQ-11-001) | blocked | new footage and labels |
| Ends (PQ-06, PA-03, PA-15) | open | action-state evaluator, labelled ends, owner decision on 0094 whitewater |
| Validity (PQ-01, PA-04) | open | ≥ 30 negatives |
| Cross-source verifier precision (PQ-17, PA-07) | open | lookalike negative-pair set |
| Multi-clip subject-gate handling | new, free next step | from EXP-12-001 |
| PA-13 | long-video and staged-upload paths still on old naming | — |

Owner decisions (OWNER-ACTIONS-CYCLE-12.md):
- promote the identity decisions;
- approve the PA-01 policy;
- the 0094 labelling convention;
- the merge policy for PR #391.

## 15. GO / NO-GO

**NO-GO for production.**
1. No independent holdout.
2. Ends, validity and verifier precision are still open.
3. EXP-12-001 regressed correct ready-for-Review reels (4 → 3).

**GO on the branch:**
- PA-13 draft ledger: CANDIDATE_IMPROVED, isolated-verified on real R2;
- owner-rejection precedence: SAFETY_FIX, MEDIA_VERIFIED;
- non-GT-person scoring and holdout tooling.

All of these wait for owner review before any merge to `main`.

**Per fix:**

| Fix | Verdict |
|---|---|
| FIX-PQ-12-001 | adopted (candidate) |
| FIX-PQ-12-002 | adopted (safety) |
| FIX-PQ-12-003 | adopted (measurement) |
| E1 end rule | rejected |
| EXP-12-001 identity promotion | failed, not adopted |
| ActionValidity | not attempted (data) |
