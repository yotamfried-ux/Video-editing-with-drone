# SportReel Annotation Studio — Product & Engineering Specification (DRAFT)

Status: **PROPOSED / awaiting operator UI/UX approval**  
Date: 2026-10-30  
Target: single-user desktop-first local web application for development and evaluation; **not** public athlete-facing product.  
Repository product contract: [README.md](../../README.md).  
**No reset, deletion, storage migration, production deployment or pipeline execution is authorized by this document.**

## 1. Goals and non-goals

Create a persistent human-reviewed ground-truth catalog of original sport footage, with source timestamps, event inclusion/exclusion, athlete attribution and optional frame-level bounding boxes. Enable blind evaluation of the existing pipeline and later ML training without leaking labels into inference. Support new uploads and full replacement of the operational video batch indefinitely.

Out of scope for MVP: public accounts, payments, automatic face recognition/face embeddings, model training, changing production selection logic, automatic approval of AI-generated labels, cloud multi-user collaboration.

## 2. Deployment and operator workflow

- One operator on a personal computer. Preferred delivery: **localhost web UI** (desktop browser, keyboard and mouse) using existing Next.js/TypeScript and Python capabilities where appropriate. Package for local launch later; no public deployment or always-on hosting required for the UI.
- The UI may use an authenticated backend to access protected R2/Supabase resources; credentials remain server-side, never in the browser. Single-user does not mean unauthenticated public endpoints.
- UI optimized for large screens, Hebrew RTL labels with LTR timecodes/filenames and frame-accurate controls; local cache permitted but not sole durable copy.
- Existing operator mobile application and production pipeline remain independent.

## 3. Storage isolation and durability (P0)

Production R2 prefixes `raw/`, `processed/`, `review/`, `approved/` are mutable *operational state*, not stable ground-truth identity. The existing cleanup service can delete video files under those prefixes. Never store the sole ground-truth copy there.

Proposed:
1. **Protected source archive** in a separate R2 bucket or equivalent independent storage boundary; copy original bytes on catalog admission, verify SHA-256 and size before marking `archived`. Use restricted credentials, deletion protection/retention appropriate to the operator, backups, and periodic restore drills. R2 object immutability/retention must be verified rather than assumed.
2. **Protected annotation database** with isolated schema or separate project and credentials. Pipeline runtime has **no SELECT, INSERT, UPDATE, DELETE** on human labels, athlete mappings, approved datasets or archives; do not inject ground-truth secrets into pipeline CI.
3. **Evaluation service** has read-only access to frozen annotations and read-only pipeline outputs, and writes its own evaluation results. Pipeline sees original footage only, not annotations or evaluator verdicts.
4. **Immutable annotation revisions**: append-only revision records, actor (single operator), timestamps, change reason, schema version, approval/freeze metadata. An approved revision is never silently overwritten; new edits produce a new revision.
5. **Backup and recovery**: scheduled database backups and independent backup/export of annotation metadata; recovery tests and integrity audits. Archiving must fail visibly when incomplete.
6. Store stable `source_id` (UUID) and `sha256` for exact-content deduplication; record many changing `storage_locations` with validity intervals. Never key labels to object path or display filename. Transcodes/crops get derivative IDs and provenance; do not assume hashes remain equal.

## 4. New-upload ingestion and reconciliation (P0)

