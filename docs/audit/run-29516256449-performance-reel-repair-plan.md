# Run 29516256449 — performance reel coverage repair

## Production finding

Run `29516256449` succeeded technically but did not satisfy the product contract:

- 15 candidate surfing moments were recorded.
- Only 5 appeared in final drafts.
- 4 drafts were uploaded, while every final QA verdict was `FAIL`.
- Three drafts remained approvable because their failures were classified as non-blocking.
- Several multi-wave athlete timelines were reduced by QA retries to a single wave.
- Clean and music renders created duplicate or misleading Review outputs.
- The operator Review screen exposed seven manual taxonomy buttons, which looked like system findings and shifted pipeline diagnosis to the operator.

## Product contract

For surfing footage, the unit of coverage is a complete wave ride attributed to one featured surfer. The frame does not need to contain only that surfer.

1. Return every distinct readable wave for each surfer.
2. A score changes ordering and emphasis, not inclusion.
3. Keep a wave when another surfer enters, crosses, or rides the same wave, provided the target surfer remains the clear, continuous center and the selected action belongs to that surfer.
4. Reject a wave only with explicit hard evidence:
   - immediate failed takeoff / no ride established;
   - no visible readable surfing;
   - duplicate of the same physical wave;
   - target surfer lost or materially obscured;
   - identity/track switches to another surfer;
   - the selected action actually belongs to another athlete.
5. Pack whole waves into consecutive performance reels under the 90-second platform limit.
6. Split only between waves. Never truncate or silently discard a ride to satisfy packing.
7. Produce one canonical silent video per Part. Do not select music, mix audio, preserve source audio, or upload `_music.mp4` variants. The athlete adds platform-native audio after download.
8. A final QA `FAIL` is review-blocking even when no individual defect was labeled critical.
9. QA may repair a premature cut or slow motion, but may not delete a valid wave merely for low score, dead time, softness, weak opening order, or another surfer being present.
10. The Review screen uses free-text re-edit notes only; manual defect taxonomy buttons are removed.

## Implementation

- `pipeline/performance_reel_policy.py`
  - appends the all-waves and same-wave primary-surfer rules to the analyzer prompt;
  - replaces score-only surf filtering with explicit no-ride/identity rejection;
  - preserves low-score but readable surf events through runtime hardening;
  - packs all whole events into annotated Parts with an 89-second safety budget;
  - prevents soft QA defects from deleting surf rides;
  - converts every final QA failure into an approval block;
  - disables the unused structured-button feedback prompt injection.
- `pipeline/primary_actor_policy.py` and `pipeline/single_athlete_selection_policy.py`
  - define personal reels by one centered athlete rather than one visible person;
  - allow active teammates, opponents, and same-wave surfers while the target remains attributable;
  - block genuine identity switch, target loss, critical occlusion, or uncertain ownership.
- `pipeline/silent_output_policy.py`
  - disables music selection;
  - strips positional and keyword `music_path` values before compilation;
  - keeps the silent clean render and deletes legacy music variants;
  - rejects audio-bearing or unknown-audio-state output.
- `scripts/check_publishable_reel_manifest.py`
  - requires every publishable Part to prove `has_audio:false`;
  - fails audio-bearing output, missing identity/coverage, failed QA, invalid duration/aspect/resolution, duplicate ownership, or missing Review upload.
- `scripts/sitecustomize.py`, `pipeline/bootstrap.py`, and `scripts/run_tracked.py`
  - install the coverage, centered-athlete, and silent-output policies in production and manual entrypoints.
- `mobile/src/app/(operator)/review.tsx`
  - removes the seven feedback buttons;
  - uses clear `Performance reel` and QA status labels;
  - stacks actions vertically to avoid narrow-screen overflow.
- Deterministic tests
  - prove six waves survive exactly once and split into whole-wave Parts;
  - prove low-score readable waves remain while explicit failed takeoffs do not;
  - prove a clear target surfer remains eligible when another surfer rides the same wave;
  - prove uncertain same-wave identity remains blocked;
  - prove football group plays retain the featured athlete;
  - prove music generation is disabled and silent output is required;
  - prove soft QA defects cannot trigger wave deletion;
  - prove the button taxonomy is absent from Review.

## Acceptance

- [ ] Performance Reel Contract workflow passes on the revised centered-athlete/silent-output head.
- [ ] Operator Smoke Check passes with the new runtime and policy tests.
- [ ] Mobile type-check passes.
- [ ] Existing CI remains green.
- [ ] Automated review or documented fallback self-review has no unresolved findings.
- [ ] New production run proves all usable waves are represented exactly once.
- [ ] Operator verifies a wave is retained when another surfer enters it but the target surfer stays central.
- [ ] Operator verifies every generated Part is silent, at most 90 seconds, and no wave is cut between Parts.
- [ ] Review contains no `_music.mp4` or other audio-bearing duplicate.

A green PR does not close the footage-level gap. The final production and visual acceptance items require a new real run after explicit merge approval.
