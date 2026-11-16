# Cycle 4 — fail-closed identity merge in the pipeline; boundary root causes (PQ-02/03/10/17/23/40; PQ-05/06 analysed)

**Owner decisions applied:** (1) a new filming day will be added later as an independent holdout (not awaited); (2) cross-clip merge is fail-closed — both image orders, positive evidence, no contradiction, every pair, no transitive merge, doubt → REVIEW; (3) Gemini budget up to $2 cumulative for the experiment, no full paid pipeline run.
**Status:** identity — PATCHED · TESTED (fake verifier, red on `main`, green here) · REPLAYED (policy on both baselines) · real-cluster check run. Boundaries — ANALYSED, not patched (blocked, see below). Not MEDIA_VERIFIED, not HOLDOUT_VERIFIED. **PR #396 stays a draft; #391 and the key fix are NOT merged separately.**
**Spend:** cycles 3+4 ≈ **$0.83 of $2** (token-based estimate); no full pipeline run.

## 1. What changed in the pipeline (identity)
`identity_evidence.member_key` is now path-first **and** pairwise-consensus evidence is the **only** accepted proof of a cross-clip merge (`ACCEPTED_METHODS == {pairwise_consensus}`). Shipping only the key fix would have released 0143+0152 (cycle 2).

| Path | Before | Now |
|---|---|---|
| `stages.identity._verify_multi_clusters` (group call, "plausibly the same") | stamped MATCH edges for pairs it never examined | `identity_pair_consensus.verify_multi_clusters` |
| `identity_failsafe._wrap_verify_multi_clusters` (the runtime wrapper) | duplicate of the above | same single function; model access via `identity._consensus_ask` |
| `stages.identity._merge_check_pairs` (two singletons, one order, "lighting shifts colours") | one-order call, confidence "high" | both orders + consensus; stamped with the pair's own digests |

Rules (`pipeline/identity_pair_consensus.py`, validated in cycle 3): MATCH needs both orders MATCH, ≥2 specific matching features, no cited contradiction, not generic-only. Every cross-source pair of a cluster is checked; all MATCH → `stamp_pairwise` (each edge keeps both response digests); any pair NO_MATCH → split; any doubt, error, missing image or colliding member key → **REVIEW**: the cluster stays together without evidence and the existing gate withholds it (`kept_together_unconfirmed`). Legacy `stamp()` evidence (`image_verifier`, `pair_check_singletons`) is still writable but never covers a cluster (`unaccepted_method`).

## 2. Evidence
**Contracts** — `scripts/test_identity_consensus_integration_contract.py` (new, wired into CI): C1 true pair stamped, passes the real gate before and after `_strip_internal_fields`; C2 generic lookalike (0143+0152-like) → REVIEW at both verifier paths and the merge-check path; C3 order disagreement / empty / contradiction / model failure; C4 no transitive merge (A~B, B~C, A~C in doubt → not stamped; 5 members need all 10 pairs); C5 legacy route dead, only the consensus prompt is ever sent, no Files-API upload, no group prompt in the source; C6 key stable across the strip, independent of `_clip_index`, colliding keys never covered; C7 tampering; C8 `ACCEPTED_METHODS` and no other writer of `_visual_verified`; C9 no re-asking; C10 error = REVIEW. **Red on `main`** (`AttributeError`/legacy evidence covers and passes the gate/key changes under the strip), green here. Seven older contracts that encoded the group-call policy were rewritten to the fail-closed policy (`test_release_safety_invariants`, `test_output_qualification` Q6, `test_verified_cluster_merge`, `test_identity_merge_check`, `test_root_cause_fixes`, `test_identity_failsafe`, `test_pipeline_quality`). The remaining failing scripts in the repository fail identically on `main` (missing `cv2`/`moto`/`boto3`/`psycopg`/`ultralytics`, mobile tokens) — untouched.

**Real clusters** (run 43974708319; `pipeline.identity_pair_consensus.verify_cluster`, the production function, on the multi-source clusters of run 43920602179; cost $0.18):

