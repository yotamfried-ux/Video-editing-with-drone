# Personal publishable reel completion plan

Date: 2026-07-17  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Active PR: `#182`  
Business source of truth: `README.md` → **Product vision — source of truth**

## 1. Business objective

For every distinct athlete with at least one complete, visible, usable action, the pipeline must produce a personal reel that can be uploaded directly to social media so the athlete can promote themself.

The run is not successful merely because GitHub Actions, rendering, upload, or an LLM call completed. It is successful only when the following chain is proven:

```text
usable athlete detected
→ identity is isolated and traceable
→ sport-specific usable actions are represented
→ one canonical social-ready output is selected per part
→ final QA passes
→ every eligible athlete has one primary publishable reel
  or an explicit hard-reject reason
```

## 2. Official documentation research

Only first-party documentation is used as design evidence.

### 2.1 Google Gemini — video understanding

Source: https://ai.google.dev/gemini-api/docs/video-understanding

Relevant official guidance:

- Gemini can extract events and refer to timestamps in video.
- Timestamp references use `MM:SS`.
- Default video processing samples visual content at approximately 1 FPS.
- Fast action may lose detail at that sampling rate; Google recommends custom sampling or slowing relevant clips when necessary.
- Google recommends one video per prompt for optimal results and the Files API for large or reusable video inputs.

Design consequences for SportReel:

- LLM event detection is not sufficient identity evidence for fast sports by itself.
- Timestamp output must be normalized and validated against real source duration.
- Fast-action and small-subject footage must be backed by perception/tracking evidence and deterministic post-validation.
- The analyzer prompt must request complete actions and explicit timestamps, but the application must verify them.

### 2.2 Google Gemini — structured outputs

Source: https://ai.google.dev/gemini-api/docs/structured-output

Relevant official guidance:

- Gemini supports outputs constrained by JSON Schema.
- Strong typing, enums, and clear field descriptions improve reliability.
- Syntactically valid JSON is not sufficient; applications must validate semantically incorrect values.
- Robust error handling is required even when a response conforms to the schema.

Design consequences for SportReel:

- Athlete/action output needs a stable application-owned schema.
- Required fields must include identity key, source, start/end, action type, score, and explicit rejection evidence where applicable.
- The runtime must validate uniqueness, timestamp ranges, complete actions, and sport-specific semantics after parsing.
- Invalid schema or invalid semantic values must not silently become publishable content.

### 2.3 Google Cloud Video Intelligence — person detection and object tracking

Sources:

- https://cloud.google.com/video-intelligence/docs/feature-person-detection
- https://cloud.google.com/video-intelligence/docs/feature-object-tracking

Relevant official guidance:

- Person detection returns temporal segments and bounding boxes for detected people.
- Object tracking represents each individual object instance separately and returns bounding boxes over time.
- Tracking differs from frame-level labels: individual instances require their own tracks.
- Very small objects may not be detected.

Design consequences for SportReel:

- “A person exists in the frame” is not equivalent to “this is the athlete performing the action.”
- Each publishable action must retain track/primary-actor evidence over its relevant time window.
- Multiple visible people are acceptable when the performing athlete remains clear and continuous.
- Low-size or uncertain tracks must be review-required or explicitly rejected; the pipeline must not guess identity.

### 2.4 OpenAI — Evals and graders

Sources:

- https://developers.openai.com/api/reference/resources/evals
- https://developers.openai.com/api/reference/resources/graders

Relevant official guidance:

- Evals define a data schema and explicit testing criteria.
- Multiple graders can be combined, including deterministic string/Python graders and model-based graders.
- Evaluation output should be reproducible against named test items and reference expectations.

Design consequences for SportReel:

- The product contract must be represented as deterministic graders wherever possible.
- Athlete coverage, identity lineage, audio, duration, part order, duplicates, and final QA status are deterministic gates.
- Visual/social quality remains a model-assisted grader, but it cannot override deterministic failures.
- Regression fixtures must include positive and negative examples, not only successful cases.

### 2.5 Anthropic — prompt clarity and evaluation tooling

Sources:

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- https://docs.anthropic.com/en/docs/test-and-evaluate/eval-tool

Relevant official guidance:

- Instructions should explicitly state the desired behavior and output.
- Context explaining why a rule matters improves instruction following.
- Examples must match the behavior the system is intended to encourage.
- Prompts should be tested across evaluation cases rather than judged from a single result.

