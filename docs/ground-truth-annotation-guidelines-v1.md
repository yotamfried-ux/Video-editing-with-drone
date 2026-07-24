# SportReel Ground Truth Annotation Guidelines — Version 1

Date: 2026-07-24  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Status: **future annotation instruction set — design and calibration only; no feature implementation**  
Parent design: `docs/ground-truth-annotation-system-design.md`  
Audit tracking: `docs/app-pipeline-audit.md` → `GAP-027`

## 1. Purpose

This document defines how a human annotator must make SportReel ground-truth decisions consistently.

The architecture document defines what the future system stores and how it remains blind. This document defines the observable decision rules used to create that truth.

The goals are:

- make one operator's decisions reproducible months later;
- let a second independent annotator apply the same rules;
- keep uncertainty visible instead of converting it into a guess;
- preserve a versioned explanation for identity, usability, primary-athlete, and event decisions;
- make disagreements measurable before a dataset version is frozen.

This instruction version is provisional until a pilot calibration set is independently annotated and adjudicated. A material rule change creates a new instruction version and, when it affects accepted labels, a successor dataset version.

## 2. Governing principles

1. **Annotate only what is observable in the raw video.** Do not use filenames, upload order, pipeline clusters, track IDs, generated titles, drafts, scores, QA results, notes, or other predictions.
2. **Do not infer identity from a single weak clue.** Similar clothing, board color, body shape, or location alone is not enough.
3. **Continuity is stronger than appearance.** Continuous visible motion through time can establish that a back-facing or briefly occluded athlete is the same person without requiring a face.
4. **No face requirement and no biometrics.** A visible face may be ordinary visual context, but the annotator does not enroll faces, create templates, or match accounts.
5. **Uncertainty is valid data.** Use `Unknown`, `uncertain`, or `Needs Review` rather than choosing the most likely answer.
6. **Primary athlete means action ownership.** It does not mean the largest, closest, or only visible person.
7. **Usability and quality are different.** A modest but complete readable action can be usable even if it is not exciting.
8. **Complete actions take priority over highlight value.** Boundaries capture the action from meaningful beginning through observable outcome.
9. **One physical action is annotated once.** Repeated or overlapping source copies must be linked as duplicate-source evidence rather than counted as separate actions.
10. **Ground truth never becomes same-run guidance.** These labels remain unavailable to the evaluated pipeline until it has finished and frozen its outputs.

## 3. Required annotation order

For each raw video, use this order:

1. Start playback from the beginning or the exact saved resume point.
2. Mark visible people only as needed to make the current decision.
3. Identify the athlete who owns the meaningful action.
4. Mark action start, key moments, and action end during the first watch where possible.
5. Assign usability and structured reason codes.
6. Assign identity and primary athlete.
7. Assign confidence.
8. Choose `Complete` only when all required decisions are supported.
9. Choose `Needs Review` when a material decision remains uncertain.

Do not replay merely to seek a more confident guess. Replay is allowed when required to resolve a precise boundary, recover from interruption, or complete a review task.

## 4. Identity annotation

### 4.1 Identity question

The identity task asks:

> Does this visible athlete represent the same real person as a previously created anonymous project identity?

The answer is project-scoped and uses codes such as `SURFER-001`. It does not identify a real-world name or account.

### 4.2 Strong identity evidence

Evidence is strongest when multiple independent observations agree, for example:

- uninterrupted temporal continuity through the clip;
- reappearance after a short occlusion with a uniquely traceable trajectory;
- stable combination of wetsuit pattern, board, equipment, body proportions, stance, and movement;
- multiple clear views from different moments in the raw footage;
- same athlete entering, performing, and exiting one continuous action.

No single item in this list is automatically decisive. The decision should rely on the total observable evidence.

### 4.3 Weak evidence that cannot establish identity alone

Do not merge people based only on:

- general wetsuit color;
- board color;
- apparent gender or age;
- body size;
- camera position;
- sequence in the upload batch;
- filename or folder;
- the fact that only one known athlete is expected;
- a pipeline description, cluster, title, or track identifier.

