# Cycle 9 — Isolated qualification runs, rendered-media QA, GO/NO-GO

**Decision: NO-GO.** PR #391 stays a draft and is not merged. No paid run is authorised by the current config
(`evaluation/qualification/run_config.json` sets `llm_budget_usd_paid: 0`).

All numbers below come from the GT-v1 dataset (ae844a94, digest `b31fd9b4…27c9`), 24 sources and 13 athletes.
GT was used only after each run, for scoring; the pipeline never read it. GT-v1 was not changed.

## 1. Proof of a non-destructive re-run (Phase B) — PROVEN, with two gaps

The mechanism is `SPORTREEL_QUALIFICATION_RUN_ID`:
- **R2:** every object key is mapped into `qualification/<id>/` at the boto3 boundary
  (`integrations/qualification.py::NamespacedS3`, wired in `integrations/r2_storage._client`).
- **Supabase:** writes and RPCs are blocked and recorded (`GuardedSupabase`).
- **Dedup:** decisions are resolved read-only from the recorded `canonical_upload_id`.
- **Skipped in qualification mode:** the reprocess stage, notifications and Cloudflare Stream.
- **Model spend:** checked before every model call (`check_llm_budget`).
- **Inputs:** seeded by a verified server-side copy (`scripts/qualification_run.py seed`, same bytes, size and ETag
  checked).
- **Production fingerprint:**
  - R2 prefixes: `raw/`, `review/`, `approved/`, `pending_payment/`, `previews/` and `metadata/source_state/`;
  - Supabase tables: `drafts`, `draft_publishability`, `reels`, `reprocess_requests` and `pipeline_status`.

| Run | Commit | Namespace | Production before = after | R2 writes (all namespaced) | Supabase writes blocked | Model spend |
|---|---|---|---|---|---|---|
| 44078257676 | 2d2595a0 | q9-dry-02 | identical | 52 | 204 | $0 (52 calls refused) |
| 44085419164 | cdb77b9c | q9-paid-01 | identical | 39 (+2 deletes of its own preflight file) | 115 | $0.225 |
| 44121013654 | 2c86d3a2 | q9-paid-02 | identical | namespaced | blocked | $0.469 |

What these runs establish:
- **Drafts and approvals:** Review drafts, approvals and the Discover tables (`reels`) are unchanged in all three
  runs.
- **Mid-run failure:** the publish state stays truthful. The dry run failed closed at the business gate (QA
  unavailable) and wrote nothing to production.
- **Discover:** there is no path to it from these runs.

**Not yet proven (PA-12):**
- a retry into the same namespace;
- an explicit mid-run kill.

Both can be tested for free with `qualrun-dry`.

## 2. EXP-09-001 (q9-paid-01) — FAILED its pre-registered conditions

Pre-registration: `evaluation/qualification/PREREGISTRATION-EXP-09-001.md`.

Outcome:
- 0097+0115 were rendered as **two** reels.
- 0143+0152 (GT: two athletes) were rendered as **one** reel. The reel was withheld as IDENTITY_UNCONFIRMED.

Diagnosis, from the run's own `identity_trace.json`:
- The pairwise image verifier made **0 calls**.
- Every multi-source cluster became a review request with reason `identity_sheet_has_fewer_than_6_crops`, although
  every sheet in the trace has 6 crops.
- Cause: `_resolve_model_appearance`, the production model-clustering path, dropped the crop count. The earlier
  contracts set `_sheet_crops: 6` by hand.
- The model clustering *did* group 0097+0115. `_split_impossible_clusters` then split them on the TEXT attribute
  `wetsuit_vs_bare_or_swimsuit_conflict` ("dark swimsuit" vs "no shirt").

## 3. EXP-09-002 (q9-paid-02) — FAILED: false merge made publishable

The fix, at 2c86d3a2:
- **FIX-PQ-09-001** keeps the crop count on the model path.
- **FIX-PQ-09-002** exempts image-verified clusters from the description-attribute split.
- RED→GREEN contract: 4 failures before the fix, 0 after.

Pre-registration: `PREREGISTRATION-EXP-09-002.md`, cap $0.90.

