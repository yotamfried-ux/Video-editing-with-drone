# Policy proposal — reels for people who are not in a catalogue (PA-01)

**Status: PROPOSED.**
- It is not active in production as a policy change.
- The current pipeline behaviour already matches points 1–6 below; this document makes the separation explicit and
  testable.
- Any change to production behaviour needs explicit owner approval.

**Commercial goal:** find every person who performed a valid action and can get a reel. A person does **not** have
to be catalogued in advance.

## The stages are separate decisions

| Stage | Who or what decides | Rule |
|---|---|---|
| 1. A new person is detected | perception + tracking (Core) | Any tracked person can be a candidate. No catalogue is consulted. |
| 2. A valid action | eligibility + `SportProfile` evidence | Independent evidence is required. No positive evidence → UNCERTAIN, sent to review. An explicit failed attempt → INELIGIBLE. The same rule applies to every person. |
| 3. Candidate reel | editor + render (Core) | The reel is cut for the tracked person only. |
| 4. QA | all QA gates | The reel must pass every gate. A person outside the catalogue gets no relaxation. |
| 5. Approval | **operator only** | The pipeline never writes `approved/` and never publishes. |
| 6. Binding to a customer | **operator only** | Pipeline athletes are scoped to `<recording date>:<run athlete id>`. Joining athletes across sessions or accounts is an operator action. There is no automatic binding by description, appearance or face. |
| 7. Distribution | delivery job, after approval | Unchanged. |

**Also:**
- No biometric face recognition is used for customer binding, or for anything else
  (`scripts/verify_no_biometric_runtime_dependencies.py`).
- **Measurement:** a person outside GT-v1 is never counted as a GT success. A reel of another person is never shown
  as a success for the tagged athlete. `quality_scorecard.py` reports such reels apart:
  - `publishable_non_gt_person`;
  - `non_gt_person_reels_audited`;
  - `qa_false_pass_gt_cohort`.

## 0095 under this policy (EXP-11-001, run 44252428407)

**What the reel shows:**
- **Reel:** "DRAFT_Man in a white long-sleeve top and dark shorts on_20261118.mp4", source 0.0–6.32 s, track 10003.
- **Frames viewed at 2 fps:**
  - 0.0–5.0 s: the rider stands and rides the wave (the recording starts mid-ride, so the start is source-limited);
  - 5.5 s: he falls;
  - 6.0 s: fade-out.
- **Verdict:** a **valid action of an uncatalogued person**. It is a candidate reel for that person.

**How it is scored:**
- It is **not** a GT-v1 success. GT-v1 marks this interval *exclude / unusable* for the tagged athlete 6c84aed0, who
  rides at the left of the same wave.
- It is **not** a reel of 6c84aed0. Its athlete key is the run's own person, and the draft is named from its own
  description.
- The scorer still counts it in the legacy `qa_false_pass` (1). The cycle-12 split shows 1 publishable non-GT-person
  reel and 0 GT-cohort false passes.

**To sell it**, the operator must approve it and decide who the rider is.

## Contract

`scripts/test_uncatalogued_person_policy_contract.py` (U1–U6), in CI (`cost-time-optimizations-check.yml`).

## Owner decision needed

Do you approve this policy as the product rule? It means candidate reels for uncatalogued people stay in Review,
under operator control.
