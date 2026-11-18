# Cycle 11 — ROI prioritisation, multi-sport architecture, boundary fix

**Production decision: NO-GO.**
- The release gaps remain open: coverage 15/24 FULL, ends, validity, the cross-source verifier, and PA-13. There is also no
  independent holdout.
- The cycle-11 boundary fix is **CANDIDATE_IMPROVED / MEDIA_VERIFIED** on the development batch. It is not production
  qualified.

**Paid experiment:** EXP-11-001.
- Run 44252428407 (namespace `qualification/q11-paid-01/`) met **every pre-registered condition**, including viewing
  the MP4s.
- Production fingerprint before and after the run: identical.

**Spend:**
- **Campaign:** $4 (the owner added $2).
- **Spent:** $1.280 before this cycle, plus EXP-11-001 at $0.228 (list-price estimate, 15 calls, cap $0.40), for
  **$1.508 in total**.
- **Remaining:** **$2.492**.
- The paid budget in `run_config.json` is reset to 0. The workflow refuses any budget above $2.492.

## 1. State sync
- **Branch `ccr-3f12fc2f-pdvirt`, PR #391:**
  - The owner closed the PR administratively. It was reopened at the owner's request ("Reopen #391 + run"), which
    resolves BLK-11-001.
  - The owner's two doc commits (gap register §13, README item 11) and `main` were merged into the branch.
  - Nothing was merged to `main`.
- **Tests:**
  - The cycle-11 contracts pass: onset O1–O6, football F1–F8, isolation, and policy.
  - Nine environment-bound contracts (real R2, YOLO, OpenCV) fail identically on the base.
- **Records updated:** gap register §14 and §14.1, registry (EVD-11-001…005, FIX-PQ-11-001/002, BLK-11-001 resolved),
  and the generated matrix (`--check` passes).
- **PA-15 corrected:** the cycle-10 "overrun" figures were a measurement error. They compared windows with a single
  segment instead of the contiguous GT ride.

## 2. ROI table
Scoring and the full ranking: `ROI-PRIORITIZED-REMEDIATION.md`.

| Gap | Estimated ROI | Generalization | Experiment | Cost | Outcome | Adopted |
|---|---|---|---|---|---|---|
| P0: PQ-02 / PA-11 auto-publishable false merge | threshold | 5 | FIX-PQ-10-001 (cycle 10), re-checked in EXP-11-001 | $0 extra | 0 wrong-identity publishable; 0143+0152 still withheld | kept |
| PQ-05 / PA-15 starts | **4.5 (highest)** | 5 (onset = motion of the bound actor; football O4/F4) | FIX-PQ-11-001 replay, then **EXP-11-001** | $0 + **$0.228** | FULL +1, missing −4.2 s, starts 8→7, 0 new waiting, no regression; MP4s viewed | **CANDIDATE_IMPROVED** (on the branch; holdout needed) |
| PA-08 0097+0115 split | 3.0 (owner decision) | 5 | review request `758fe7783e9c` (cycle 10) | $0 | awaiting owner | — |
| PQ-30 cross-sport | 2.5 | 5 | FIX-PQ-11-002 profiles + football contract | $0 | surf behaviour unchanged (EXP-11-001 identical elsewhere); football through the same engine (synthetic) | YES (architecture) |
| PA-14 shadowed compile | 2.0 | 3 | docstring marker | $0 | trap documented on the active path | YES |
| PA-16 metric | done | 5 | `quality_scorecard.py` | $0 | visible mixed 1 vs time-attributed 2 | YES |
| PQ-01 / PA-01 / 0155 / 0095 validity | 1.3 | 4 | — (needs an owner decision or negative GT) | — | not run: no signal that avoids tuning on the test set | — |
| PQ-06 / PA-15 ends | 0.8 | 4 | — | — | no reliable signal (EXP-10-002 failed) | — |

**ActionValidity (0155) was not run.** Without independent negative GT, any validity threshold would be fitted to the
same 24 cases. The current behaviour stays: an explicit failed take-off is INELIGIBLE, and a low-evidence action is
UNCERTAIN and reviewed.

**No identity experiment was run.**
- The remaining identity gains need owner decisions: 0097+0115 approve, 0074+0151 reject.
- Biometric face matching is excluded by mandate.
- The 0143+0152 negative stays safe: withheld and not publishable.