Design consequences for SportReel:

- The analyzer prompt must state the business reason: each athlete needs a personal promotional output.
- “One usable action is enough” must be explicit so an athlete is not omitted because they have fewer than an arbitrary target number of highlights.
- Surfing-specific examples must not accidentally become the global contract for every sport.
- Cross-sport fixtures must verify the same athlete-level outcome with sport-specific action policies.

## 3. Product definitions

### Eligible athlete

A distinct athlete with at least one complete, visible, usable action after timestamp, identity, and readability validation.

### Publishable reel

A canonical output that:

- contains one athlete only;
- passed final QA;
- has audio;
- is vertical 9:16;
- uses supported H.264/AAC-compatible social-media encoding;
- has acceptable output resolution;
- is at most 90 seconds;
- contains complete actions rather than fragments;
- is independently understandable and uploadable.

### Primary reel and supplemental parts

- Part 1 is the athlete's primary reel.
- Parts 2+ are allowed only when complete usable actions cannot fit within the platform limit.
- Every part must independently satisfy the publishable-reel contract.
- A complete action is never split across parts.

### Hard reject

A no-output or action-rejection reason backed by evidence, such as:

- no complete action was established;
- athlete/action is not readable;
- identity cannot be isolated safely;
- duplicate physical action;
- source timestamp is invalid or lies outside the media;
- source content itself ends before a usable action can be represented.

Low score, weak opening order, or removable dead time are not hard rejects.

## 4. Complete implementation plan

Each stage includes its artifact, deterministic acceptance test, and production evidence requirement. A stage is not complete when only documentation or code exists.

### Stage A — lock the vision in the repository

- [x] Replace the generic README introduction with the business outcome.
- [x] Define eligible athlete, publishable reel, primary reel, supplemental part, and hard reject.
- [x] State non-negotiable cross-sport invariants.
- [x] Link this audit from README.

Acceptance:

- README contains the phrase “every distinct athlete with at least one complete, visible, usable action.”
- README states that QA failure is not publishable.
- README states that Review exposes one canonical social-ready output per part.

### Stage B — explicit cross-sport analyzer contract

Implementation:

- [ ] Add a global analyzer instruction that applies before sport-specific rules.
- [ ] Require every distinct athlete with at least one usable action to be returned.
- [ ] State that one usable action is sufficient; do not require 3–8 actions to create an athlete output.
- [ ] Keep surfing's stronger all-waves rule as a sport-specific override.
- [ ] Preserve the existing team-sport attribution rule: assign the meaningful action to the athlete who performed it.
- [ ] Add application validation for person IDs, event start/end, complete action duration, and duplicate person/action records.

Deterministic tests:

- One football player with one valid goal remains eligible.
- A second player with no successful action is not forced into a reel.
- Two athletes in the same source remain separate.
- One surfer with six waves retains all six; a failed takeoff is rejected with evidence.
- Invalid or reversed timestamps fail validation.

### Stage C — canonical publishable output selection

Implementation:

- [ ] Generate internal clean and music variants only as processing intermediates.
- [ ] Select exactly one canonical social-ready variant for each part.
- [ ] Prefer the audio/music variant; never upload the silent intermediate as a normal Review draft.
- [ ] Rename the selected variant to a stable canonical filename without implementation-specific `(music)` noise.
- [ ] If no audio-capable variant exists, mark the athlete outcome as blocked instead of uploading a silent “ready” draft.
- [ ] Preserve ordered Part metadata; Part 1 is primary, Parts 2+ are supplemental.

Deterministic tests:

- Clean + music input becomes one canonical file.
- Silent-only output produces no publishable file and records a blocking reason.
- Multiple parts produce exactly one canonical output per part.
- Internal variants do not appear as duplicate Review drafts.

### Stage D — athlete-level publishable manifest

Implementation:

- [ ] Create a run-scoped `publishable_reel_manifest.json`.
- [ ] Record one row per eligible athlete/identity cluster.
- [ ] Record sport, athlete label/key, action count, generated parts, final QA state, technical specs, primary output, supplemental outputs, and blocking reasons.
- [ ] Derive a stable run-local athlete key from identity label plus source/action lineage.
- [ ] Write the manifest atomically and include it in diagnostics.

Deterministic tests:

- Each eligible athlete appears exactly once.
- Exactly one primary output exists for a publishable athlete.
- Parts are ordered and unique.
- QA-blocked outputs are not counted as publishable.
- Technical failures are visible in blocking reasons.

### Stage E — production business gate

Implementation:

- [ ] Add a deterministic checker for the publishable manifest.
- [ ] Fail the workflow when any eligible athlete lacks a primary publishable reel and lacks an explicit hard-reject reason.
- [ ] Fail on duplicate athlete manifest entries, duplicate output names, missing audio, non-9:16 output, resolution below the configured floor, duration over 90 seconds, or final QA failure counted as publishable.
- [ ] Preserve diagnostics generation even when the business gate fails.
- [ ] Copy the manifest and checker result into the workflow artifact.

Deterministic tests:

- Complete two-athlete manifest passes.
- Missing athlete output fails.
- Silent output fails.
- QA-failed output fails.
- Duplicate primary output fails.
- No-input runs remain `no_input` and do not fail solely because no manifest exists.

### Stage F — final QA and repair semantics

Implementation:

- [ ] Treat every final QA `FAIL` as approval-blocking across sports.
- [ ] Record QA verdict per canonical part in the manifest.
- [ ] Keep surfing soft defects from deleting complete waves.
- [ ] Continue using repair actions for premature cut, crop, tracking, and slow motion before rejecting content.
- [ ] Ensure the re-edit task points to the canonical draft and retains source/action lineage.

Deterministic tests:

- Noncritical final FAIL is still blocked.
- Re-edit cannot silently convert a multi-action athlete into a single-action reel by deleting usable actions.
- A repaired output must be re-graded before it becomes publishable.

### Stage G — cross-sport eval matrix

Fixtures required before claiming general completion:

- [ ] Surfing: one athlete, many waves, split only between waves.
- [ ] Surfing: two athletes with visually similar equipment remain separate.
- [ ] Football: scorer receives the goal; conceding player does not receive it as a positive action.
- [ ] Football: a player with one valid action still receives a reel.
- [ ] Skateboarding: complete trick from setup through landing.
- [ ] Multi-person footage: background people are allowed when the primary actor is clear.
- [ ] Identity uncertainty: split or review-required; never mixed output.
- [ ] Technical negative cases: no audio, over 90 seconds, wrong aspect, duplicate output.

Evaluation policy:

- Deterministic graders decide contract failures.
- Model-based QA grades hook, pacing, clarity, payoff, and loopability only after deterministic gates pass.
- Every fixture includes expected athlete count, expected publishable count, expected action ownership, and expected rejection reasons.

### Stage H — production experiment and closure

Required real-run evidence:

- [ ] Merge only after all repository CI and review findings are green/resolved.
- [ ] Run the same source footage used in run `29516256449` for direct comparison.
- [ ] Inspect `publishable_reel_manifest.json`, athlete coverage report, candidate ledger, selection audit, draft trace, QA trace, and final videos.
- [ ] Verify every eligible athlete has a primary publishable reel.
- [ ] Verify every usable surf wave appears exactly once or has explicit hard-reject evidence.
- [ ] Verify no silent duplicate drafts appear in Review.
- [ ] Verify every part is at most 90 seconds and no action is split.
- [ ] Verify each final file can be uploaded directly without additional editing.
- [ ] Record observed false positives, false negatives, identity splits, and QA repair attempts in this audit.

Closure rule:

The audit remains open until both deterministic contracts and real visual evidence pass. Green CI alone does not close the footage-level product gap.

## 5. Required implementation artifacts

- `README.md`
- `pipeline/performance_reel_policy.py`
- `pipeline/publishable_reel_policy.py`
- `scripts/check_publishable_reel_manifest.py`
- `scripts/run_pipeline_with_diagnostics.sh`
- `scripts/test_performance_reel_policy_contract.py`
- `scripts/test_publishable_reel_business_contract.py`
- `.github/workflows/performance-reel-contract.yml`
- production artifact: `publishable_reel_manifest.json`

## 6. Current status

- Vision and definitions: complete.
- Official-source research: complete.
- Surfing all-waves policy: implemented in PR #182; real-run validation pending.
- Cross-sport athlete accountability: implementation pending in this plan.
- Canonical publishable output: implementation pending in this plan.
- Publishable manifest and production gate: implementation pending in this plan.
- Production validation: blocked until implementation is merged and a new run is explicitly started.
