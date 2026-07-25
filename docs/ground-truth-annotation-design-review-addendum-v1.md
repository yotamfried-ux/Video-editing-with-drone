# SportReel Ground Truth Annotation Design — Normative Review Addendum v1

Date: 2026-07-25  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Status: **design-only normative clarification; no runtime, UI, API, database, workflow, or pipeline implementation**  
Parent design: `docs/ground-truth-annotation-system-design.md`  
Annotation instructions: `docs/ground-truth-annotation-guidelines-v1.md`  
Audit tracking: `docs/app-pipeline-audit.md` → `GAP-027`

## 1. Scope and precedence

This addendum closes the final documentation-review findings on PR #197. It is part of the GAP-027 design source set and is normative for future implementation.

Where this addendum conflicts with a field or rule in the parent design or Version 1 guidelines, this addendum controls. Before implementation Phase 2 begins, the design source set should be consolidated without changing the meaning recorded here.

Merging this document closes only the planning review. It does not implement or close GAP-027.

## 2. Independent annotation streams

A raw item may participate in multiple independent annotation streams. Item inventory state and annotator work state must therefore be separate.

### 2.1 `AnnotationSet`

Purpose: one isolated annotation stream over a project subset.

Required logical fields:

- `annotation_set_id`
- `project_id`
- `purpose`: `primary | delayed_blind_reannotation | independent_qa | adjudication`
- `taxonomy_version`
- `instruction_version`
- `assigned_annotator_id` or pseudonymous reviewer ID
- `status`: `draft | active | submitted | adjudicating | accepted | archived`
- `created_at`
- `submitted_at`

Rules:

- an annotator cannot read another set's revisions, notes, person mappings, cursor, or agreement results before submitting the independent set;
- the same `AnnotationItem` can belong to multiple annotation sets;
- primary, re-annotation, and independent-QA sets remain immutable after submission;
- adjudication is represented by a separate set and never overwrites contributing sets.

### 2.2 `AnnotationAssignment`

Purpose: annotation-set-scoped queue and resume state for one item.

Required logical fields:

- `annotation_assignment_id`
- `annotation_set_id`
- `item_id`
- `queue_status`: `unlabeled | in_progress | needs_review | completed | excluded`
- `current_revision_id`
- `assigned_operator_id`
- `playback_position_ms`
- `started_at`
- `completed_at`

Rules:

- `(annotation_set_id, item_id)` is unique;
- queue status, revision head, assignment, resume position, and undo state are scoped to the assignment, not stored as a single global state on `AnnotationItem`;
- the source item remains immutable inventory shared by all sets;
- a second annotator starts from an independent empty assignment and cannot reopen or replace the first annotator's revision head.

### 2.3 Annotation-set-scoped identities

Anonymous person codes and mappings are scoped to an annotation set while independent work is in progress.

- direct code equality across annotation sets is invalid;
- each set maintains its own `PersonEntity` namespace and appearance mappings;
- agreement compares partitions and same-person/different-person pairs;
- adjudication creates a separate accepted identity graph that references contributing identities without mutating them.

## 3. Event-scoped primary-athlete ownership

Primary-athlete truth is event-scoped.

- every usable `EventAnnotation` must reference one `primary_person_id`, `no_primary_action`, or `uncertain_primary`;
- one raw item may contain multiple events owned by different athletes;
- `PersonAppearance.is_primary` must be removed or treated only as an event-scoped relation, not a single item-wide assertion;
- an optional item-level primary may be derived only when every included meaningful event has the same accepted primary athlete;
- when accepted events have different primary athletes, the item-level primary is null or explicitly `multiple_event_owners`;
- athlete coverage and attribution metrics are computed from event ownership, not from a forced item-wide primary.

## 4. Cross-item physical-action lineage

A revision-local event ID is insufficient when the same physical action appears in multiple raw files. Future implementation requires explicit action lineage.

### 4.1 `PhysicalActionEntity`

Purpose: identify one real-world sports action independently of how many raw sources contain it.

Required logical fields:

- `physical_action_id`
- `project_id`
- `sport`
- `action_type`
- `primary_person_identity_id` in the accepted/adjudicated identity graph
- `lineage_state`: `provisional | accepted | split | merged | retired`
- `created_revision_id`
- `created_at`

