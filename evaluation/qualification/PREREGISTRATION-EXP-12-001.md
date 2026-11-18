# Pre-registration EXP-12-001 — identity working decisions and draft ledger in a real isolated run

Written before the run. Nothing below may be changed after the label is applied.

**Run setup:**
- **Code:** the PR #391 head at launch (draft ledger 9c26a306, plus identity rejection precedence and later
  docs/tooling only). No threshold or prompt change since EXP-11-001 except the identity decision path.
- **Inputs:** batch `batch_2026-10-03T12-19-52_ttgvat95`, the 24 GT-v1 sources, namespace `qualification/q12-paid-01/`.
- **Identity decisions:** `SPORTREEL_IDENTITY_REVIEW_DECISIONS` = `evaluation/qualification/identity_working_decisions.json`
  (qualification-only owner working decisions: 0097+0115 APPROVED, 0074+0151 REJECTED).
- **Cost:** hard cap **$0.40** (`run_config.llm_budget_usd_paid`). Remainder before the run: $2.492.
- **Launch condition:** Gate A suite pa13 (run 44269495332) PASS. Otherwise the run is not launched.
  - **Met:** every PA13 check passed in the run. The workflow verdict was FAIL only because the evaluator also
    required cycle-10 phases this suite does not run. After fixing that bug, re-scoring the run's own inventories
    gives PASS 16/16 (EVD-12-008).

## Hypothesis

With the owner's working decisions, the engine delivers 0097 and 0115 as **one** athlete's reel without relying on
text similarity: the operator_review evidence is bound to the exact sources. It never merges 0074 with 0151. The
draft ledger leaves exactly one Review object per canonical reel. No protected quality metric regresses against
EXP-11-001.

## Success conditions (all required)

| # | Condition |
|---|---|
| S1 | If the model clustering or the singleton stage proposes 0097+0115, they render in ONE reel whose identity evidence is `operator_review` for request `758fe7783e9c…`. If no stage proposes the pair, S1 is recorded as NOT_OBSERVED (not a pass). |
| S2 | 0074 and 0151 are in different reels. No reel contains both. |
| S3 | split_athletes ≤ 1 (EXP-11-001: 2), counted only if S1 is observed |
| S4 | Every Review object in the namespace belongs to a ledgered canonical reel. No two Review objects share a canonical reel. Every ledger's latest revision is committed. |

## Protected conditions (EXP-11-001 → allowed)

| Metric | Allowed |
|---|---|
| FULL rides | ≥ 15 |
| missing include s | ≤ 16.7 (+0.5 tolerance) |
| incorrect starts | ≤ 7 |
| non-GT seconds | ≤ 7.97 |
| excluded frames | ≤ 999 |
| publishable wrong identity | 0 |
| publishable visibly mixed reels | 0 |
| QA false pass (legacy) | ≤ 1 |
| GT-cohort QA false pass | 0 |
| publishable correct | ≥ 4 |

Also required:
- spend ≤ $0.40;
- production fingerprint identical before and after.

## MP4 verification (mandatory before any verdict)

- Decode all reels: H.264, 9:16, 0 decode errors, no freeze or black.
- View the 0097+0115 reel: one athlete, both clips, each opening on the action.
- View the 0074 and 0151 reels: each one athlete.
- Record SHA-256s.

## Failure handling

- **Any protected regression:** the experiment fails and nothing is adopted. The identity path stays as at
  3da09101 + rejection precedence (a safety-only change).
- **Run crash or cap:** report it as such. No retry without a new pre-registration.
