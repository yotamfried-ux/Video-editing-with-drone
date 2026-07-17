# Personal publishable reel completion plan

Date: 2026-07-17  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Active PR: `#182`  
Business source of truth: `README.md` → **Product vision — source of truth**  
Audit state: **implementation complete; production experiment pending**

## 1. Business objective

For every distinct athlete with at least one complete, visible, usable action, the pipeline must produce a personal reel that can be uploaded directly to social media so the athlete can promote themself.

The run is not successful merely because GitHub Actions, rendering, upload, or an LLM call completed. It is successful only when this chain is proven:

```text
usable athlete detected
→ identity is isolated and traceable
→ sport-specific usable actions are represented
→ one canonical social-ready output is selected per part
→ the output is uploaded to REVIEW
→ final QA and deterministic technical gates pass
→ every eligible athlete has one primary publishable reel
  or an explicit evidence-backed no-output reason
```

## 2. Official documentation research

Only first-party documentation is used as design evidence.

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

- “A person is visible” does not prove they are the performing athlete.
- Publishable actions retain identity/track/primary-actor evidence.
- Background people are allowed when the primary actor remains clear and continuous.
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

- Coverage, identity ownership, upload confirmation, audio, duration, aspect, resolution, part order, duplicates, and final QA state are deterministic gates.
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
- The global athlete contract is separate from sport-specific rules such as all-waves surfing coverage.
- A cross-sport eval matrix tests football, skateboarding, surfing, identity ambiguity, background people, and technical failures.

## 3. Product definitions

### Eligible athlete

A distinct athlete with at least one complete, visible, usable action after timestamp, identity, primary-actor, and readability validation.

### Publishable reel

A canonical output that:

- contains one athlete only;
- was successfully uploaded to REVIEW;
- passed real final QA;
- has audio;
- is vertical 9:16;
- has acceptable resolution;
- is at most 90 seconds;
- contains complete actions rather than fragments;
- is independently understandable and uploadable.

### Primary reel and supplemental parts

- Part 1 is the athlete's primary reel.
- Parts 2+ are permitted only when complete usable actions cannot fit under the platform limit.
- Every part independently satisfies the publishable contract.
- A complete action is never split between parts.

### Hard reject

An evidence-backed reason that makes an action or athlete output genuinely unusable, including:

- no complete action was established;
- the athlete/action is not readable;
- identity cannot be isolated safely;
- duplicate physical action;
- invalid source timestamp;
- source content ends before a complete usable action can be represented.

Low score, weak opening order, or removable dead time are not hard rejects.

## 4. Implementation plan and evidence

A checked implementation item means code plus deterministic regression exists. It does not replace Stage H's real footage validation.

### Stage A — lock the vision in the repository

- [x] Replace the generic README introduction with the business outcome.
- [x] Define eligible athlete, publishable reel, primary reel, supplemental part, and hard reject.
- [x] State non-negotiable cross-sport invariants.
- [x] Link this audit from README.

Evidence:

- `README.md`
- `scripts/test_publishable_reel_business_contract.py`

### Stage B — explicit cross-sport analyzer contract

- [x] Add a global instruction that applies across sports.
- [x] Require every distinct athlete with at least one usable action to be returned.
- [x] State that one usable action is sufficient.
- [x] Preserve surfing's stronger all-waves override.
- [x] Preserve team-sport attribution to the athlete performing the meaningful play.
- [x] Validate person IDs, event arrays, numeric fields, score range, action type, and timestamp order after parsing.
- [x] Fail invalid semantic model output instead of publishing it.

Deterministic evidence:

- One football player with one valid goal receives a primary output.
- A person without a successful action is not forced through the existing empty-events path.
- Distinct athletes remain separate by canonical identity ID even when descriptions are similar.
- Six surf waves remain exactly once; failed takeoffs remain hard rejects.
- Invalid or reversed timestamps fail semantic validation.

Files:

- `pipeline/publishable_reel_policy.py`
- `pipeline/performance_reel_policy.py`
- `scripts/test_cross_sport_publishable_eval_matrix.py`
- `scripts/test_publishable_reel_business_contract.py`

### Stage C — canonical publishable output selection

- [x] Treat clean and music renders as processing variants.
- [x] Select exactly one canonical social-ready variant for each part.
- [x] Prefer the audio-capable music render.
- [x] Rename the selected render to the stable canonical path.
- [x] Delete the silent intermediate rather than upload it as another Review draft.
- [x] Block silent-only output with an explicit reason.
- [x] Preserve ordered Part metadata.

Deterministic evidence:

- Clean + music collapses to one canonical file.
- Silent-only output produces no publishable file.
- Multiple parts produce exactly one canonical output per part.
- Primary and supplemental ordering is preserved.

### Stage D — athlete-level publishable manifest

- [x] Create run-scoped `publishable_reel_manifest.json`.
- [x] Record one row per eligible athlete outcome.
- [x] Record sport, athlete key/IDs/label, action lineage, parts, QA, technical specs, upload state, primary output, supplemental outputs, and blocking reasons.
- [x] Derive a stable run-local key from canonical IDs, label, and source/action lineage.
- [x] Write the manifest atomically.
- [x] Protect parallel upload updates with an `RLock`.
- [x] Include the manifest in diagnostics.

Deterministic evidence:

- A rendered part is not publishable before a real REVIEW upload succeeds.
- Two parallel Part uploads both remain in the manifest.
- Duplicate canonical athlete ownership and duplicate output names fail.
- QA-blocked and technically invalid outputs are not counted as publishable.

Files:

- `pipeline/publishable_reel_policy.py`
- `scripts/test_publishable_reel_concurrency_contract.py`

### Stage E — production business gate

- [x] Add deterministic `check_publishable_reel_manifest.py`.
- [x] Fail when an eligible athlete lacks a primary publishable reel.
- [x] Reconcile the final manifest with `athlete_coverage_report.json`.
- [x] Fail when a selected upstream athlete is absent from the manifest.
- [x] Fail unresolved athlete coverage or accountability below 1.0.
- [x] Fail duplicate athlete ownership, duplicate output names, missing REVIEW upload, missing audio, wrong aspect, low resolution, duration over 90 seconds, or final QA failure.
- [x] Preserve diagnostics even when the business gate fails.
- [x] Make the business-gate result the final exit code after successful processing.
- [x] Preserve true `no_input` behavior when no candidate evidence exists.

Deterministic evidence:

- Valid two-athlete cross-sport manifest passes.
- Missing athlete output fails.
- Missing upstream athlete fails.
- Silent, over-length, wrong-aspect, low-resolution, QA-failed, duplicate, and unuploaded outputs fail.
- Empty no-input manifest passes.

Files:

- `scripts/check_publishable_reel_manifest.py`
- `scripts/run_pipeline_with_diagnostics.sh`
- `scripts/test_cross_sport_publishable_eval_matrix.py`
- `scripts/test_publishable_reel_business_contract.py`

### Stage F — final QA and repair semantics

- [x] Treat every final QA `FAIL` as approval-blocking across sports.
- [x] Fail closed with `QA_UNAVAILABLE` when real model QA is unavailable; remove the previous synthetic PASS behavior from the publishable path.
- [x] Record QA state per canonical part.
- [x] Keep surfing soft findings from deleting complete waves.
- [x] Preserve repair actions for premature cuts, crop/tracking, and slow motion before rejection.
- [x] Re-grade repaired output before it can become publishable.
- [x] Upload and source mapping use the canonical draft name consumed by the existing re-edit path.

Deterministic evidence:

- A noncritical final FAIL is still blocked.
- “QA skipped” becomes a critical explicit failure.
- Soft QA findings cannot reduce a valid all-waves reel by deletion.
- Existing QA re-edit contracts remain green.

### Stage G — cross-sport eval matrix

- [x] Surfing: one athlete, many waves, split only between complete waves.
- [x] Surfing: visually similar athlete labels remain separate when canonical IDs differ.
- [x] Football: attribution instructions assign goals/tackles to the successful actor.
- [x] Football: one valid action is sufficient for a primary reel.
- [x] Skateboarding: one complete trick is sufficient for a primary reel.
- [x] Multi-person footage: background people are allowed when the primary actor is clear.
- [x] Identity uncertainty: split or review-required; never mixed output.
- [x] Technical negative cases: no audio, over 90 seconds, wrong aspect, low resolution, duplicate output, missing upload, and final QA failure.

Evaluation policy:

- Deterministic graders decide product-contract failures.
- Model QA grades hook, pacing, clarity, payoff, and loopability after deterministic validation.
- Fixtures define expected athlete count, publishable count, action ownership, and rejection behavior.

Evidence:

- `scripts/test_cross_sport_publishable_eval_matrix.py`
- existing identity, primary-actor, multi-person, QA, surf-ride, and duplicate workflows

### Stage H — production experiment and closure

Required real-run evidence remains open:

- [ ] Merge only after the final head has green CI and no unresolved review findings.
- [ ] Run the same source footage used in run `29516256449` for direct comparison.
- [ ] Inspect `publishable_reel_manifest.json`, athlete coverage, candidate ledger, selection audit, draft trace, QA trace, and final videos.
- [ ] Verify every eligible athlete has a primary publishable reel.
- [ ] Verify every usable surf wave appears exactly once or has explicit hard-reject evidence.
- [ ] Verify no silent duplicate drafts appear in Review.
- [ ] Verify every part is at most 90 seconds and no action is split.
- [ ] Verify each final file can be uploaded directly without additional editing.
- [ ] Record false positives, false negatives, identity splits, and repair attempts in this audit.

Closure rule:

This audit remains open until deterministic contracts **and** real visual production evidence pass. Green CI alone does not close the footage-level product gap.

## 5. Required artifacts

Implemented repository artifacts:

- `README.md`
- `pipeline/performance_reel_policy.py`
- `pipeline/publishable_reel_policy.py`
- `scripts/check_publishable_reel_manifest.py`
- `scripts/run_pipeline_with_diagnostics.sh`
- `scripts/test_performance_reel_policy_contract.py`
- `scripts/test_publishable_reel_business_contract.py`
- `scripts/test_publishable_reel_concurrency_contract.py`
- `scripts/test_cross_sport_publishable_eval_matrix.py`
- `.github/workflows/performance-reel-contract.yml`

Production-run artifacts:

- `publishable_reel_manifest.json`
- `publishable_reel_gate_result.json`
- `athlete_coverage_report.json`
- candidate ledger, selection audit, draft trace, QA trace, and perception sidecars

## 6. Current status

- Product vision and terminology: complete.
- Official first-party research: complete.
- Surfing all-waves policy: implemented; real-run validation pending.
- Cross-sport athlete obligation: implemented and covered by deterministic evals.
- Canonical social-ready output selection: implemented.
- Upload-confirmed per-athlete manifest: implemented.
- Athlete-coverage reconciliation and production business gate: implemented.
- Concurrent manifest integrity: implemented and regression-tested.
- Final QA fail-closed behavior: implemented.
- Real footage validation and business closure: pending explicit merge and production-run approval.
