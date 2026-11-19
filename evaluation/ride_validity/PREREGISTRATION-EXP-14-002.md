# EXP-14-002 — observed action validity on real clips (pre-registered; revision 2, cycle 14b; NOT RUN)

Revision 2 follows the owner's review of PR #402. Rev. 1 had three problems: the verifier was not wired into
production; low confidence could still produce VALID; and the sampling (12 crops at 0.5 s from the start) could
miss the action. All three are fixed before any model call:

- **Code under test (production, not a harness copy).**
  - `pipeline/action_validity_runtime.observe_event` is what `publishable_reel_policy._qualification_inputs` calls
    for every final shot.
  - `pipeline/action_validity` (`parse_observations`, `decide`, prompt `action-validity-v2`).
  - The surfing profile's `ActionValidityPolicy`: established = prone, kneeling or standing riding; transitional =
    popping_up; min_established_sec 2.0, set a priori.
- **Sampling.**
  - Two interleaved passes, each spanning the full final window: [start, end], both edges included.
  - Up to 16 crops per pass, spacing ≤ 1 s for windows up to 15 s.
  - Before any call, the bound (stitched) target must be in ≥ 75 % of samples and present at both take-off and
    ending. Otherwise the result is UNCERTAIN with no model call.
- **Answers.** The model must describe exactly the requested crop times.
- **Decision.**
  - VALID needs 2 agreeing passes, none of them low-confidence.
  - INVALID needs 2 agreeing high-confidence passes.
  - Everything else is UNCERTAIN, which means review and never VALID.
- **Input (development split; not a holdout).** The 25 selected final windows of run 44388634790 plus two controls:
  - 0108 tail, 6.82–9.23 s, track 10007 (ADJ-14-001);
  - 0094 track-37 tail, 13.2–22.5 s (ADJ-14-002).
- **Labels** (`scripts/score_action_validity_experiment.py`, from GT-v1 plus `evaluation/adjudications`):
  - 23 valid;
  - 3 valid by owner policy (0095 uncatalogued rider, 0108 tail, 0094 tail);
  - 1 invalid (0155).
- **Failure conditions (any → gate stays OFF):**
  - ≥ 1 valid window INVALID;
  - 0155 VALID;
  - more than 2 valid windows UNCERTAIN;
  - pass agreement below 80 %;
  - any window unscored (error or skip).
- **Success** (only if no failure condition is hit): 0155 INVALID (or UNCERTAIN, i.e. review), with 0 false
  rejections and at most 2 UNCERTAIN valid windows.
  - Even then this is development evidence only; 0155 is a known case.
  - The gate may next be enabled only for a strict cold run.
  - Blind generalisation stays BLOCKED until new labelled footage, including failed attempts, exists.
- **Cost.**
  - Estimate: 27 windows × 2 calls of gemini-2.5-flash, one ~1024×1024 grid each. Roughly 1.5k input and 2k
    output+thinking tokens per call, about $0.0055 per call, so **≈ $0.30**.
  - **Hard cap $0.40**, enforced twice:
    - `integrations.qualification.check_llm_budget` with `SPORTREEL_LLM_BUDGET_USD=0.40`;
    - the harness stops before any window that could exceed the cap.
- **Execution.**
  - The `avexp-dry` label: real R2 media, grid build and identity/coverage checks, no model; $0.
  - The `avexp-paid` label: applied only after explicit owner approval of the $0.40 cap.
  - Read-only R2. JSON-only artifact (public repository). No publication.