- Accept existing original videos from `raw/`, `processed/`, legacy prefixes and verified upload metadata; explicitly exclude generated `review/`, `approved/`, previews, etc. Distinguish originals from derivatives by source-upload lineage and verified hash, not folder alone.
- New upload flow: upload completion/verification event -> durable ingestion queue -> hash and metadata extraction -> exact-content dedup -> archive original -> register source -> create thumbnail/proxy -> catalog entry `not_annotated`.
- Support batch import, e.g. 50 videos, with per-file progress, retries, resumable jobs and clear error states. On same bytes: reuse source identity; track new upload occurrence and batch membership. Same filename with different bytes is a different source.
- Reconciliation job periodically discovers verified source uploads missed by events and repairs incomplete catalog entries idempotently. Handle eventual consistency, partial uploads, retries, moves and storage outages.
- When production resets or files move, existing source identity and labels stay unchanged. When operational original is deleted, protected archive remains readable.
- Catalog status: `pending_archive`, `ready`, `not_annotated`, `in_progress`, `needs_review`, `approved`, `archive_error`, `unavailable`; distinguish ingestion state from annotation state.
- Source archive admission policy for future uploads configurable (archive all verified originals versus manually selected); default proposed: archive all admitted sources to prevent accidental loss, with retention/cost dashboard and explicit approval for destructive pruning.

## 5. Annotation data model

Proposed entities:
- `sources`: UUID, sha256, byte size, codec, resolution, fps numerator/denominator, frame count, duration, capture timestamp (if known), ingest state, archive reference, created_at.
- `source_locations`: source_id, provider/bucket/key, kind, observed_at, active, verified checksum.
- `upload_batches` and `batch_sources`: import history and many-to-many batch membership.
- `athletes`: opaque UUID, operator label, optional non-biometric descriptors, notes; avoid face embeddings or automatic cross-video biometric matching.
- `athlete_appearances`: athlete_id, source_id, local track/appearance id, confidence/uncertain flag, manual confirmation; cross-video linkage only with explicit operator confirmation.
- `segments`: source_id, start_frame, end_frame (define inclusive/exclusive consistently), athlete_appearance_id nullable, sport, event_type, inclusion decision (include/exclude/uncertain), reason code, freeform notes, created revision.
- `frame_annotations`: segment/appearance id, frame index, bbox normalized coordinates, visibility/occlusion, interpolation provenance, manual-vs-suggested status.
- `annotation_revisions`: immutable revisions, source_id, parent_revision, author, created_at, approved_at, review state, content digest.
- `dataset_versions` and `dataset_members`: frozen references to exact source hashes and approved revision IDs; split (train/validation/test), grouping and policy metadata.
- `pipeline_predictions`: run ID, pipeline version/commit, source lineage, predicted events/tracks and output artifacts.
- `evaluation_runs` and `evaluation_errors`: evaluator version, dataset version, metrics, matched/unmatched segments, diagnosis and evidence links.

Store canonical timestamps in frames against original video timebase, display as timecode; for variable-frame-rate media store presentation timestamps as needed. Never infer an exact frame from a rounded decimal time alone.

## 6. Annotation editor behavior

Desktop video player with waveform optional, thumbnail filmstrip and zoomable multitrack timeline. Start/end marking via keyboard, per-athlete tracks, colored inclusion/exclusion/uncertain states, direct segment editing, optional bounding-box drawing on frames, playback speed, single-frame stepping, notes, reject reasons, and quick athlete creation/selection.

Suggested keyboard shortcuts: Space play/pause; I mark in; O mark out; arrows frame-step; 1–9 choose athlete; N next unreviewed suggestion; Ctrl/Cmd+S manual save. All shortcuts editable and disabled while typing into fields.

Autosave drafts with optimistic concurrency, offline/error indication and recovery. Approved ground truth requires explicit operator confirmation; AI suggestions are stored in separate suggestion records and **never** silently promoted to approved truth. Track unreviewed footage; absence of a segment is not automatically a negative label. Support marking reviewed time ranges explicitly.

## 7. Evaluation and ML readiness

- Blind evaluation: isolate ground truth from inference, freeze dataset/version and pipeline commit, then run the pipeline on original footage.
- Deterministic matching by source ID, temporal overlap tolerance/IoU and athlete attribution; log ambiguous matches, double counts and reason codes. Report event precision/recall, athlete coverage, identity attribution, temporal accuracy, false positives, false negatives, wrong-athlete events, duplicate reels, output coverage and editing quality separately.
- Split by recording session/athlete where feasible to avoid near-duplicate leakage across train/test; keep a permanently held-out test set. No training on test or blind-evaluation labels.
- Model-training exports (JSONL/COCO-like or task-specific) are generated from **approved** revisions only, with schema versions, provenance, licensing/consent review and reproducible manifests. This spec does not authorize training or biometric identification.
- Error-review screen shows human segment, prediction, corresponding original frames, pipeline outputs, and source-to-render lineage. Preserve historical comparisons across model versions.