### 4.4 Back-facing, distant, or face-hidden athletes

A hidden face does not force `Unknown` when identity remains observable through continuity and several non-biometric cues.

Use an existing person when:

- the athlete is continuously visible from a previously clear observation; or
- a brief obstruction occurs and the same trajectory, equipment, appearance combination, and timing make the continuation unambiguous.

Use `Unknown` or `Needs Review` when:

- the appearance begins after an unobserved gap;
- two plausible athletes could emerge from the obstruction;
- only one generic cue is visible;
- distance, spray, blur, darkness, or framing removes the evidence needed to distinguish people.

### 4.5 Two very similar athletes

Start from separation, not merging.

- Create or retain separate anonymous identities unless affirmative evidence supports sameness.
- Compare the full evidence sequence, not one frame.
- Treat a different board or clothing detail as useful only if it is clearly visible and stable.
- If evidence supports neither same nor different with adequate confidence, use `Unknown` or `Needs Review`.
- Never choose the existing identity merely to avoid creating a new person.

### 4.6 Continuous handoff and occlusion

When two people cross or overlap:

- follow entry trajectory, motion direction, equipment, and exit trajectory;
- do not assume tracks remain attached through the crossing;
- if the human cannot determine who exits as whom, split the certainty at the ambiguous interval and route the item to review;
- do not repair ambiguity using a pipeline track ID.

### 4.7 New person versus Unknown

Choose `New person` when the footage gives enough evidence to establish a distinct reusable identity but no existing identity matches.

Choose `Unknown` when the current appearance cannot support a stable reusable identity.

An `Unknown` observation may later be resolved by a new reviewed revision; it must not be silently reassigned.

### 4.8 Identity confidence

- `certain`: the same/different decision is supported by clear continuity or several strong consistent cues with no plausible alternative.
- `fairly_certain`: evidence favors one decision and no strong contradiction exists, but one important cue is weak or missing.
- `uncertain`: more than one plausible identity remains, or the evidence is too weak to create a stable person mapping.

An uncertain identity that affects primary-athlete attribution, action ownership, cross-video grouping, false merge, or false split must enter `Needs Review`.

## 5. Primary-athlete annotation

The primary athlete is the person who owns the meaningful sports action in the labeled event.

Do not select a person merely because that person is:

- closest to the camera;
- largest in the frame;
- centered for the longest time;
- the first person visible;
- the only person already assigned an anonymous identity.

### 5.1 Surfing

For a wave event, the primary athlete is the surfer performing the ride or attempted meaningful maneuver being annotated.

Another surfer, paddler, swimmer, or bystander may remain visible without becoming primary.

### 5.2 Team sports

For a play, select the athlete performing the meaningful action represented by the event, such as the pass, shot, save, tackle, dribble, or reception. Other players are expected context.

### 5.3 Ambiguous ownership

Use `uncertain_primary` and `Needs Review` when:

- the action changes ownership and the intended event cannot be separated cleanly;
- the camera loses the actor during the decisive moment;
- two people plausibly perform the same marked action;
- identity uncertainty prevents reliable ownership.

Use `no_primary_action` only when the clip contains no meaningful action with an attributable actor.

## 6. Usability annotation

### 6.1 `usable`

Use `usable` when the raw video contains at least one complete, readable action that can contribute to a personal reel while keeping the primary athlete and action ownership understandable.

A usable action does not need to be spectacular. It may include other people and may require an evidence-backed edit repair, provided the core action remains complete and attributable.

### 6.2 `partially_usable`

Use `partially_usable` when a bounded portion is useful but the complete item contains a material limitation, for example:

- only part of the action is visible;
- one event is usable and another is not;
- the opening or outcome is missing but a meaningful segment remains;
- a short occlusion or camera problem affects only part of the event;
- the clip requires review to define the valid temporal window.

