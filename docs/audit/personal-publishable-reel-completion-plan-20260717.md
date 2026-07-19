# Personal publishable reel completion plan

Date: 2026-07-17  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Active PR: `#182`  
Business source of truth: `README.md` → **Product vision — source of truth**  
Audit state: **centered-athlete and silent-output implementation is contract/CI/review validated; production experiment pending**

## 1. Business objective

For every distinct athlete with at least one complete, visible, usable action, the pipeline must produce a personal silent video centered on that athlete. The file must be ready for direct social-media upload; the athlete adds platform-native music or other audio after download.

“Personal” describes who the edit is about, not how many people are visible. A football highlight normally includes teammates and opponents. A surf ride may include another surfer entering or riding the same wave. These actions remain eligible when the target athlete stays identifiable, continuous, central to the edit, and clearly owns the featured action.

A run is not successful merely because GitHub Actions, rendering, upload, or an LLM call completed. It is successful only when this chain is proven:

```text
usable athlete detected
→ canonical identity is traceable
→ one featured athlete remains central and attributable
→ sport-specific usable actions are represented
→ complete actions are packed into Parts of at most 90 seconds
→ one canonical silent video is selected per Part
→ the output is uploaded to REVIEW
→ real final QA and deterministic technical gates pass
→ every eligible athlete has one primary publishable reel
  or an explicit evidence-backed no-output reason
→ GitHub, the durable run row, and the operator live status agree on the result
```

## 2. Official documentation research

Only first-party documentation is used as external design evidence. The silent-output requirement is an explicit SportReel product decision, not a claim derived from the AI-provider documentation.

### 2.1 Google Gemini — video understanding

Source: https://ai.google.dev/gemini-api/docs/video-understanding

Official guidance used:

- Gemini can extract video events and refer to timestamps.
- Timestamp references use `MM:SS`.
- Default visual processing samples at approximately 1 FPS.
- Fast actions may lose detail at that sampling rate; custom sampling or slowed relevant clips may be required.
- One video per prompt is recommended for optimal results, with the Files API for large or reusable inputs.

SportReel decisions:

- LLM event detection is not sufficient identity evidence for fast sports by itself.
- Timestamp output is normalized and semantically validated.
- Fast-action and small-subject footage remains backed by perception/tracking and deterministic post-validation.
- Complete actions and timestamps are requested from the model, but the application owns acceptance.

### 2.2 Google Gemini — structured outputs

Source: https://ai.google.dev/gemini-api/docs/structured-output

Official guidance used:

- Gemini supports JSON-Schema-constrained outputs.
- Strong typing, enums, and clear field descriptions improve reliability.
- Valid JSON does not guarantee semantically valid values.
- Applications still need semantic validation and robust error handling.

SportReel decisions:

- The runtime validates unique person IDs, event arrays, finite start/end values, positive windows, score range, and action type after parsing.
- Invalid or reversed timestamps cannot silently become publishable content.
- Final business state is stored in an application-owned manifest rather than inferred from model prose.

### 2.3 Google Cloud Video Intelligence — person detection and object tracking

Sources:

- https://cloud.google.com/video-intelligence/docs/feature-person-detection
- https://cloud.google.com/video-intelligence/docs/feature-object-tracking

Official guidance used:

- Person detection returns temporal segments and bounding boxes.
- Object tracking treats individual instances as separate tracks over time.
- Frame-level person presence is different from instance tracking.
- Very small objects may not be detected reliably.

SportReel decisions:

- “Another person is visible” is not an identity defect.
- A personal reel requires one featured athlete with reliable identity and action attribution, not a single-person frame.
- Teammates, opponents, officials, and other surfers may remain visible or active when the target athlete remains clear and continuous.
- Another surfer on the same wave is allowed when the target surfer remains central; genuine target loss, identity switch, or ambiguous action ownership remains blocked.
- Uncertain identity is split or review-blocked; the pipeline does not guess.

### 2.4 OpenAI — Evals and graders

Sources:

- https://developers.openai.com/api/reference/resources/evals
- https://developers.openai.com/api/reference/resources/graders

Official guidance used:

- Evals define explicit data schemas and testing criteria.
- Deterministic and model-based graders can be combined.
- Evaluation should be reproducible against named test items and expected outcomes.