### 4.2 `ActionOccurrence`

Purpose: connect one annotated event in one raw source to a physical action.

Required logical fields:

- `action_occurrence_id`
- `physical_action_id`
- `event_id`
- `item_id`
- `source_upload_id`
- `raw_storage_key`
- `start_ms`
- `end_ms`
- `occurrence_role`: `canonical_view | duplicate_view | supplementary_view | uncertain`
- `evidence_revision_id`

Rules:

- one event occurrence belongs to at most one accepted physical action;
- multiple occurrences may reference the same physical action when several raw files show the same wave or play;
- duplicate lineage identifies the exact events being grouped, not only a generic duplicate reason on a file;
- split/merge corrections are append-only and preserve previous groupings;
- the frozen dataset manifest contains every physical-action ID, its exact event occurrences, accepted lineage revisions, and content hashes;
- exactly-once coverage and duplicate-action metrics operate on `PhysicalActionEntity`, while source-level evidence operates on `ActionOccurrence`.

## 5. Exact canonical source binding

Prefix validation alone is not source identity.

For every annotation read or mutation:

1. the client sends an opaque server-issued `item_id`, not a trusted raw key;
2. the server resolves the canonical `source_upload_id` from the item;
3. the server resolves the authoritative `raw_storage_key`, batch ID, SHA-256, size, verification state, and supersession state from that canonical source row;
4. any submitted or cached key must equal the authoritative key exactly;
5. the source must still be verified, canonical, non-superseded, hash-matching, and size-matching;
6. `raw/<batch_id>/` prefix validation remains defense in depth only;
7. any mismatch fails closed before issuing a signed URL or accepting an annotation action.

The server must never accept an arbitrary same-batch object merely because its prefix is valid.

## 6. Revisioned person merge/split lineage

A single `superseded_by` pointer cannot represent a split into multiple successors. Replace it as the authoritative model with a revisioned relation.

### 6.1 `PersonLineageRelation`

Required logical fields:

- `person_lineage_relation_id`
- `annotation_set_id` or adjudication set ID
- `relation_type`: `merge | split | equivalent | retire`
- `from_person_id`
- `to_person_id`
- `contributing_revision_id`
- `reason_code`
- `created_by`
- `created_at`

Rules:

- a merge supports multiple predecessors and one or more accepted successors;
- a split supports one or more predecessors and multiple successors;
- all edges are revisioned and append-only;
- historical appearance mappings remain queryable at the dataset version that used them;
- the frozen identity graph is reconstructed from exact accepted lineage relation IDs;
- `superseded_by`, if retained as a convenience projection, is non-authoritative and cannot be the sole representation.

## 7. Raw-only boundary adjustment

The Version 1 usability guidance phrase `evidence-backed edit repair` means only a possible future edit inferred from observable raw footage. To remove ambiguity, the normative term is **raw-only boundary adjustment**.

A usable action may need a raw-only temporal boundary adjustment or later production edit, provided the human usability decision is based solely on the raw video and the complete action remains observable and attributable.

The annotator and adjudicator must not consult:

- drafts;
- pipeline outputs;
- generated edits;
- prediction manifests;
- QA results;
- model scores or suggestions.

Those artifacts may be compared only by the separate post-run evaluator after the pipeline is terminal.

## 8. Deterministic event-matching algorithm

Event metrics require one reproducible matching procedure. Every evaluation records a versioned `event_matching_config` whose values are approved before results are inspected.

### 8.1 Compatibility

A truth event and prediction event are eligible candidates only when:

- they reference the same canonical source item, or the same accepted physical-action lineage when cross-source evaluation is explicitly enabled;
- their event types are identical or compatible under a frozen versioned event-type mapping;
- their accepted primary-athlete identities match after applying the frozen identity mapping, unless the metric intentionally measures attribution disagreement;
- their temporal intersection-over-union meets the configured minimum candidate threshold.

### 8.2 One-to-one assignment

- matching is one-to-one: one truth event cannot match multiple predictions and one prediction cannot match multiple truth events;
- build all eligible candidate pairs;
- rank candidates by: highest temporal IoU, then smallest combined absolute start/end boundary error, then stable lexical order of truth event ID and prediction event ID;
- greedily accept the highest-ranked pair whose truth and prediction are both unmatched;
- the matching implementation and configuration version are frozen and tested against deterministic fixtures before use.