Result, with the verifier live (64 consensus calls):
- **0143+0152:** stamped as a both-orders pairwise MATCH. The identity gate passed the reel and marked it
  **publishable**. GT says these are two athletes (`0d12c8b8` and `42f8772b`). This is a pre-registered failure
  condition.
- **0112 / 0131 / 0104 / 0126+0140:** one GT athlete was split into 4 reels, because a pair was answered NO_MATCH.
- **0097+0115:** still two reels. The singleton stage most likely skipped: 14 single-source clusters give 91 candidate
  pairs, above the cap of 45. This is inferred; the skip line is not in the captured log.
- **Production fingerprint:** identical.

**Action taken:** FIX-PQ-09-001 and FIX-PQ-09-002 were reverted (the identity code is back to cdb77b9c), and paid runs
are disabled. The dead verifier is the safer state: it withholds a lookalike reel instead of publishing it.

**FIX-PQ-08-003** (singleton pair merge) is now **FAILED in integration**. It never took effect in a real run.

## 4. Rendered-media QA (decoded MP4s, q9-paid-02)

Visual inspection used contact sheets at 1.5 fps of the decoded reels. The EDL was not used as a substitute.

| Reel (sha256 prefix) | Sources | Identity | Rides | Boundaries | Verdict |
|---|---|---|---|---|---|
| b7b86f1066e2 | 0143+0152 | **two lookalike riders** (white top, pink longboard; clip 2 sleeves longer) | both | — | WRONG (mixed), marked publishable |
| 70a8d9460ef8 | 0097 | correct athlete, backlit | ride complete | foam-only tail ~0.7 s | correct, but split |
| 1708522a574b | 0115 | visibly the same athlete as 0097 | ride to fall | **starts at pop-up: paddle-in missing** (GT start error 4.44 s) | correct, but split |
| 7831b08d9d8a | 0070+0108 | correct athlete | both rides | **clip 2 runs into the GT-excluded shore tail, ~20–26 s** | not publishable-correct |

Technical check: all 17 reels were decoded with a full scaled decode pass, plus SHA-256 and ffprobe (see §8). No
reel carries `RENDERED_MEDIA_VERIFIED` for a fix, because no fix survived.

## 5. Before/after metrics

| Metric | 43583126199 | 43920602179 | q9-dry-02 ($0, no identity) | q9-paid-01 | q9-paid-02 (reverted) |
|---|---|---|---|---|---|
| FULL rides (of 24) | 7 | 7 | 14 | 14 | 14 |
| ≥95% | 10 | 9 | 14 | 14 | 14 |
| Missing include seconds | 29.8 | 26.1 | 20.4 | 20.4 | 20.4 |
| Boundaries over tolerance | 17 | 17 | 9 | 9 | 9 |
| Excluded frames rendered | 517 | 999 | 999 | 999 | 999 |
| Non-ride windows | 1 | 2 | 2 | 2 | 2 |
| Mixed reels | 2 | 2 | 1 | 2 | 2 |
| Split athletes | 1 | 2 | 6 | 2 | 3 |
| Reels | — | — | 25 | 14 | 17 |
| Published / correct | 12 / 9 | 5 / 4 | 0 / 0 | 5 / 4 | 10 / 7 |
| QA false pass (published, not correct) | 3 | 1 | 0 | 1 | 3 (incl. the 0143+0152 false merge) |
| Correct reels withheld | 0 | 6 | 21 | 6 | 6 |
| Model cost | — | ~$0.23 | $0 | $0.225 | $0.469 |
| Cost per correct published reel | — | ~$0.06 | — | $0.056 | $0.067 |
| Wall time (CI run) | — | — | 44 min | 39 min | 46 min |

The ride-coverage gain over the two baselines (FULL 7→14, missing 29.8/26.1→20.4 s) comes from the cycle-7/8 code
already on this branch. Identity did not improve.

### Per athlete

Cell format: FULL rides / reels; M = mixed reel; P = correct published reel.