## 8. UX concepts — pending explicit approval

These are design alternatives, **not approved implementation requirements**:

**A — Precision Annotation Workbench (recommended)**  
Large source video at top-left; frame-accurate, zoomable multitrack timeline below; right-side form for surfer, event type, include/exclude, notes and bounding boxes. Keyboard-first. Good for intensive labeling.

**B — Library & Batch Triage**  
Card/grid of source thumbnails, upload batch, duration, archive verification, annotation progress, quick filters, next unannotated, bulk operations (non-destructive). Good for ingesting future batches.

**C — Athlete & Evaluation Explorer**  
Athlete directory with appearance galleries and uncertainty flags; side-by-side human-versus-pipeline video/timeline with highlighted misses, wrong identities and duplicates; filter by pipeline run/dataset version. Good for QA and model iteration.

Proposed navigation: Library | Annotate | Athletes | Datasets | Evaluations | Settings. All screens must display source archive integrity and save/sync status where relevant. User must approve layouts, field density, keyboard interaction and light/dark visual direction before UI implementation.

### Example interaction

New 10-video upload -> 10 queued ingestion records -> verified archive copies -> 10 cards appear -> operator opens a video -> marks frames covering 00:18.2–00:28.7 as a usable wave -> assigns Surfer #1 -> marks a second failed attempt as exclude -> reviews remaining time or explicitly leaves unreviewed -> approves revision 1 -> later run moves raw to processed and creates reels -> annotations remain unchanged -> evaluator compares predictions with approved revision 1.

## 9. Reset of last production run — separate approval gate

Operator requested returning originals to `raw/` and deleting outputs **from the last run only**. This is NOT authorized for execution by this design document.

Before any reset: identify exact last run ID, frozen batch, source manifests, current raw/processed keys, object hashes and references; ensure no active pipeline; make verified backup/snapshot; show operator an explicit dry-run inventory and deletion manifest. Restore originals idempotently without overwrites; delete only proven outputs owned exclusively by the selected run, after explicit confirmation. Preserve logs, run metadata and audit evidence. Never invoke broad `Clean Video Storage`, `full_clean`, or delete unrelated prior-run/customer assets.

## 10. Acceptance criteria

1. Upload 1, 10, and 50 new videos; every verified source eventually appears exactly once by content, with upload occurrences preserved.
2. Move source between `raw/` and `processed/`; annotations, approved revisions and archive playback remain unchanged.
3. Simulate operational cleanup in an isolated fixture; protected archive and annotation database remain untouched.
4. Simulate interrupted upload, hash mismatch, archive failure and ingestion event loss; recover through reconciliation with visible errors and no false success.
5. Annotate multiple surfers and overlapping events, exclude intervals, mark uncertainty, add bbox, approve and revise; reload retains exact frame positions and revision history.
6. Run pipeline without annotation credentials; verify access denied to Ground Truth.
7. Evaluate against frozen dataset; report correct matches, misses, duplicates and wrong-athlete assignments; repeat produces same results.
8. Prove backup restoration, archive checksum verification and audit logging.
9. No production mutations, new deployments, paid services or destructive reset before explicit approval.

## 11. Open decisions

- Operator approval of UI layout(s) and visual design, including whether annotation and evaluation are separate screens.
- Archive policy/cost ceiling and verified provider retention capabilities.
- Whether the single-user app runs entirely local or uses a local UI with remote protected backend (recommended).
- Source footage consent/retention requirements and whether athlete identity should be session-local by default.
- Exact most-recent run ID and scope for future reset, to be confirmed in a separate dry run.