SportReel decisions:

- Coverage, identity ownership, primary-athlete continuity, upload confirmation, proven silent state, duration, aspect, resolution, Part order, duplicates, final QA, and terminal status are deterministic gates.
- Model-assisted QA grades social quality only after deterministic output checks.
- Positive and negative fixtures are both required.

### 2.5 Anthropic — prompt clarity and evaluation tooling

Sources:

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool

Official guidance used:

- State desired behavior and output explicitly.
- Explain why a rule matters.
- Examples should match the behavior being encouraged.
- Test prompts across evaluation cases rather than judging one result.

SportReel decisions:

- The analyzer prompt states the business obligation to serve every eligible athlete.
- It explicitly says one usable action is enough.
- It explicitly says a personal reel is centered on one target athlete and may contain other active people.
- Football group plays and two surfers on the same wave are positive eval cases when the featured athlete remains clear.
- The global athlete contract remains separate from sport-specific rules such as all-waves surfing coverage.

## 3. Product definitions

### Eligible athlete

A distinct athlete with at least one complete, visible, usable action after timestamp, identity, primary-athlete, and readability validation.

### Featured athlete / primary athlete

The athlete for whom the personal reel is being created. The edit, tracking, action attribution, and narrative stay centered on this athlete. Other people may be visible or actively participate.

### Publishable reel

A canonical output that:

- is centered on one featured athlete;
- may include other people when identity and action ownership remain clear;
- was successfully uploaded to REVIEW;
- passed real final QA;
- proves that no audio stream is present;
- is vertical 9:16;
- has acceptable resolution and supported encoding;
- is at most 90 seconds;
- contains complete actions rather than fragments;
- is independently understandable and uploadable;
- leaves music/audio selection to the athlete after download.

### Primary reel and supplemental Parts

- Part 1 is the athlete's primary reel.
- Parts 2+ are permitted only when complete usable actions cannot fit under the platform limit.
- Every Part independently satisfies the publishable contract.
- A complete action is never split between Parts.

### Hard reject

An evidence-backed reason that makes an action or athlete output genuinely unusable, including:

- no complete action was established;
- the target athlete/action is not readable;
- identity or action ownership cannot be established safely;
- the camera or tracker switches to another athlete;
- duplicate physical action;
- invalid source timestamp;
- source content ends before a complete usable action can be represented.

The following are **not** hard rejects by themselves:

- low score;
- weak opening order;
- removable dead time;
- teammates or opponents in a football play;
- people in the background;
- another surfer entering or riding the same wave;
- a file without audio—the silent file is the required product.

## 4. Implementation plan and evidence

A checked implementation item means code and a deterministic regression were added. Final-head CI and real footage remain separate closure requirements.

### Stage A — lock the vision in the repository

- [x] Define the outcome as one personal video per eligible athlete.
- [x] Replace “one person visible” with “one featured athlete centered.”
- [x] State that active teammates, opponents, and same-wave surfers may remain.
- [x] Define silent video as the only publishable output.
- [x] State that the athlete adds audio after download.
- [x] Link this audit from README.

Evidence:

- `README.md`
- `docs/audit/primary-actor-continuity-policy.md`
- `scripts/test_publishable_reel_business_contract.py`
- `scripts/test_single_athlete_selection_policy_contract.py`

### Stage B — centered-athlete cross-sport analyzer contract

- [x] Add a global instruction that applies across sports.
- [x] Require every distinct athlete with at least one usable action to be returned.
- [x] State that one usable action is sufficient.
- [x] Define personal reels by target-athlete continuity rather than visible-person count.
- [x] Allow `competing_active_subjects:true` when the featured athlete is explicitly clear, stable, and attributable.
- [x] Preserve surfing's all-waves override.
- [x] Preserve team-sport attribution to the athlete performing the meaningful play.
- [x] Validate person IDs, event arrays, numeric fields, score range, action type, and timestamp order after parsing.
- [x] Fail invalid semantic model output instead of publishing it.

Deterministic evidence:

- A football scorer remains valid while defenders and teammates are active in the play.
- A complete surf ride remains valid while another surfer enters the same wave.
- The same-wave case becomes review-required when identity continuity or target focus is uncertain.
- One football action and one skateboard trick are sufficient for primary outputs.
- Distinct athletes remain separate by canonical identity ID even when descriptions are similar.
- Six surf waves remain exactly once; failed takeoffs remain hard rejects.

Files:

- `pipeline/primary_actor_policy.py`
- `pipeline/single_athlete_selection_policy.py`
- `pipeline/publishable_reel_policy.py`
- `pipeline/performance_reel_policy.py`
- `scripts/test_single_athlete_selection_policy_contract.py`
- `scripts/test_cross_sport_publishable_eval_matrix.py`

### Stage C — canonical silent output and audio-stage removal

- [x] Add `pipeline/silent_output_policy.py` as an explicit product policy.
- [x] Disable music selection by replacing `_pick_music` with a no-op.
- [x] Force `compile_reel` to ignore positional or keyword `music_path` values.
- [x] Force loop-bookend processing to remain video-only.
- [x] Keep the clean silent render as the canonical Part.
- [x] Delete legacy `_music.mp4` variants.
- [x] Reject audio-bearing files with `unexpected_audio`.
- [x] Fail closed when the audio state cannot prove silence.
- [x] Install the policy in GitHub Actions, shared bootstrap, local runs, surf runs, and reset/rerun entrypoints.

Deterministic evidence:

- Music picker always returns `None`.
- Direct compile calls cannot pass music into FFmpeg.
- Clean + music keeps the clean silent file and deletes the music file.
- Audio-only output produces no publishable file.
- A valid silent vertical file passes.
- Multiple Parts produce exactly one silent canonical output per Part.

Files:

- `pipeline/silent_output_policy.py`
- `pipeline/bootstrap.py`
- `scripts/run_tracked.py`
- `scripts/test_silent_output_policy_contract.py`
- `scripts/test_publishable_reel_business_contract.py`

### Stage D — athlete-level publishable manifest

- [x] Create run-scoped `publishable_reel_manifest.json`.
- [x] Record one row per eligible athlete outcome.
- [x] Record sport, athlete IDs/label, action lineage, Parts, QA, technical specs, upload state, primary output, supplemental outputs, and blocking reasons.
- [x] Store `has_audio:false` as required technical evidence.
- [x] Derive a stable run-local key from canonical IDs, label, and source/action lineage.
- [x] Write the manifest atomically.
- [x] Protect parallel upload updates with an `RLock`.
- [x] Scope editor-to-QA lineage, variant failures, and final QA evidence to one invocation-unique token.
- [x] Include the manifest in diagnostics.

Deterministic evidence:

- A rendered Part is not publishable before a real REVIEW upload succeeds.
- Two parallel Part uploads both remain in the manifest.
- Two matching athlete labels cannot overwrite or clear each other's final QA evidence.
- Duplicate canonical athlete ownership and duplicate output names fail.
- QA-blocked, audio-bearing, and technically invalid outputs are not counted as publishable.

### Stage E — production business gate and status alignment

- [x] Add deterministic `check_publishable_reel_manifest.py`.
- [x] Fail when an eligible athlete lacks a primary publishable reel.
- [x] Reconcile the final manifest with `athlete_coverage_report.json`.
- [x] Match coverage only through canonical `athlete_id` lineage; text labels are not identity proof.
- [x] Fail unresolved coverage, incomplete identity lineage, or accountability below 1.0.
- [x] Require `has_audio:false` for every publishable Part.
- [x] Fail `has_audio:true` as unexpected audio.
- [x] Fail an unknown/missing audio state rather than assuming silence.
- [x] Fail duplicate ownership, duplicate output names, missing REVIEW upload, wrong aspect, low resolution, duration over 90 seconds, or final QA failure.
- [x] Persist operator publishability authority under the immutable Drive file ID or canonical R2 object key.
- [x] Refuse filename-only authority fallback and filename/object mismatches.
- [x] Preserve diagnostics when the business gate fails.
- [x] Make the business-gate result the final GitHub Actions exit code after successful processing.
- [x] Propagate post-run business failure to the durable run and operator live status.
- [x] Preserve true `no_input` behavior only for a proven empty/evidence-free run.

Deterministic evidence:

- Valid silent two-athlete cross-sport manifest passes.
- Audio-bearing and unknown-audio Parts fail.
- Missing athlete output or upstream athlete fails.
- Same label with a different canonical athlete ID does not match.
- R2 and Drive REVIEW objects resolve authority only by the listed storage identity.
- Wrong aspect, low resolution, over-length, QA-failed, duplicate, and unuploaded outputs fail.
- A failed business gate writes a terminal failure to the durable run and operator live status.

### Stage F — final QA and repair semantics

- [x] Treat every final QA `FAIL` as approval-blocking across sports.
- [x] Fail closed with `QA_UNAVAILABLE` when real model QA is unavailable.
- [x] Require explicit final QA evidence for each local Part path.
- [x] Record QA state per canonical Part and invocation token.
- [x] Consume final QA evidence atomically without a process-global clear.
- [x] Keep surfing soft findings from deleting complete waves.
- [x] Preserve repair actions for premature cuts, crop/tracking, and slow motion before rejection.
- [x] Re-grade repaired output before it can become publishable.
- [x] Do not classify other visible/active people as a QA defect when the featured athlete remains clear.

### Stage G — cross-sport eval matrix

- [x] Surfing: one athlete, many waves, split only between complete waves.
- [x] Surfing: another surfer on the same wave is allowed while the target remains centered and stable.
- [x] Surfing: uncertain same-wave identity is blocked or review-required.
- [x] Surfing: visually similar labels remain separate when canonical IDs differ.
- [x] Football: group play with active defenders/teammates is allowed when the scorer remains central.
- [x] Football: attribution instructions assign goals/tackles to the successful actor.
- [x] Football: one valid action is sufficient for a primary reel.
- [x] Skateboarding: one complete trick is sufficient for a primary reel.
- [x] Identity uncertainty: split or review-required; never guess.
- [x] Silent technical cases: valid silence, unexpected audio, unknown audio state, over 90 seconds, wrong aspect, low resolution, duplicate output, missing upload, final QA failure, missing identity lineage, and stale-success status.

Evaluation policy:

- Deterministic graders decide product-contract failures.
- Model QA grades hook, pacing, clarity, payoff, and loopability after deterministic validation.
- Fixtures define expected athlete count, featured-athlete ownership, allowed surrounding participants, publishable count, rejection behavior, silent state, and terminal run state.

Evidence:

- `scripts/test_single_athlete_selection_policy_contract.py`
- `scripts/test_cross_sport_publishable_eval_matrix.py`
- `scripts/test_silent_output_policy_contract.py`
- `scripts/test_publishable_reel_business_contract.py`
- existing identity, primary-actor, multi-person, QA, surf-ride, and duplicate workflows

### Stage H — final CI, review, production experiment, and closure

Required evidence remains open:

- [x] Confirm all workflows are green on the revised centered-athlete/silent-output implementation head.
- [x] Resolve new review findings and record fallback self-review when automated review is unavailable.
- [ ] Merge only after explicit user approval.
- [ ] Run the same source footage used in run `29516256449` for direct comparison.
- [ ] Inspect `publishable_reel_manifest.json`, athlete coverage, candidate ledger, selection audit, draft trace, QA trace, status row, and final videos.
- [ ] Verify every eligible athlete has a primary publishable reel.
- [ ] Verify every usable surf wave appears exactly once or has explicit hard-reject evidence.
- [ ] Verify a wave remains when another surfer enters it but the target surfer stays central.
- [ ] Verify football group plays remain when the featured athlete is clearly attributable.
- [ ] Verify no `_music.mp4` or other audio-bearing draft appears in REVIEW.
- [ ] Verify every final Part proves `has_audio:false`.
- [ ] Verify every Part is at most 90 seconds and no complete action is split.
- [ ] Verify each file can be uploaded directly and accepts platform-native audio after download.
- [ ] Deliberately exercise one business-gate failure and confirm GitHub, the durable run row, and operator live status all show failure.
- [ ] Record false positives, false negatives, identity splits, repair attempts, and status inconsistencies in this audit.

Closure rule:

This audit remains open until deterministic contracts, final-head CI/review, and real visual production evidence pass. Green CI alone does not close the footage-level product gap.

