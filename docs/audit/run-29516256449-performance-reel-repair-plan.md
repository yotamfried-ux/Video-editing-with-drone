# Run 29516256449 — performance reel coverage repair

## Production finding

Run `29516256449` succeeded technically but did not satisfy the product contract:

- 15 candidate surfing moments were recorded.
- Only 5 appeared in final drafts.
- 4 drafts were uploaded, while every final QA verdict was `FAIL`.
- Three drafts remained approvable because their failures were classified as non-blocking.
- Several multi-wave athlete timelines were reduced by QA retries to a single wave.
- The operator Review screen exposed seven manual taxonomy buttons, which looked like system findings and shifted pipeline diagnosis to the operator.

## Product contract

For surfing footage, the unit of coverage is a complete wave ride for one surfer.

1. Return every distinct readable wave for each surfer.
2. A score changes ordering and emphasis, not inclusion.
3. Reject a wave only with explicit hard evidence:
   - immediate failed takeoff / no ride established;
   - no visible readable surfing;
   - duplicate of the same physical wave;
   - wrong athlete / identity mismatch.
4. Pack whole waves into consecutive performance reels under the 90-second platform limit.
5. Split only between waves. Never truncate or silently discard a ride to satisfy packing.
6. A final QA `FAIL` is review-blocking even when no individual defect was labeled critical.
7. QA may repair a premature cut or slow motion, but may not delete a valid wave merely for low score, dead time, softness, or weak opening order.
8. The Review screen uses free-text re-edit notes only; manual defect taxonomy buttons are removed.

## Implementation

- `pipeline/performance_reel_policy.py`
  - appends the surfing coverage override to the analyzer prompt;
  - replaces score-only surf filtering with explicit no-ride rejection;
  - preserves low-score but readable surf events through runtime hardening;
  - packs all whole events into annotated parts with an 89-second safety budget;
  - prevents soft QA defects from deleting surf rides;
  - converts every final QA failure into an approval block;
  - disables the unused structured-button feedback prompt injection.
- `scripts/sitecustomize.py` and `pipeline/bootstrap.py`
  - install the policy in production and manual entrypoints.
- `mobile/src/app/(operator)/review.tsx`
  - removes the seven feedback buttons;
  - uses clear `Performance reel` and QA status labels;
  - stacks actions vertically to avoid narrow-screen overflow.
- `scripts/test_performance_reel_policy_contract.py`
  - proves six waves survive exactly once and split into two whole-wave parts;
  - proves low-score readable waves remain while explicit failed takeoffs do not;
  - proves soft QA defects cannot trigger wave deletion;
  - proves the button taxonomy is absent from Review.

## Acceptance

- [ ] Performance Reel Contract workflow passes.
- [ ] Mobile type-check passes.
- [ ] Existing CI remains green.
- [ ] Automated review or documented fallback self-review has no unresolved findings.
- [ ] New production run proves all usable waves are represented exactly once.
- [ ] Operator verifies every generated part is at most 90 seconds and no wave is cut between parts.

A green PR does not close the footage-level gap. The final two acceptance items require a new real run and visual review.
