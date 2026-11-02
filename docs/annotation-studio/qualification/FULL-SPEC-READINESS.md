# FULL_SPEC_GO readiness — decision record

**Decision (2026-11-02): `NO-GO`.** The normative corpus (spec §§1–22, system design, guidelines v1, design-review addendum v1, V2 contract) contains mandatory requirements that are **not implemented**. Nothing in this branch changes an original requirement to make partial work look complete.

## Not implemented (mandatory for FULL_SPEC)

| Addendum / spec | Requirement | Why it is larger than a patch |
|---|---|---|
| Addendum §2.1–2.3 | `AnnotationSet`, `AnnotationAssignment`, set-scoped identities: independent annotation streams | Drafts and revisions are keyed by `source_id` only. Supporting independent streams changes the draft/revision keys, the API and the UI, and needs a migration that keeps every existing draft and revision readable. |
| Addendum §2, system design | Review / adjudication between streams | Depends on annotation sets. |
| Addendum §4 | `PhysicalActionEntity` / `ActionOccurrence`: the same physical action across videos | New entities, a linking UI, and evaluator support for cross-source matching. |
| Addendum §6 | `PersonLineageRelation`: revisioned identity merge/split | New lineage tables; evaluation must apply a frozen identity mapping. |
| Addendum §9 | Jaccard multi-label agreement metric | Only meaningful between independent streams (§2). |
| Spec §18 / §20.1 | Sport suggestion with confirmation, `source_sports`, sport-stratified datasets | Sport-separated **evaluation** works; suggestion and stratified datasets do not exist. |

## Implemented but not fully traced to the addendum

- Deterministic matching (§8): the evaluator is deterministic and digest-reproducible. Its ranking and tie-break rules, and the "inconclusive on missing config" behaviour, have not been checked line by line against §8.
- Evaluation identity / idempotency (§10): reruns with identical inputs give an identical digest (`e2e/workflow` #10). The rest of §10 is untraced.
- Raw-only boundary adjustment (§7): not traced.

## Not tested

- Real output-quality comparison (source vs proxy vs final reel), spec §21.5. Needs an existing real reel. The pipeline was not run.
- Accessibility audit (axe/contrast) and an operator usability walkthrough.

## Recommended order (each is its own PR, additive migrations only)

1. Annotation sets + assignments (migration: every existing draft becomes the default set), then adjudication and Jaccard agreement.
2. Person lineage (merge/split) with a frozen mapping in evaluation.
3. Physical-action lineage across sources.
4. Sport suggestion + stratified datasets.
5. Real reel-quality comparison once a reel exists and its use is approved.

`CATALOG_GO` (single-operator cataloging) does not depend on these. They block only the claim that the whole specification is implemented.