The usable and unusable portions must be explained with event boundaries or reason codes.

### 6.3 `not_usable`

Use `not_usable` when no complete, readable, attributable action can support evaluation or a publishable reel. Examples include:

- no meaningful action;
- source corruption;
- the athlete is unreadable throughout;
- the action is entirely outside the captured interval;
- severe camera/focus failure prevents interpretation;
- the only apparent action is an exact duplicate of a physical action already represented and the item adds no new evidence.

Low excitement alone is not a not-usable reason.

### 6.4 `uncertain`

Use `uncertain` when usability depends on an unresolved identity, action-boundary, duplicate-source, or visibility decision. Route it to `Needs Review` rather than forcing usable/not-usable.

### 6.5 Required reason discipline

- Use structured reason codes before optional text.
- Select every material reason, not every minor imperfection.
- Do not use `other_needs_review` when a specific reason applies.
- Notes explain unusual evidence; they do not replace structured fields.

## 7. Surfing event boundaries

These definitions are instruction-versioned and must be calibrated on pilot examples.

### 7.1 Wave-ride start

Mark the earliest moment at which the surfer commits to the wave and the ride becomes meaningfully attributable.

Normally this is the committed takeoff transition, not:

- unrelated paddling far before commitment;
- waiting for the wave;
- a camera lead-in that contains no action;
- a later highlight maneuver that omits the takeoff and setup.

When the source begins after commitment, mark the first observable ride frame and add `partial_window_only` or the applicable partial reason.

### 7.2 Wave-ride end

Mark the first moment at which the outcome of the ride is clear and the meaningful action has ended, including:

- clean exit from the wave;
- fall or loss of the board;
- loss of rideable wave energy;
- the surfer leaving the observable action area;
- camera loss that prevents further reliable observation.

Do not cut at the visual peak if recovery, landing, fall, or exit is needed to understand the outcome.

When the source ends before the outcome, use a partial/incomplete reason rather than inventing an end.

### 7.3 Important moments

Mark a key moment only when it is part of the event's meaning, such as:

- committed takeoff;
- decisive turn or cutback;
- aerial or other high-impact maneuver;
- landing, recovery, or fall outcome;
- high-five or intentional social interaction;
- another sport-specific decisive action defined by the taxonomy.

Do not mark ordinary camera movement, generic proximity, or a moment merely because it looks dramatic without sports meaning.

### 7.4 Multiple events

- Separate physically distinct waves or actions.
- Do not split one continuous wave into multiple events merely because it contains several maneuvers.
- Key moments belong inside the containing action event.
- If one raw source repeats the same physical action, preserve duplicate lineage and count it once in the ground-truth action inventory.

### 7.5 Boundary uncertainty

When the event is clear but an exact frame is not, place the best observable boundary and record confidence.

When the ambiguity changes whether the action is complete, usable, or attributable, route the item to `Needs Review`.

## 8. Other sports

Before another sport is included in a frozen dataset, it requires a versioned sport-specific appendix defining:

- meaningful action types;
- action ownership;
- start and end rules;
- important moments;
- usable versus incomplete examples;
- expected multi-person context;
- hard ambiguity cases.

Do not apply surfing-specific wave rules to football, basketball, skating, or another sport by analogy without an approved appendix.

## 9. Needs Review rules

Use `Needs Review` whenever a material unresolved decision could change:

- person identity or same-person grouping;
- primary-athlete ownership;
- usable/not-usable status;
- whether an action is complete;
- whether two source appearances are the same physical action;
- event start/end enough to affect coverage or early-cut measurement;
- dataset inclusion or exclusion.

A review task must preserve:

- the partial annotation;
- structured uncertainty reason;
- exact source and playback position;
- instruction version;
- current revision;
- optional concise evidence note.

Review is adjudication, not an opportunity to see pipeline predictions. The reviewer remains blind to the evaluated run.

## 10. Completed-item corrections

When a completed decision is later found to be wrong:

1. Open the item explicitly from `Completed`.
2. Create a new revision; do not overwrite the accepted revision.
3. Record the corrected structured fields and the correction reason.
4. Preserve identity merge/split lineage when applicable.
5. If a frozen dataset references the old revision, create a successor dataset version before using the correction in evaluation.

## 11. Instruction examples and calibration set

Before the first production-quality freeze, the project must include a versioned instruction example pack containing raw-only examples of:

- clear same person;
- clear different people with similar appearance;
- back-facing but continuous identity;
- unresolved identity after occlusion;
- usable modest action;
- partially usable action;
- unusable source;
- complete wave start/end;
- source ending before outcome;
- multiple people with a clear primary athlete;
- ambiguous primary athlete;
- duplicate physical action across source files;
- important versus non-important moments.

Examples must not reveal pipeline predictions or evaluation results. The pack records the expected decision and a short rationale.

## 12. Independent annotation and agreement protocol

### 12.1 Purpose

Agreement measurement estimates whether the instruction set produces repeatable human truth. It is not a competition between annotators and does not automatically declare either annotation correct.

AWS Ground Truth models multiple worker annotations plus consolidation, while Azure consensus labeling routes unresolved disagreement to `Needs Review`. SportReel adopts independent annotation, explicit disagreement reports, and human adjudication rather than silently applying majority vote.

### 12.2 Blind independent sample

Before freezing the pilot dataset:

- select a QA sample using a documented rule fixed before agreement results are seen;
- include a random component and predefined difficult strata such as occlusion, distance, similar athletes, multiple people, partial actions, and duplicate-source cases;
- ensure the second annotator does not see the first annotator's labels, notes, person mappings, or pipeline predictions;
- use the same raw objects, taxonomy version, instruction version, and UI constraints;
- preserve both annotation sets independently.

For a single-operator phase, perform delayed blind re-annotation after a configured washout period and measure intra-annotator agreement. This does not replace future independent inter-annotator validation.

### 12.3 Agreement metrics

Report agreement by decision type rather than one combined score.

#### Categorical decisions

For usability, confidence, review routing, and primary-athlete/no-primary states, report:

- observed percent agreement;
- confusion matrix;
- Cohen's kappa for two annotators;
- weighted Cohen's kappa for ordered categories where appropriate;
- per-class disagreement counts.

Cohen's kappa adjusts observed agreement for agreement expected by chance. Do not report kappa alone when a category is rare or the metric is undefined.

#### Identity grouping

Anonymous codes are arbitrary, so direct code equality is invalid across annotators. Compare the partitions of appearances using:

- pairwise same-person/different-person precision, recall, and F1;
- false-merge and false-split disagreement counts;
- Rand Index and Adjusted Rand Index;
- agreement on `Unknown` versus stable identity;
- adjudicated examples for every material identity disagreement.

#### Temporal events

For matched events, report:

- event-type agreement;
- temporal intersection-over-union;
- absolute start-boundary difference;
- absolute end-boundary difference;
- key-moment matching within the versioned tolerance;
- event count disagreement;
- unmatched-event false positive/false negative counts.

#### Usability reasons and multi-label fields

Report per-reason agreement and a set-based similarity measure. Do not treat two annotations as fully agreeing when both choose `not_usable` but cite materially different observable causes.

### 12.4 Threshold policy

There is no universal official agreement threshold adopted for all SportReel labels.

Before measuring the pilot sample, the project owner must approve versioned acceptance thresholds for each metric family. Thresholds must account for:

- task difficulty;
- category prevalence;
- sample size;
- boundary tolerance;
- product risk of false merge, false split, missed athlete, and missed usable action.

Thresholds cannot be lowered after viewing results merely to permit a freeze.

Regardless of aggregate agreement, the following disagreements are blocking until adjudicated:

- false merge of two real people;
- false split that changes athlete coverage;
- disagreement about the primary athlete;
- disagreement that changes usable versus not usable;
- disagreement that changes whether a complete usable wave/action exists;
- duplicate-action disagreement that changes exactly-once coverage.