### Contract/CI validation record — 2026-07-19

The last code-changing head in the review pass was `5692368664bfdcea1ca8e32c6618e9f023e8dec3`.

- All 20 triggered GitHub Actions workflows passed.
- Performance Reel Contract run `29695393549` passed all 24 steps.
- Operator Smoke Check run `29695393614` passed all 57 steps.
- Mobile Check run `29695393547` passed.
- Vercel and CodeRabbit commit statuses passed.
- All PR review threads were resolved.
- Fallback self-review found and fixed two gaps that the earlier green harness did not prove:
  1. the runtime-integrity install chain still replaced invocation-scoped QA functions with an older process-global implementation;
  2. R2 returned a signed URL after upload while the operator listed the canonical `review/` object key, forcing unsafe filename fallback.
- New regressions prove a single QA-scope owner, matching-label invocation isolation, canonical R2 identity, storage-object-only authority lookup, and repeated filename safety.
- No merge or real production run was performed. Validation level remains **Contract/CI only — pending real-run validation**.

## 5. Required artifacts

Implemented repository artifacts:

- `README.md`
- `docs/audit/primary-actor-continuity-policy.md`
- `pipeline/performance_reel_policy.py`
- `pipeline/publishable_reel_policy.py`
- `pipeline/publishable_pending_scope.py`
- `pipeline/publishable_qa_evidence.py`
- `pipeline/publishable_runtime_integrity.py`
- `pipeline/silent_output_policy.py`
- `pipeline/primary_actor_policy.py`
- `pipeline/single_athlete_selection_policy.py`
- `integrations/drive.py`
- `integrations/r2_storage.py`
- `web-api/src/lib/draft-publishability.ts`
- `supabase/migrations/20260717_draft_publishability_authority.sql`
- `scripts/check_publishable_reel_manifest.py`
- `scripts/record_publishable_business_gate_status.py`
- `scripts/run_pipeline_with_diagnostics.sh`
- `scripts/test_performance_reel_policy_contract.py`
- `scripts/test_single_athlete_selection_policy_contract.py`
- `scripts/test_silent_output_policy_contract.py`
- `scripts/test_publishable_reel_business_contract.py`
- `scripts/test_publishable_reel_concurrency_contract.py`
- `scripts/test_publishable_qa_evidence_contract.py`
- `scripts/test_publishable_runtime_integrity_contract.py`
- `scripts/test_publishable_identity_lineage_contract.py`
- `scripts/test_publishable_gate_status_contract.py`
- `scripts/test_cross_sport_publishable_eval_matrix.py`
- `scripts/test_review_finding_hardening_contract.py`
- `scripts/test_storage_contract.py`
- `.github/workflows/performance-reel-contract.yml`

Production-run artifacts:

- `publishable_reel_manifest.json`
- `publishable_reel_gate_result.json`
- `athlete_coverage_report.json`
- candidate ledger, selection audit, draft trace, QA trace, durable run status, operator live status, and perception sidecars

## 6. Current status

- Product vision and terminology: updated for one centered athlete with other people allowed.
- Football group-play policy: implemented with deterministic positive and negative fixtures.
- Same-wave surfing policy: implemented with deterministic positive and negative fixtures.
- Silent video-only output policy: implemented and contract/CI validated.
- Music selection/mixing in production execution: disabled by runtime policy.
- Audio-bearing and unknown-audio output gates: implemented.
- Surfing all-waves policy: implemented; real-run validation pending.
- Cross-sport athlete obligation: implemented and covered by deterministic evals.
- Upload-confirmed per-athlete manifest: implemented.
- Canonical identity-lineage reconciliation: implemented and regression-tested.
- Invocation-scoped QA evidence: implemented with one runtime owner and matching-label isolation tests.
- Immutable storage-object publishability authority: implemented for Drive and R2; filename fallback removed.
- Athlete-coverage reconciliation and production business gate: implemented.
- Concurrent manifest integrity: implemented and regression-tested.
- Final QA fail-closed behavior: implemented.
- GitHub/Supabase/operator terminal-status alignment: implemented and regression-tested.
- Final CI/review on the revised implementation head: complete.
- Merge, migration application, real footage validation, and business closure: pending explicit approval and production-run evidence.