| Cluster | GT | Pair decisions | Verdict |
|---|---|---|---|
| 0143 + 0152 | **two athletes (mixed)** | REVIEW | **REVIEW — not released** |
| 0160 + 0163 | same athlete | MATCH | MATCH → stamped |
| 0070 + 0108 | same athlete | MATCH | MATCH → stamped (the reel is still blocked by its excluded 0108 tail, §3) |
| 5-source cluster (A7) | same athlete | 8 MATCH, 2 REVIEW | REVIEW (needs the operator) |
| 5-source cluster (A2, with a non-ride source) | same athlete | 5 MATCH, 5 REVIEW | REVIEW |

Caveat: the experiment cut 6-crop sheets; the pipeline's own thumbnails are 4-crop sheets, so the production numbers can differ. 3 of 5 clusters (incl. both 5-source ones) need an operator under the owner's no-transitive rule.

**Frozen replay on both baselines** (`scripts/identity_gate_replay.py`; frozen artifacts have no consensus evidence, so every multi-source part is REVIEW until a run re-verifies it):

| metric | best 43583126199 before → after | latest 43920602179 before → after |
|---|---|---|
| parts withheld by the policy | 5 | 0 |
| published | 12 → 7 | 5 → 5 |
| published_correct | **9 → 6** | 4 → 4 |
| published_wrong_identity | 1 → 0 | 0 → 0 |
| published_nonride | 2 → 1 | 1 → 1 |
| correct reels withheld (pending REVIEW) | 0 → 3 | 6 → 6 |

**This is the known price of decision 2, stated plainly:** against the best historical run the strict rule removes one confirmed wrong-athlete publish and one non-ride publish, and moves 3 correct multi-source reels to REVIEW until they are re-verified or approved by the operator. No protected metric of the latest run changes. It is a recall loss, not hidden: the three reels are listed as withheld.

## 3. Boundary root causes (PQ-05/06) — analysed from the frozen sidecars, no patch
- **0115 (starts 4.4 s late).** `window_refinement.refine_event_window` only looks at detections in `[start−1.0, end+1.0]`, so `first_track_sec` (5.51) is "first detection ≥ start−1", not the actor's first appearance. The sidecar shows the pipeline's actor track `10043` detected **continuously from 1.9 s** (no gap > 0.4 s). The cut start (4.5 s) comes from the analyzer's `setup_start` capped by `SETUP_LEAD_IN_MAX_SEC`/`extend_to_setup`. GT starts at 0.1 s: even the tracker's earliest observation (1.9 s) is 1.8 s later, so tracking alone cannot meet ≤0.5 s. First failing stage: analyzer setup + lead-in cap; second: tracker start.
- **0108 (tail to 9.2 s, GT ends 6.82 s).** The actor track is continuous 0.7–9.21 s (max gap 0.07 s), so the track-based interval gate is blind to it by construction. The outcome end must come from action-state evidence (the ride stopped), not from a track-gap threshold. Per-frame bbox kinematics are not usable (the drone follows the surfer).
- **Not patched because:** (a) owner choice #1 (include the paddle-in/catch lead-in?) is still open and fixes the target; (b) an outcome-end verifier needs video (a narrow segment check) with a held-out ride set, which is a new experiment, not a free replay; (c) widening the look window or the lead-in cap on the examples alone is the "tune on the examples" change the charter forbids.

## 4. Gaps
PQ-40 PATCHED/TESTED, real-cluster REPLAYED (the false merge is REVIEW); PQ-10/23 PATCHED/TESTED; PQ-02 improved for the measured pair, not HOLDOUT_VERIFIED; PQ-03 (false splits) **worse by design** (REVIEW instead of merge); PQ-05/06 root cause documented, BLOCKED on owner choice #1 + a video check; PQ-17 partial (6-crop vs 4-crop production thumbnails not yet reconciled).

## 5. Next
1. Add the new filming day as an independent holdout (owner); run the pair experiment on it once.
2. Decide whether the pipeline's contact sheet should be 6 crops (the validated setting) — a measurable change to `track_bbox_sheet`.
3. Operator REVIEW queue for the withheld multi-source reels (what the strict rule produces).
4. PQ-05/06: choose the lead-in policy, then an outcome-end check with a held-out ride set.