## 3. Quality table (same scorer, GT-v1 ae844a94, 24 rides)

`scripts/quality_scorecard.py --diagnostics --audit --gt`. Comparisons:
- "Previous best" is the best value found across 43583126199, 43920602179, q9-paid-02 and EXP-10-001. Where only an
  older scorer exists, that is stated.
- "Baseline" is EXP-10-001 (run 44166232265).

| Metric | Previous best | Current baseline (EXP-10-001) | Candidate (EXP-11-001) | Improvement | Regression |
|---|---:|---:|---:|---:|---|
| FULL rides | 14 | 14 | **15** | +1 | none |
| ≥95 % rides | 14 | 14 | **15** | +1 | none |
| Missing include s | 20.4 | 20.4 | **16.2** | −4.2 | none |
| Excluded frames | 517 (43583126199) | 999 | 999 | 0 | none |
| Non-GT seconds (waiting / tails) | – | 7.47 | 7.47 | 0 | none (0140 unchanged) |
| Incorrect starts / ends | – | 8 / 1 | **7** / 1 | −1 start | none |
| Wrong-actor frames (crop vs GT boxes) | – | 54 | 54 | 0 | none |
| Identity switches | – | 0 | 0 | 0 | none |
| Visible mixed reels (all withheld) | – | 1 | 1 | 0 | none |
| Time-attributed "mixed" (old metric, misleading) | – | 2 | 2 | — | — |
| False merges auto-publishable | 0 | 0 | 0 | — | none |
| Split athletes | 1 | 2 | 2 | 0 | none |
| Duplicate ride frames | – | 0 | 0 | 0 | none |
| Correct ready-for-Review (publishable correct) | 9 (43583126199, before the identity gate) | 4 | 4 | 0 | none |
| Withheld correct (QA false reject) | 0 (43583126199) | 6 | 6 | 0 | — |
| QA false pass | 1 | 1 | 1 | 0 | none |
| Render integrity (14 reels) | – | clean | clean: 0 decode errors, no freeze/black, 9:16 H.264 | — | none |
| Runtime | – | ~1 h | ~1 h (same workflow) | — | — |
| Actual cost | – | $0.206 | $0.228 | — | within cap |

**Fixed metric:**
- The old "mixed reels" count attributed time overlap with any GT ride, so it counted 0094's single-rider reel as
  mixed.
- The table now reports **visible** mixing (who is in the crop) as the metric, and keeps the old count only for
  reference (PA-16).

**Reading:**
- The only material change is the boundary-start improvement.
- Identity, waste, ends and publishability are unchanged, as pre-registered.
- The 43583126199 values for publishable correct and false reject predate the cycle-9/10 identity safety gate. That
  run auto-published wrong identities, so the gate makes them non-comparable.

## 4. Mandatory MP4 verification (EXP-11-001)

| Reel (SHA-256) | Segment | Seen in decoded frames (2 fps, reel time burnt in) | Pre-registered expectation |
|---|---|---|---|
| 0115 `c5f122af…ddf3cc` | starts at reel 0 s (source 1.5 s; was 4.5 s) | prone paddling 0–2 s, catching the wave 2.5–4.5 s, pop-up 5–5.5 s | opens on the paddle-in: **PASS** |
| 0094-cluster `423a3d65…3e5231` | 0142 at reel 65.27 s (source 0.0 s; was 1.2 s) | prone paddling 0–3 s, pop-up ~3.5 s, riding | opens on the paddle-in: **PASS** |
| 0112-cluster `2ab15f72…357a56` | 0140 at reel 49.3 s (source 1.4 s, unchanged) | paddling 0–1.5 s, pop-up 2–2.5 s; no stationary waiting; every other segment boundary in that reel opens in motion | no waiting at the opening: **PASS** |
| all 14 reels | — | H.264 2160×3840 30 fps, 0 decode-error lines, no freeze ≥ 0.5 s, no black ≥ 0.3 s | decode cleanly: **PASS** |

Full hashes are in EVD-11-005. The reels are in the run's `qualification-reels` artifact. No draft was deleted or
published.

## 5. Architecture progress
Document: `docs/architecture/MULTI-SPORT-PERFORMANCE-ENGINE.md`.