A future implementation may use an equivalent deterministic maximum-weight bipartite assignment, but it must preserve the same declared objective and deterministic tie-breaking and must receive a new matching-version identifier if results can differ.

### 8.3 Unmatched events and metrics

- matched-event IoU and boundary metrics use only accepted one-to-one matches;
- every unmatched accepted truth event is a false negative;
- every unmatched prediction event is a false positive;
- incompatible event types never match;
- events below the minimum temporal threshold remain unmatched;
- event precision, recall, F1, counts, and denominators include these unmatched events explicitly;
- missing or invalid matching configuration makes the evaluation `inconclusive`, not successful.

## 9. Reproducible multi-label agreement metric

Usability reasons and other multi-label fields are represented as deduplicated sets of exact versioned reason codes.

The required set metric is **Jaccard similarity**:

`J(A, B) = |A ∩ B| / |A ∪ B|`

Rules:

- if both sets are empty because the field is validly not applicable, similarity is `1.0`;
- if exactly one set is empty, similarity is `0.0`;
- unknown, deprecated, or unmapped codes make the comparison invalid until normalized under the recorded taxonomy version;
- report per-item Jaccard, mean and distribution by stratum, exact-set agreement, and per-label agreement/disagreement counts;
- thresholds and reports must use this same representation and empty-set behavior.

Selecting the same top-level usability class does not count as full agreement when the structured reason sets materially differ.

## 10. Unique evaluation identity and idempotency

The complete comparison identity is the tuple:

- `dataset_version_id`;
- `dataset_manifest_sha256`;
- `pipeline_run_id`;
- `prediction_manifest_sha256`;
- `evaluator_version`;
- `evaluator_config_sha256`;
- `event_matching_config_version`;
- `metric_tolerance_version`.

Rules:

- this tuple is unique;
- retries with the same tuple resolve to the same `evaluation_run_id` and cannot create competing accepted results;
- a recoverable failed attempt may append attempt history while preserving the same comparison identity;
- changing any tuple component creates a distinct evaluation identity and result;
- terminal success freezes the result artifact hashes and denominators;
- the result cannot mutate the dataset version, pipeline run, prediction manifest, or production behavior.

## 11. Freeze and acceptance integration

A GAP-027 dataset version cannot freeze until the future implementation proves all of the following in addition to the parent design and guidelines:

- every included item is represented by assignment-scoped annotation state;
- independent annotation sets remain isolated before submission;
- event-level primary-athlete ownership is complete;
- cross-item physical-action lineage is resolved or explicitly uncertain/excluded;
- canonical source binding passes exact-key, hash, size, verification, and supersession checks;
- person merge/split history is representable through accepted lineage relations;
- agreement uses the deterministic event matcher and Jaccard multi-label metric defined here;
- the evaluation identity tuple is enforced idempotently;
- all blocking review disagreements are adjudicated;
- the frozen manifest references exact annotation sets, assignments, accepted revisions, identity-lineage relations, physical-action lineage, instruction/taxonomy versions, and agreement report.

## 12. Review-finding closure map

| Finding | Normative resolution |
|---|---|
| Independent annotations shared one item-wide queue/revision head | Sections 2.1–2.3 introduce isolated annotation sets and assignment-scoped state |
| Item-wide primary conflicted with multiple event owners | Section 3 makes ownership event-scoped and item primary optional/derived |
| Duplicate actions lacked cross-item lineage | Section 4 introduces physical actions and exact source occurrences |
| Prefix-only raw source validation | Section 5 requires server-resolved exact canonical equality plus hash/size checks |
| One `superseded_by` pointer could not model splits | Section 6 introduces revisioned many-to-many lineage relations |
| `edit repair` could imply output-assisted annotation | Section 7 limits the concept to raw-only boundary adjustment |
| Event metrics lacked deterministic matching | Section 8 defines compatibility, one-to-one assignment, tie-breaking, and FP/FN handling |
| Multi-label similarity was unnamed | Section 9 requires Jaccard with explicit empty-set semantics |
| Evaluation uniqueness was underspecified | Section 10 defines the complete idempotency tuple |
