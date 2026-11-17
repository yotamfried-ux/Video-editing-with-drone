# Cycle 3 — cross-clip athlete identity: method comparison against GT-v1 (PQ-02/03/10/17/23/40)

**Status:** REPRODUCED · TESTED (decision rules) · EXPERIMENT RUN (dev + one-shot holdout, **low power**). Not PATCHED in the pipeline, not HOLDOUT_VERIFIED, not MEDIA_VERIFIED for any product reel.
**Budget:** authorised $2 per experiment; spent **≈ $0.64** (dev $0.49, holdout $0.15; token-based estimate, 270 Gemini 2.5 Flash calls). No full pipeline run. MAX_PAID_PIPELINE_RUNS=0 unchanged.
**Data handling:** the repository is public. R2 proxies were read in the job (read-only, secrets in Actions), crops cut in memory, sent to Gemini as inline bytes. The only output is JSON verdicts and counts (`evaluation/identity_experiment/cycle3_results.json`). No image, crop or video was written to the repository, an artifact or a log.

## Research record (before implementation)
| Source | Finding | Decision |
|---|---|---|
| Engineering-OS `docs/architecture-guides/cv/tracking.md`, `video-analytics.md` | Tracking guidance is intra-video (Kalman + appearance ReID, HOTA/IDF1). No cross-clip person verification pattern. | Library is not sufficient for this gap; used for metric vocabulary only. |
| Ultralytics docs (Context7, `modes/track`) | BoT-SORT `with_reid` fuses appearance only after an IoU `proximity_thresh`; "ReID is tracking-only" (no predict/val for ReID). Intra-video association, not a cross-clip verifier. | Not applicable to PQ-02/03; remains a candidate for in-clip fragmentation (PQ-04). License AGPL-3.0/commercial (register §10.4): config A/B only, no vendoring. |
| DeepSORT (nwojke/deep_sort) | Intra-video appearance association; needs a person-ReID network trained on ground-level data. Licence **not verified in this cycle**. | Not adopted; domain gap (top-down aerial) unmeasured. |
| Existing SportReel code | `identity._VERIFY_PROMPT` ("plausibly the same", group call) and `_MERGE_CHECK_PROMPT` ("lighting shifts colours"): both permissive; `identity_evidence.stamp` writes a MATCH edge for every pair from ONE group call (PQ-23). | Measured below (M0). |

## Method comparison (labels = GT athlete of the pipeline's actor track; split by athlete fixed before results)
Dev: 9 athletes, 69 pairs (9 positive / 60 negative; 31 "hard" negatives = smallest colour distance). Holdout: 4 athletes, 21 pairs (10 / 11; 3 hard), run once with the frozen rule.

| Method | Dev FM | Dev FS | Dev auto-TP | Dev REVIEW (pos/neg) | Holdout FM | Holdout FS | Holdout auto-TP | Holdout REVIEW (pos/neg) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 production verifier prompt (one 4-crop sheet per clip) | **3** | 1 | 8 | 0/0 | 0 | 0 | 10 | 0/0 |
| M1 pairwise, 6 crops, explicit matching/contradicting features | 1 | 4 | 5 | 0/0 | 0 | 0 | 10 | 0/0 |
| **M2 = M1 in both image orders + consensus (disagreement ⇒ REVIEW)** | **0** | **0** | 4 | 5/1 | 0 | 0 | 8 | 2/0 |
| M4 HSV colour histogram, no model | 44 | 1 | 8 | – | not scored | | | |

FM = false merge (GT different athletes, rule says MATCH). FS = false split. Upper 95 % bound on the false-merge rate (Wilson): M0 13.7 %, M2 6.0 % on dev negatives; **26 % on the 11 holdout negatives**.

## Conclusions (and what they do not prove)
1. **The production verifier prompt produces confirmed false merges:** 3 of 60 dev negatives (≈5 %). PQ-40 is measured, not hypothetical.
2. **Colour alone cannot separate lookalikes** (M4: 44/60 false merges) — hand-crafted appearance cues are out; the aerial-colour prefilter must stay a prefilter.
3. **Order-symmetric consensus with a mandatory REVIEW outcome removed every false merge on dev (0/60) and holdout (0/11)** at the price of sending 5/9 dev and 2/10 holdout true pairs to REVIEW (automation 44 % / 80 %). Safety is bought with REVIEW volume, as the owner required.
4. **Power is low:** 9+10 positives (correlated: one athlete has 4–5 appearances), holdout has 11 negatives, 3 hard, and no known lookalike pair (0143/0152 are in dev). "0 false merges" is therefore an upper bound of 6 % (dev) / 26 % (holdout), not proof. Holdout is reported as **run, not verified**.
5. **Leakage disclosed:** the M1 prompt's example of a generic trait ("a pink board of common shape") was written after the 0143/0152 failure, which sits in dev. Dev numbers for M1/M2 are optimistic; the holdout never influenced any prompt or threshold.
6. **Label noise:** appearances are the pipeline's actor tracks mapped to GT rides; wrong-track appearances (e.g. 0094 A3/A4) would flip a label. No frame-level boxes exist (PQ-19).
7. Per-pair dev results are not retained (artifact download blocked by the session egress proxy; metrics were read from the job log). The holdout pairs are in the results file.

## Implementation decision
`pipeline/identity_pair_consensus.py` (pure rules + prompt, tested by `scripts/test_identity_pair_experiment_contract.py`) is added and is the single source of truth for the experiment. **It is deliberately NOT wired into `identity.py` / `identity_failsafe.py` / `identity_evidence.py`:**
- The path-first `member_key` fix (PR #391) alone would release 0143+0152 (cycle 2). It may only ship together with pairwise-consensus evidence as the sole automatic merge route, replacing the group `stamp` that fabricates pairwise MATCH edges (three stamp sites: `identity._verify_multi_clusters`, `identity._merge_check_pairs`, `identity_failsafe._wrap_verify_multi_clusters`).
- That coupled change cannot be qualified on frozen replay (the verifier needs images) and a pipeline run is outside the $0 run budget; the evidence above is too weak to turn a measured 56 %-REVIEW rule into a default.
- Required before wiring: (a) a larger adjudicated pair set (second filming day, owner choice #3), (b) an integration test with an injected fake verifier at all three sites, (c) one capped controlled run, (d) human review of every auto-MATCH.

## Actor / boundary observation (free, from the artifacts; PQ-05/06)
For 0108 the tracker reports the actor continuously from 0.7 s to 9.21 s (max gap 0.07 s) while GT excludes everything after 6.82 s. The track-based interval gate cannot see this by construction (no `tail_*` issue is raised). The first failing stage for the excluded tail is the analyzer's outcome end, not tracking; a fix needs action-state evidence, not a looser/stricter track-gap threshold. 0115 starts 4.4 s late because the actor track only begins at 5.51 s (detector misses the paddle-in), also upstream of the gate.

## Next cycle (free first)
1. Outcome-end evidence for 0108-type tails (PQ-06) on frozen sidecars + a narrow video-segment check (budget permitting).
2. Catch-start from earliest plausible detection (PQ-05) with the same adversarial controls.
3. Grow the adjudicated identity pair set; only then wire the consensus rule.
