# Cycle 11 — ROI prioritisation, multi-sport architecture, boundary fix (interim)

**Production decision: NO-GO**, unchanged from cycle 10.

**Paid experiment: not launched.** PR #391 was closed (not merged) from the owner's account 25 s after the
`qualrun-paid` label for EXP-11-001 was applied. Label-triggered runs need an open PR, and the close may be a stop
signal, so no money was spent (BLK-11-001).

**Spend:** $4 campaign (the owner added $2); $1.280 spent; $2.720 remaining.

## 1. State sync
- **Branch:** `ccr-3f12fc2f-pdvirt`. The owner's two doc commits (gap register §13, README item 11) were merged in, and
  `main` was merged in (append-only gap register kept). Nothing was merged to `main`.
- **CI:** cycle-10 head 0ccc0ee0 green; cycle-11 contracts pass locally. Nine environment-bound contracts (real R2,
  YOLO, OpenCV) fail identically on the base without these changes.
- **Gap register §14, registry and matrix updated.**
- **PA-15 corrected:** the cycle-10 "overrun" figures were a measurement error (single segment versus contiguous GT
  ride).

## 2. ROI prioritisation
Full table and scoring: `ROI-PRIORITIZED-REMEDIATION.md`.

| Gap | Estimated ROI | Generalization | Experiment | Cost | Outcome | Adopted |
|---|---|---|---|---|---|---|
| PQ-05 / PA-15 starts | 4.5 (highest) | 5 | FIX-PQ-11-001 replay; EXP-11-001 pre-registered | $0 (paid run pending) | missing include −3.7 s, ≥95 % +1, starts 8→7, 0 new waiting | CANDIDATE (not rendered) |
| PQ-30 cross-sport | 2.5 | 5 | FIX-PQ-11-002 profiles + football contract | $0 | surf behaviour unchanged, football through the same engine (synthetic) | YES (architecture) |
| PA-16 metric | done | 5 | `quality_scorecard.py` | $0 | visible mixed 1 versus time-attributed 2 | YES |
| PA-08 0097+0115 | 3.0 (owner decision) | 5 | review request from cycle 10 | $0 | awaiting owner | — |
| PQ-06 / PA-15 ends | 0.8 | 4 | — | — | no reliable signal (EXP-10-002 failed) | — |
| PQ-01 / PA-01 / 0155 / 0095 | 1.3 | 4 | — | — | needs an owner decision or more negative GT | — |

## 3. Quality results (same scorer, GT-v1)

| Metric | Previous best | EXP-10-001 (baseline) | Candidate (replay) | Improvement | Regression |
|---|---:|---:|---:|---:|---|
| FULL rides (of 24) | 14 | 14 | 14 | 0 | none |
| ≥95 % rides | 14 | 14 | **15** | +1 | none |
| Missing include s | 20.4 | 20.4 | **16.7** | −3.7 | none |
| Excluded frames | 517 (43583126199) | 999 | 999 | 0 | none |
| Non-GT seconds (waiting / tails) | – | 7.47 | 7.47 | 0 | none (0140 unchanged) |
| Incorrect starts / ends | – | 8 / 1 | **7** / 1 | −1 | none |
| Wrong-actor frames (audited) | – | 54 | 54 | 0 | — |
| Visible mixed reels (all withheld) | – | 1 | 1 | 0 | — |
| False merges auto-publishable | 1 (q9-paid-02) | 0 | 0 | — | — |
| Split athletes | 1 | 2 | 2 | 0 | — |
| Publishable correct / QA false pass / false reject | 9 / 3 / 0 (43583126199) | 4 / 1 / 6 | 4 / 1 / 6 | 0 | — |
| Actual cost | – | $0.206 | $0 (replay) | — | — |

The candidate is a **replay**. It is not a rendered result, and no MP4 exists for it yet.

## 4. Architecture progress
Document: `docs/architecture/MULTI-SPORT-PERFORMANCE-ENGINE.md`.

**Already generic and reused unchanged:**
- tracking, stitching and actor binding;
- identity gates and owner review;
- lineage, windows and intervals;
- framing, render and EDL;
- QA, manifest and approval;
- storage and isolation.

**Moved into profiles in this cycle:**
- surf terms and the failed-takeoff rule;
- coverage-first;
- identity text-attribute conflicts;
- framing height;
- build-up onset policy.

**New interfaces:**
- `SportProfile` / `OnsetPolicy` (every field has a consumer);
- `profile_for` / `profile_for_event` / `default_profile`;
- `PerformanceEvent` (typed view, explicit missing fields);
- Core `action_onset`.

**Still surf-specific** (migration list, §3 of the architecture document):
- analyzer and identity prompts;
- surf editor;
- ride segmentation and validity;
- missed-moment rescue's sport stamp;
- the identity engine's equipment/wetsuit categories;
- the fall-tail constant.

**Football:**
- **Profile:** written and run through the engine in a synthetic real-MP4 contract (F1–F8 PASS).
- **Still needed:** ball linkage, shirt-number OCR, a kit-aware identity rule, prompts, football GT and holdout, and
  calibration.
- **Reusable without change:** orchestrator, render, review, evidence and storage.
- **Not proven:** any football accuracy.

## 5. Experiments

| Experiment | What | Result | Adopted |
|---|---|---|---|
| Start-rule replay | lead-in cap 3 s / 6 s; stitching without motion | +0.9 s waiting on 0140 every time | rejected |
| FIX-PQ-11-001 replay | Core motion-supported onset, surfing profile 0.2 body heights/s | −3.7 s missing, 0 new waiting | candidate |
| Football architecture contract | synthetic MP4 through production binding, windows, eligibility, gate, framing and editor | 8/8 PASS (after fixing two test bugs: drawbox did not animate; a missing-field expectation) | yes (architecture) |
| EXP-11-001 (paid, pre-registered) | rendered proof of FIX-PQ-11-001 | **not run** (BLK-11-001) | — |

- **Videos viewed this cycle:** synthetic football frames only (decoded centre check, one frame inspected). No new real
  reels were rendered.

## 6. Next highest-ROI step
EXP-11-001 needs an open PR and your confirmation, at a hard cap of $0.40. It would render the onset fix on the 24
sources, view the 0115, 0142 and 0140 MP4s, and score them with the pre-registered thresholds.

Owner decisions that unblock free improvements:
- **Identity requests:** `758fe7783e9c` (0097+0115) and `7b2a6964427f` (0074+0151).
- **PA-01:** whether uncatalogued riders get reels.
- **PA-03:** whether the 0094 ride ends at 13.2 s or 16 s.