| GT athlete | GT rides | 43583126199 | 43920602179 | q9-paid-01 | q9-paid-02 | Visual verdict (q9-paid-02) |
|---|---|---|---|---|---|---|
| 0d12c8b8 (0143) | 1 | 1/1 M | 1/1 M | 1/1 M | 1/1 M | mixed with 42f8772b |
| 42f8772b (0152) | 1 | 1/1 M | 0/1 M | 0/1 M | 0/1 M | mixed with 0d12c8b8 |
| 144c217d (0070, 0108) | 3 | 2/1 | 1/1 | 2/1 | 2/1 | correct identity, excluded tail |
| 6c84aed0 (0112, 0126, 0131, 0140, 0104) | 5 | 2/1 P1 | 3/1 | 4/1 | 4/4 P3 | split into 4 |
| 6e81fe5b (0074) | 1 | 0/1 P1 | 0/1 | 1/1 | 1/1 | — |
| 8627f3bf (0151) | 1 | 0/1 P1 | 0/1 | 0/1 | 0/1 | — |
| 8b1c2b0e (0160, 0163) | 2 | 1/1 P1 | 2/1 | 2/1 | 2/1 | withheld (conflicting track ids) |
| 8ef1161d (0130) | 1 | 0/1 P1 | 0/1 P1 | 1/1 P1 | 1/1 P1 | — |
| 9524ac02 (0094, 0118, 0142, 0146) | 4 | 0/1 M | 0/1 M | 2/1 M | 2/1 M | mixed via 0094 window |
| b9818a21 (0165) | 1 | 0/1 P1 | 0/1 P1 | 1/1 P1 | 1/1 P1 | — |
| c53ef74d (0097, 0115) | 2 | 0/1 P1 | 0/2 P1 | 0/2 P1 | 0/2 P1 | same athlete, two reels |
| d805a9b1 (0094 tandem) | 1 | 0/2 M P1 | 0/2 M | 0/2 M | 0/2 M | — |
| ed0d45c3 (0162) | 1 | 0/1 P1 | 0/1 P1 | 0/1 P1 | 0/1 P1 | — |

Athletes without a ready, correct reel in q9-paid-02: 6 of 13.

## 6. Status of the cycle-9 mandate items

| Item | Status | Evidence |
|---|---|---|
| Non-destructive re-run | **Proven** (retry and crash tests open) | EVD-09-001…003 |
| 0097+0115 merged into one rendered reel | **Not achieved**; the two reels were viewed and show the same athlete | EVD-09-003, EVD-09-004 |
| 0143+0152 not merged | **Violated** in q9-paid-02 (reverted); withheld in q9-paid-01 | PA-11 |
| 0115 start (paddle-in) | Open: the rendered reel starts at pop-up, 4.44 s late; no general rule without the 0140 regression | EXP-08-003 |
| 0155 | Open: no general signal; analyzer score 7 for both 0155 and the valid 0143; an owner definition or more negatives are needed | EVD-08-004 |
| 0108 / 0094 tails | Open: 0108 tail visible in the rendered reel; 0094 13.2–16 s still awaits owner adjudication | PA-03 |
| Primary athlete | 24/25 shots OK; 0095 is a WRONG_PERSON (uncatalogued rider) | `primary_athlete_audit` |
| QA on the new videos | Done: visual (4 reels) + technical (17 reels) | §4, §8 |
| Cost | $1.074 of $2 spent; $0.926 left; paid runs disabled | BLK-09-001 |

## 7. Code ↔ experiment ↔ output

| ID | Commit | Run | Output |
|---|---|---|---|
| Phase B isolation | ef780a91, 2d2595a0, 0948615e | 44078257676 | `qualification-diagnostics-q9-dry-02-44078257676` |
| EXP-09-001 | cdb77b9c | 44085419164 | `qualification-diagnostics-q9-paid-01-44085419164`, reels artifact 14330909596 |
| EXP-09-002 / FIX-PQ-09-001, -002 | 2c86d3a2 (reverted) | 44121013654 | `qualification-diagnostics-q9-paid-02-44121013654`, reels artifact 14350100273 |

## 8. Technical media check (q9-paid-02, all reels)