### 12.5 Adjudication

When agreement is below the approved threshold or a blocking disagreement exists:

1. keep both original annotations immutable;
2. create an adjudication task without pipeline predictions;
3. identify whether the cause is annotator error, unclear instruction, taxonomy gap, poor source, or genuinely ambiguous evidence;
4. create an accepted adjudication revision;
5. update instructions/taxonomy only through a new version;
6. re-annotate an affected sample when a rule changes;
7. block dataset freeze until required revalidation passes.

Consensus or adjudication output must never erase the contributing annotations.

### 12.6 Agreement report

Every freeze candidate stores an agreement report containing:

- project and dataset candidate IDs;
- source manifest hash;
- taxonomy and instruction versions;
- annotator identifiers or pseudonymous reviewer IDs;
- sample-selection rule and strata;
- sample sizes and denominators;
- all metrics by field and stratum;
- blocking disagreements;
- adjudication outcomes;
- instruction changes;
- final pass/fail/inconclusive decision.

An insufficient or unrepresentative sample must be reported as `inconclusive`, not as high agreement.

## 13. Freeze checklist for annotation quality

A dataset version cannot freeze until:

- [ ] the exact instruction version is recorded;
- [ ] the taxonomy version is recorded;
- [ ] every included item has an accepted revision;
- [ ] all material uncertainty is resolved or explicitly excluded;
- [ ] the review queue is empty for included items;
- [ ] identity merge/split decisions are resolved;
- [ ] event boundaries are valid and within source duration;
- [ ] the instruction example pack exists;
- [ ] the independent or delayed-blind QA sample was completed;
- [ ] agreement metrics and denominators were generated;
- [ ] versioned thresholds were approved before results were inspected;
- [ ] every blocking disagreement was adjudicated;
- [ ] any instruction change triggered the required re-annotation;
- [ ] the final agreement report is `pass`, not `inconclusive`;
- [ ] the frozen manifest references the exact accepted and adjudicated revision IDs.

## 14. Change control

A new instruction version is required when changing:

- same-person evidence rules;
- `Unknown`/new-person behavior;
- usability definitions;
- primary-athlete ownership rules;
- event start/end semantics;
- key-moment taxonomy;
- duplicate-action rules;
- confidence meanings;
- review-routing rules;
- agreement metrics, tolerances, or thresholds.

Editorial wording that does not alter meaning may be clarified in place before the first freeze, but every frozen dataset must retain the exact rendered instruction content used by its annotators.

## 15. Official basis

This guideline operationalizes patterns from the official sources already registered in the parent design, especially:

- AWS SageMaker Ground Truth — worker instructions, save/resume, verification/adjustment, multiple-worker annotation, consolidation, and output confidence;
- AWS Augmented AI — concise task instructions, full edge-case instructions, and human-review workflows;
- Azure Machine Learning Data Labeling — project instructions, consensus labeling, `Needs Review`, and owner review when consensus fails;
- Google Vertex AI — versioned instruction resources, annotation schemas, datasets, and dataset versions;
- scikit-learn official metrics documentation — Cohen's kappa, Rand Index, and Adjusted Rand Index definitions used for reproducible agreement reporting.

Primary references:

- https://docs.aws.amazon.com/sagemaker/latest/dg/sms-creating-instruction-pages.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-creating-good-instructions-guide.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/sms-video-worker-instructions.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/sms-annotation-consolidation.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/consolidation-lambda.html
- https://docs.aws.amazon.com/sagemaker/latest/dg/sms-verification-data.html
- https://learn.microsoft.com/azure/machine-learning/how-to-create-image-labeling-projects
- https://learn.microsoft.com/azure/machine-learning/how-to-create-text-labeling-projects
- https://learn.microsoft.com/azure/machine-learning/how-to-manage-labeling-projects
- https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html
- https://scikit-learn.org/stable/modules/generated/sklearn.metrics.rand_score.html
- https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html