**Core vs profile:**
- **Core (sport-neutral):** tracking, stitching, actor binding, identity gates and review, lineage, windows and the new
  motion-supported onset, framing, render, EDL, QA, manifest, storage and isolation.
- **Profile:** action terms, failed-attempt rule, coverage-first, action types and phases, onset policy, reviewable
  description conflicts, framing height.
- **Every profile field has a live consumer.** One unused field (`shared_appearance_attributes`) was removed.

**Moved out of Core in this cycle:**
- surf terms and the failed-takeoff rule;
- the coverage rule;
- identity text-attribute conflicts;
- framing height;
- the lead-in rule (now Core onset plus per-profile `OnsetPolicy`).

**PerformanceEvent:**
- It is a typed view over the existing event dict, with explicit `missing_fields`.
- It converts labelled examples into engine events.

**MULTI_SPORT_COMPATIBILITY of FIX-PQ-11-001: PASS (architecture).**
- Onset is computed from the bound actor's displacement in body heights per second; it has no surf term.
- The surfing (O1–O3) and football (O4, F4) contracts both pass.
- No surf/wave/board/paddle condition was added to Core.

**Still surf-specific:** the migration list (architecture doc §3) covers:
- the analyzer, identity and QA prompts;
- the surf editor and ride segmentation;
- the sport stamp in missed-moment rescue;
- the equipment/wetsuit identity categories;
- the fall-tail constant.

## 6. Football extension

**Profile:** `pipeline/sport_profiles/football.py`.
- **Actions:** pass, shot, dribble, tackle, and others.
- **Phases:** build-up → ball contact → action → outcome.
- **Onset:** ≥ 0.3 body heights/s, at most 4 s.
- **Identity:** no kit-colour conflict is reviewable.

**Synthetic architecture contract:** `scripts/test_football_profile_architecture_contract.py`.
- 8 checks (F1–F8) and 14 assertions in total, all PASS. This meets the mandated 10.
- **Covered:** profile registration; labelled `PerformanceEvent` conversion; binding among a same-kit team-mate and an
  opponent; onset on the run-up; coverage and ineligibility; identity gate; a 9:16 render whose decoded centre is the
  target; EDL; explicit missing fields; surfing unchanged.

**This proves architecture only. It is not football accuracy.** Real football still needs:
- ball linkage;
- shirt-number OCR (non-biometric);
- a kit-aware identity rule;
- football prompts;
- football GT and a holdout;
- calibration.

## 7. Experiments

| Experiment | What | Result | Cost | Adopted |
|---|---|---|---|---|
| Start-rule replays | lead-in cap 3 s / 6 s; stitching without motion | +0.9 to 1.27 s waiting on 0140 every time | $0 | rejected (single-source global widening) |
| FIX-PQ-11-001 replay | Core motion-supported onset, surfing 0.2 body heights/s | −3.7 s missing, 0 new waiting | $0 | candidate |
| Football architecture contract | synthetic MP4 through the production path | 8/8 PASS | $0 | yes (architecture) |
| **EXP-11-001** (paid, pre-registered) | rendered proof of FIX-PQ-11-001 | all conditions met; MP4s viewed | **$0.228** | **CANDIDATE_IMPROVED** |

The replay predicted 16.7 s missing and a 0142 start at 0.5 s. The real run produced 16.2 s and 0.0 s, because the
real run's analyzer gave a slightly different setup. The direction and the protected metrics matched the replay.

## 8. GO/NO-GO and next steps

**NO-GO for production.**

**GO** for keeping FIX-PQ-11-001 on the branch as an improved candidate. Its limits:
- it was evaluated on the development batch only (one negative, 0140, and four positives);
- the threshold is not calibrated on independent data.

**Next steps, by ROI:**
1. **Owner decisions (free, ROI 3.0+):**
   - identity requests `758fe7783e9c` (0097+0115, approve) and `7b2a6964427f` (0074+0151, reject);
   - PA-01 (do uncatalogued riders get reels?);
   - PA-03 (0094 end: 13.2 s or 16 s).
2. **An independent holdout session for the onset rule** before calling it qualified. It needs new GT, not GT-v1.
3. **PA-13 stable draft keys** (ROI 1.9, free contract).
4. **A negative-pair set (≥ 30 lookalikes)** before any cross-source verifier experiment.

The remaining $2.492 stays unspent until one of these has a pre-registered paid run.