One full decode pass per reel, scaled to 480 px, with freezedetect (≥0.5 s) and blackdetect (≥0.3 s), plus ffprobe and
SHA-256.

| Reel | sha256 (prefix) | codec / resolution / fps | duration s | frames | decode error lines | frozen ≥0.5 s | black ≥0.3 s |
|---|---|---|---|---|---|---|---|
| Man in a black long-sleeved top on a red_pink surf | 3bbe99cfc58b | h264 2160x3840 30/1 | 9.1 | 274 | 0 | [] | [] |
| Man in a white long-sleeved top and dark shorts on | b5065b8f6204 | h264 2160x3840 30/1 | 6.3 | 190 | 0 | [] | [] |
| Man in a white t-shirt and dark shorts on a pink l | b7b86f1066e2 | h264 2160x3840 30/1 | 14.6 | 439 | 0 | [] | [] |
| Man with long dark hair and beard_ wearing a black | cd44268ecb46 | h264 2160x3840 30/1 | 87.0 | 2609 | 0 | [] | [] |
| Shirtless surfer in pink shorts on a light-colored | 2cf3e6ffc781 | h264 2160x3840 30/1 | 6.1 | 184 | 0 | [] | [] |
| Shirtless surfer with patterned shorts on a light | 1708522a574b | h264 2160x3840 30/1 | 11.9 | 356 | 0 | [] | [] |
| Silhouette of a surfer in patterned shorts on a li | 70a8d9460ef8 | h264 2160x3840 30/1 | 9.1 | 274 | 0 | [] | [] |
| Surfer wearing a red hooded top on a light-colored | fe0ea14ef120 | h264 2160x3840 30/1 | 8.6 | 259 | 0 | [] | [] |
| Tandem surfers_ an adult in a pink top and a child | e6d52c8268a6 | h264 2160x3840 30/1 | 9.7 | 291 | 0 | [] | [] |
| Woman in a dark patterned bikini on a turquoise lo | a86c64167871 | h264 2160x3840 30/1 | 6.1 | 184 | 0 | [] | [] |
| Woman in a green bikini on a white_yellow longboar | cb0184d091a1 | h264 2160x3840 30/1 | 23.5 | 705 | 0 | [] | [] |
| Woman in a grey long-sleeved swimsuit on a turquoi | 7831b08d9d8a | h264 2160x3840 30/1 | 27.0 | 811 | 0 | [] | [] |
| surfer in a greenish-grey t-shirt and dark shorts | 1ee66569e92f | h264 2160x3840 30/1 | 7.8 | 234 | 0 | [] | [] |
| surfer in black long-sleeve top and shorts on a wh | faebd5abeeaf | h264 2160x3840 30/1 | 21.7 | 652 | 0 | [] | [] |
| surfer in greenish-blue shirt and dark shorts on a | 88a95df2469f | h264 2160x3840 30/1 | 19.2 | 575 | 0 | [] | [] |
| surfer on a red longboard wearing a light blue-gre | 5f8eb9ac966e | h264 2160x3840 30/1 | 12.9 | 388 | 0 | [] | [] |
| surfer with red longboard and dark top | 708009fee8fd | h264 2160x3840 30/1 | 20.3 | 608 | 0 | [] | [] |

Result: 17 reels decoded; reels with a decoder error line or a frozen stretch: 0.

## 9. Open gaps (next cycle)

1. **PA-11 — identity verifier precision.** Lookalike negatives (0143/0152) pass. The verifier must not gate
   auto-publish until it is validated on more negatives. Operator review for every multi-source cluster is the safe
   default.
2. **PA-08 — 0097+0115.** Needs a verifier the system can trust, plus a singleton stage that runs within its pair cap
   on a real batch (14 singles → 91 pairs).
3. **PA-12 — isolation:** retry idempotency and mid-run crash tests ($0).
4. **0094 window overrun** mixes 9524ac02 with the tandem rider: a mixed reel in every run.
5. **0108 tail, 0115 paddle-in, 0155 failed take-off:** open, as in cycle 8.
6. **0095:** a wrong-person non-ride reel is still marked publishable.
