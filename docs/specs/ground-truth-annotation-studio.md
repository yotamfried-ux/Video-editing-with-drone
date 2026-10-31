# SportReel Annotation Studio — Product & Engineering Specification

Status: **APPROVED DESIGN DIRECTION: Precision Studio / implementation specification**  
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

## 8. Approved primary UX and supporting screens

The operator selected **A — Precision Annotation Workbench** as the approved primary screen. B (library/batch ingestion) and C (evaluation) remain supporting screens, not competing primary UI designs. Detailed visual polish remains iterative:

**A — Precision Annotation Workbench (recommended)**  
Large source video at top-left; frame-accurate, zoomable multitrack timeline below; right-side form for surfer, event type, include/exclude, notes and bounding boxes. Keyboard-first. Good for intensive labeling.

**B — Library & Batch Triage**  
Card/grid of source thumbnails, upload batch, duration, archive verification, annotation progress, quick filters, next unannotated, bulk operations (non-destructive). Good for ingesting future batches.

**C — Athlete & Evaluation Explorer**  
Athlete directory with appearance galleries and uncertainty flags; side-by-side human-versus-pipeline video/timeline with highlighted misses, wrong identities and duplicates; filter by pipeline run/dataset version. Good for QA and model iteration.

Proposed navigation: Library | Annotate | Athletes | Datasets | Evaluations | Settings. All screens must display source archive integrity and save/sync status where relevant. Precision Studio layout is approved; visual styling can be refined through a local clickable prototype without reopening the architecture decision.

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

- Precision Studio approved as primary layout; final styling and detailed interactions to be validated in a clickable local prototype.
- Archive policy/cost ceiling and verified provider retention capabilities.
- Whether the single-user app runs entirely local or uses a local UI with remote protected backend (recommended).
- Source footage consent/retention requirements and whether athlete identity should be session-local by default.
- Exact most-recent run ID and scope for future reset, to be confirmed in a separate dry run.

## 12. Editing Ground Truth — evaluate actual rendered video (approved scope)

**Goal:** assess not just event selection and athlete identity, but whether the *rendered output* frames the correct surfer and preserves useful wave context. This is a distinct third layer: (1) event truth, (2) tracking truth, (3) editing/composition truth.

### 12.1 Coordinate and time lineage

- Preserve a deterministic **edit decision list (EDL)** for every rendered output: `output_id`, `pipeline_run_id`, `source_id` and immutable source hash, output timestamp/frame -> source presentation timestamp/frame mapping, source dimensions, output dimensions, crop rectangle per output frame or time-keyframe, resize/pad/rotation parameters, playback speed and any stabilization transforms.
- Store and version EDL alongside output manifest; make it accessible to evaluator only after pipeline inference. When EDL is absent, use visual frame matching as an explicitly lower-confidence fallback and mark results `unverified_mapping`.
- Ground-truth surfer box is expressed in **source coordinates**. Transform into output coordinates using the actual crop and resize/rotation/padding transform; if a transform is missing, refuse exact center scoring rather than guessing.
- Multiple people and occlusion are expected. Preserve source-frame subject identity and confidence; mark `not_visible`, `occluded` and `unreviewed` separately.

### 12.2 Composition labels and operator controls

- Operator can choose a target framing mode per segment: `geometric_center` or `directional_lead_room`; optionally manually specify a desired normalized target point or desired crop box at selected keyframes.
- Keyframe labels can define desired crop path. Interpolated paths are proposals until reviewed; keep original operator labels and automated proposals separately.
- Editing Review tab in Precision Studio: synchronized **original source + rendered output**, overlay ground-truth athlete box, actual output surfer center, target center/region, crop boundary, safe margins and failure timestamps; click a failure to jump both players to corresponding frames.
- Permit dragging a proposed crop window on original footage, previewing an alternative edit without changing source video or overwriting the production output. Save operator-approved crop examples as new immutable editing revisions.

### 12.3 Metrics and evidence

- **Centering error:** normalized Euclidean distance from actual output surfer center to operator-selected target; report median, p95 and temporal distribution. A target of (0.5,0.5) is used only when geometric centering is selected.
- **Visibility:** percentage of *reviewed* frames with surfer fully visible; separately report partially clipped, completely missing and occluded frames. Do not treat missing detection as definitive disappearance without supporting evidence.
- **Edge violations:** frames where box crosses a configurable safe-area margin; distinguish partial clipping from intentional composition.
- **Tracking continuity:** source-linked identity switches, interruptions and incorrect-athlete output intervals.
- **Crop smoothness:** output crop center/scale velocity, acceleration and jerk, normalized by frame time and resolution; flag abrupt changes with configurable thresholds.
- **Wave context:** human-rated preservation of wave/trajectory and optional future machine-estimated context; do not present unvalidated heuristic as ground truth.
- Produce frame-level evidence and aggregate per segment, output, surfer, run and frozen dataset. Store evaluator version and thresholds with every report.

### 12.4 Evaluation correctness

- Compare outputs only to the **approved, frozen revision** selected for that evaluation run.
- Distinguish annotation coverage from actual quality; exclude unreviewed/uncertain intervals from strict aggregate scoring, and report their proportion.
- Do not optimize model hyperparameters or train on the held-out evaluation/test set. An alternative crop generated by an algorithm is a *proposal*, not a human-approved target.
- Evaluate timing decisions, subject framing, identity continuity and final output artifact quality independently; a correct event with a poor crop must still fail editing quality criteria.

### 12.5 Editing-specific acceptance tests

1. Known synthetic source boxes and crop transforms yield analytically correct output coordinates, including resize, pad and rotation.
2. Deliberately off-center surfer triggers centering deviation; directional lead-room is not incorrectly penalized as off-center.
3. Clipped surfer, identity swap and sudden crop jump are reported with exact output/source timestamps and replayable evidence.
4. Missing EDL is flagged as unverified, never silently treated as exact.
5. Operator adjustment of a crop creates a new approved editing revision without mutating original video, historical labels or production output.
6. Reset or movement of operational files does not change stored source identity, annotations, EDL lineage or archived evaluation reports.

## 13. Claude development handoff

Start with repository discovery and a non-destructive architecture audit. Confirm current upload events, R2 object lifecycle, Supabase schemas, pipeline artifact/EDL provenance, cleanup paths, local dev scripts and existing security boundaries; report evidence and gaps before schema migrations.

Implement in stages with tests and review gates:
1. Protected source archive and catalog source identity, new-upload reconciliation, safe ingestion states and migrations.
2. Local desktop-first Precision Studio (video, multitrack segment editor, athlete identities, bbox keyframes, autosave/revisions, approval).
3. Dataset freezing and blind pipeline evaluation with reproducible reports.
4. Editing Review, EDL capture, source-to-output coordinate transforms, crop metrics and alternative crop preview.
5. End-to-end regression, recovery, authorization-denial and backup-restore tests.

Do not run destructive reset, remove production outputs, change production credentials or deploy paid infrastructure without explicit operator approval. Treat generated UI mockups as conceptual references rather than source assets or implemented screens.

## 14. Existing SportReel product contract — MUST NOT REGRESS

Read repository `README.md` and `docs/operator-pipeline-contract.md` before implementation. The canonical business contract is **one featured athlete per silent, vertical publishable reel**, complete eligible actions, evidence-backed hard rejects, and QA fail-closed. In particular:

- Default framing is **contain**, keeping the entire 4K source frame inside the 9:16 canvas. Source production is 4K/30 and canonical output 2160x3840/30, silent, maximum 90 seconds. Tracked destructive crop/zoom is exceptional and requires evidence-backed necessity; **do not change pipeline defaults** merely to optimize a centering score.
- Therefore editing evaluation must distinguish `contain` from `tracked_crop` and `pad` (if present). For `contain`, measure position and readability within the displayed source region and output canvas separately; do not classify a correct contain render as a crop failure. For tracked crop, calculate actual crop geometry and subject visibility.
- A surfer need not occupy geometric center in every frame; valid context, wave direction and full-source containment matter. An isolated high centering-error score is not grounds to discard a publishable reel.
- Other surfers in frame are expected. Never mark a reel wrong merely because another surfer appears; only target identity switch/attribution is a defect.
- No face enrollment, face embeddings or biometric account matching. Existing mandatory detector/tracker evidence stays mandatory; no Gemini-only fallback.
- Keep operator controls behind existing security boundary, and avoid interfering with upload, reset, approval, payment or delivery flows.

## 15. Implementation-ready UI interaction specification

### 15.1 Navigation and layout

Desktop baseline: 1440x900 viewport, responsive minimum 1280x720, RTL chrome, LTR video timecodes. Top bar shows project name, source name, source archive verified indicator, annotation revision and save status. Left collapsible sidebar: Library, Annotate, Athletes, Datasets, Evaluations, Settings.

Precision Studio:
- Main video viewport should occupy most available width. Show bbox overlays with stable color per appearance and selected athlete ID; clicking a box selects that appearance. Overlay visibility toggle must not modify saved labels.
- Below player: synchronized scrubber and zoomable timeline; one track per surfer plus optional global event/review track; overlapping segments allowed. Show event bars, explicit reviewed intervals and unknown/unreviewed areas distinctly.
- Right inspector: selected source and segment, athlete assignment, event kind, decision include/exclude/uncertain, reject reason, notes, bbox/keyframe controls and approval. Collapsible to prioritize footage.
- Video controls: play/pause, frame step, playback speed 0.25x/0.5x/1x/2x, jump to next segment, in/out marks, timecode, zoom timeline, fit timeline, keyboard shortcut help.
- Editing Review: side-by-side synchronized source and final render, source-to-output mapping indicator (verified/unverified), bbox/crop overlays, centering and visibility graphs, jump-to-failure list, proposed crop preview.
- Library: thumbnail grid/table toggle, search, batch/date/status filters, archive verification badge, count of approved/reviewed/unreviewed, `Continue annotation` CTA. Missing thumbnails do not block annotation.

### 15.2 Interaction states and validation

- Press `I` to set start; `O` to set end; create segment only if end > start and both are inside the source duration. Store half-open `[start_frame,end_frame)` interval for constant-FPS sources; for variable-FPS use exact presentation timestamps and indexed frame references.
- An event can overlap other events and have multiple appearance references if supported; the featured athlete must be explicit for athlete-specific evaluation. If unknown, choose `unknown`, never silently guess.
- Bounding box normalized `x,y,w,h` values each within [0,1], with positive width/height and box constrained to image bounds. Source dimensions and rotation are recorded. User can correct a proposed track at keyframes; generated interpolation is visually distinguished from manually confirmed boxes.
- Approve only after operator explicitly reviews the relevant interval and sees unresolved unknown/uncertain counts. Do not force all footage to be annotated before saving partial revisions; approval scope (segment/interval/source) must be explicit.
- Save status: `saving`, `saved`, `offline/pending`, `conflict`, `failed`; unsaved work must not be silently lost. Use local durable draft queue with replay and conflict UI, not local cache as authoritative storage.
- Accessibility: labels for controls, visible focus, contrast, non-color-only meaning, keyboard-only segment workflow, reduced motion where possible.

### 15.3 Example operator journey

Open Library -> select new batch -> source with verified archive -> player loads proxy preserving original timestamp mapping -> choose surfer or create new pseudonymous ID -> I/O segment -> classify wave -> draw bbox on 2–3 keyframes -> optionally request tracking proposal -> review/correct -> mark reviewed time range -> save draft -> approve revision -> freeze dataset -> run blind evaluator later. If source moves from raw to processed at any point, reload shows same source UUID, exact segment frames and approved revision.

## 16. Technical contracts and failure handling

### 16.1 Logical API (adapt paths to actual repo conventions after discovery)

- `GET /annotation/sources?status=&batch=&cursor=` paginated catalog; `GET /annotation/sources/:id` metadata and secure short-lived playback URL for protected archive.
- `POST /annotation/ingestion/reconcile` idempotent operator-only reconciliation trigger; asynchronous job returns job ID/status. Never blindly import generated output prefixes.
- `GET /annotation/sources/:id/revisions`, `POST /annotation/sources/:id/drafts` with expected revision/ETag, `POST /annotation/sources/:id/approve` with expected draft version; server validates frames and identity references.
- `GET/POST /annotation/athletes`, `GET/POST /annotation/datasets`, `POST /annotation/evaluations` (async, immutable version IDs), `GET /annotation/evaluations/:id`.
- `GET /annotation/outputs/:id/edl` and `POST /annotation/edits/:id/proposals` for editing QA. A proposal must never overwrite production output.
- API responses use consistent error codes: `INVALID_INTERVAL`, `INVALID_BBOX`, `VERSION_CONFLICT`, `ARCHIVE_UNVERIFIED`, `SOURCE_UNAVAILABLE`, `PERMISSION_DENIED`, `EDL_UNVERIFIED`, `INGEST_RETRYABLE`. Return human-readable Hebrew messages without exposing internal credentials.
- Pagination and bounded preview generation are mandatory for large collections; no loading 50 full-resolution videos into the browser simultaneously.

### 16.2 DB and ingestion invariants

- Unique index on exact `(sha256, byte_size)` for original content, with a collision/verification fallback; source UUID never changes. Multiple upload occurrences may point to one source.
- Ingestion is idempotent under repeated webhook delivery, batch re-import and reconcile; status transitions are transactional and auditable. Mark `ready` only after archive integrity verification.
- Avoid direct production storage rename as a prerequisite for annotation. Archive and catalog operations must be non-destructive.
- Never place service credentials in `NEXT_PUBLIC_*`, browser bundles, logs or test fixtures. Use least-privilege separate principals; include negative authorization tests.
- Data migrations are reversible where feasible, applied in test environment first, and do not alter production pipeline tables or policies without separate approval.
- Dataset split assignment groups near-duplicate recordings/sessions and linked athlete appearances to prevent leakage; freeze revision/hash manifests.

### 16.3 Explicit evaluation formulas

For a reviewed output frame with verified mapping, transform source bbox through actual EDL geometry to output pixel bbox. Normalize center to `(cx/Wout,cy/Hout)`. For operator target `(tx,ty)`, centering error is `sqrt((cx/Wout-tx)^2+(cy/Hout-ty)^2)`. Report distribution and coverage denominator. Edge violation when transformed bbox intersects operator-configured unsafe margin; visibility uses intersection area with displayed output bounds, while separately tracking occlusion. Crop smoothness uses timestamp-normalized derivatives of crop center/scale, excluding genuine edit cuts; compare only within continuous shots. Record thresholds/config and evaluator version. When evidence is missing, report `NOT_EVALUABLE` rather than a passing metric.

### 16.4 Recommended delivery milestones and definition of done

**M0 — Discovery + plan:** inventory exact repository routes, migrations, workflows, R2 lifecycle and output manifests. Produce gap matrix and implementation plan with file paths, dependencies, risks, tests and estimated complexity. No production changes.

**M1 — Safe local prototype:** clickable Precision Studio with synthetic/mock source and bbox/timeline, keyboard workflow and save states; operator can review layout. No real storage writes.

**M2 — Durable catalog:** isolated archive/database, migration/tests, ingestion/reconcile, source UUID/hash, verified archive playback, recovery/backup tests; test data first.

**M3 — Human annotations:** multitrack segment editing, athlete appearances, bbox keyframes, drafts, approvals, revision history, reviewed coverage, autosave/conflict handling; end-to-end browser tests.

**M4 — Blind evaluation:** dataset freezing, access-denial test for pipeline, source/prediction alignment, reproducible event/tracking metrics and evidence dashboard.

**M5 — Editing QA:** EDL output provenance, source/render sync, contain-vs-crop evaluation, centering/visibility/continuity/smoothness metrics and operator-approved alternative crop proposals.

For each milestone: commit scoped changes to feature branch, run relevant lint/type/unit/integration/E2E tests, attach test logs and sample screenshots, document known limitations, and obtain operator approval before production resource changes. Do not claim `PASS` without execution evidence. Never implement a destructive last-run reset as a side effect of this project.

## 17. Decision log

Approved: single-user desktop-first local interface; Precision Studio as primary annotator; library and evaluation as supporting views; future upload support; immutable independent Ground Truth; temporal/identity/tracking labels; editing-quality assessment of actual renders.

Pending: precise archive service/cost and retention settings; consent and source retention; final visual details; local-only versus localhost UI with protected remote backend; approval of any real cloud resource creation and last-run reset. Claude should make reversible defaults for mock implementation, clearly flag decisions needing authorization, and continue non-destructive work rather than blocking on minor styling choices.

## 18. Multi-sport catalog and sport-aware annotation (approved requirement)

The catalog is **multi-sport by design**; surfing is the initial reference workflow, not a hardcoded system-wide assumption. The existing SportReel README requires sport-specific action definitions with a shared athlete/reel business contract.

### 18.1 Taxonomy and data contracts

- Add a versioned `sports` registry: stable machine key (e.g. `surfing`, `football`, `basketball`, `tennis`), Hebrew/English display names, enabled flag, schema/taxonomy version. Do not rely on translated display strings as identifiers.
- Each source has an explicit `primary_sport_id` or `unknown/unclassified` until reviewed; optional many-to-many `source_sports` supports mixed-sport footage, with sport assignment per segment authoritative when different. Never infer or overwrite operator-confirmed sport from filename or AI guesses.
- Add `sport_event_types` with stable sport-scoped event keys, display labels, optional parent event category and configurable required attributes. Examples: surfing `wave_ride`, `takeoff_attempt`, `paddling`; football `shot`, `pass`, `goal`; basketball `shot`, `assist`, `rebound`; tennis `serve`, `rally`, `point`. These are initial examples, not exhaustive or hardcoded enum restrictions.
- Every segment references a sport and a sport-scoped event type; validate compatibility server-side and in UI. Preserve historical taxonomy version in approved annotation revisions and frozen datasets; retiring an event type must not invalidate existing annotations.
- Keep sport-neutral base entities: sources, athletes, appearances, tracks, segments, boxes, reviewed ranges, revisions, datasets, predictions and evaluations. Sport-specific attributes live in versioned validated extension payloads or normalized tables when justified, not dozens of nullable sport-specific columns.
- Support operator correction of sport labels and bulk classification for uploads, with auditable revisions; do not silently reclassify approved data.

### 18.2 UX and ingestion

- Library displays sport badge, sport filter, `Unclassified` queue and bulk assign action. New footage may have a suggested sport from metadata/model, but suggestion is clearly labeled and requires confirmation.
- Annotation inspector sport selector determines available event types and relevant sport-specific fields. Changing sport warns about incompatible existing event labels and offers explicit remapping; never delete them automatically.
- Segment timeline and athlete identity remain sport-agnostic. Multiple sports can appear in one source; event overlap and athlete attribution remain supported.
- Settings includes sport/event taxonomy administration, with validation, versioning and no-code addition of new sports/event types.

### 18.3 Sport-aware evaluation

- Evaluation config and metrics declare sport/taxonomy version and event matching policy. Shared metrics: timing, athlete identity, track continuity, subject visibility, source/output lineage and technical output QA.
- Sport-specific metrics: surfing wave completeness and wave context; football play/action context; basketball ball/hoop context where annotated; tennis court/ball context where annotated. Do not claim to measure unannotated ball/wave/court context automatically.
- Maintain shared contain-first framing and publishable-reel contract across sports; do not introduce crop changes merely to improve a sport-specific score.
- Split datasets by source/session and athlete as appropriate, stratify by sport where feasible, and report per-sport quality and coverage. Do not aggregate scores across sports without denominators and transparent weighting.
- Existing surfing labels/data remain readable after migration; supply migration/backfill with explicit `unknown` where sport cannot be proven rather than assuming every historical video is surfing.

### 18.4 Acceptance tests

1. Import surfing, football and mixed-sport sources; classify/filter by sport, including unknown.
2. Create sport-specific segments in one source, validate incompatible sport/event pairs are rejected.
3. Add a new sport and event type through configuration without application code changes.
4. Reclassify a draft and preserve audit history; approved historical revisions and frozen datasets remain unchanged.
5. Produce sport-separated evaluation reports, with no cross-sport event matching.
6. Verify legacy surfing annotations and existing pipeline workflows remain backward compatible.

### Phase B implementation impact

Include sport registry, sport-event taxonomy, source and segment sport classification, versioned schemas, sport-aware ingestion/UI filters and evaluation grouping in Phase B's gap matrix and migrations. Prefer schema-driven extensibility over sport-specific forks. Build and test the general contract with surfing and at least one additional sport, without requiring production changes until explicitly approved.

## 19. Implementation notes — M1–M5 (as built)

Product requirements above are unchanged. These are technical adaptations discovered during implementation (see `annotation-studio/` and `docs/annotation-studio/STATUS.md`):

- **Delivery form:** zero-dependency Node 22 service (`node:sqlite`) + vanilla ES-module UI under `annotation-studio/`, bound to `127.0.0.1`, per-install token. The R2 archive and separate Supabase project in §3 are expressed as adapters (`ArchiveStore`, `db.mjs`); only local implementations exist. Creating the real resources still requires operator approval.
- **Revision storage:** an approved revision is one immutable JSON document (`annotation_revisions.content`, schema 1) with a SHA-256 content digest, instead of separate normalized `segments`/`frame_annotations` tables. Segments reference persistent `athlete_id`s; `athlete_appearances` rows are derived per (athlete, source). Normalized projections for training export are produced from frozen revisions (`exportJsonl`).
- **Drafts vs revisions:** drafts are mutable with optimistic `version`; only approval creates a revision. Idempotent when the digest is unchanged.
- **Approval gating:** unresolved counts (`uncertain` segments, `include` with unknown athlete) require explicit `acknowledge_unresolved`; approval also requires `ingest_state='ready'` (verified archive).
- **Intervals:** half-open `[start_frame, end_frame)`; the `O` key marks the *current* frame as included (`end = frame + 1`). Seeking uses mid-frame time `(f+0.5)/fps`. Proxy videos are constant-fps VP9/WebM with the source frame rate.
- **Editing evaluation:** `edl/v1` (shots with linear crop interpolation in source pixels, optional output rotation, optional `subject_track`); `contain` is never scored against a centre target; no EDL or `mapping:"visual_match"` ⇒ `NOT_EVALUABLE`/`unverified_mapping`. The production pipeline does not emit this format yet (separate approval).
- **Evaluator identity mapping:** pipeline athlete keys are mapped to GT athletes by deterministic co-occurrence over temporally matched events; deviations are reported as `wrong_athlete`.

## 20. Implementation notes — Phase B (infrastructure and pipeline integration)

Status of live infrastructure and real-footage validation: see `docs/annotation-studio/STATUS-PHASE-B.md`. Product requirements are unchanged; technical adaptations:

- **Pluggable backends.** Catalog: SQLite (default) or PostgreSQL (`STUDIO_DB_URL`, role `gt_studio`); archive: local write-once or `R2Archive` (`STUDIO_R2_*`, dedicated bucket). Schema/roles live in `annotation-studio/db/` (never under `supabase/migrations/`) and are applied only by `npm run migrate` with an admin connection.
- **Isolation is privilege-based.** `service_role` bypasses RLS, so Ground Truth is protected by schema ownership and `REVOKE`s (tested against real PostgreSQL roles), with RLS and append-only triggers as additional fences. The evaluator uses role `gt_evaluator` with access to `frozen_*` views, predictions, and its own results only.
- **Archive deletion protection** cannot be expressed in an R2 token (Object R/W includes delete): use a bucket-lock retention rule on the archive prefix (verified live by a probe before use), a separate Studio token, an independent second copy, and the adapter exposes no delete.
- **Zero-extra-cost infrastructure decision (2026-10-30):** default is local-first (SQLite + local write-once archive) with independent encrypted backups; the PostgreSQL/Supabase schema and the R2 archive remain tested options. A new Supabase project (from $10/month) and metered R2 usage beyond the free tier are not adopted without explicit approval. See `docs/annotation-studio/phase-b/INFRASTRUCTURE-DECISION.md`.
- **`edl/v1` additions:** per-shot `mode`, `source_sha256`/`source`, `keyframes` (piecewise-linear crop in output frames), `subject_track`, and top-level `blends`; reel `mode` may be `mixed`. Cross-dissolve frames are excluded from scoring.
- **`predictions/v1`:** produced from the existing candidate ledger + EDLs; carries `run_id` and the full code commit; the importer rejects exports without them. Rejected candidates are diagnostics (a missed GT event overlapping a pipeline rejection is reported as `pipeline_rejected`).
- **Export is opt-in and observational:** `SPORTREEL_EXPORT_EDL=1`; rendering arguments are unchanged (tested). EDL records are built from the exact values passed to ffmpeg and checked against rendered pixels.

### 20.1 Multi-sport (§18) — as built in PR #312
- **Implemented (SQLite + PostgreSQL `0002_sports.sql`):** `sports` and `sport_event_types` registry (stable machine keys; Hebrew/English labels; `enabled`; per-sport `taxonomy_version`, bumped and audited on every change; rows are never deleted — retiring only hides a type from pickers). `sources.primary_sport_id` (NULL = unclassified, **never backfilled to surfing**; changes are audited with before/after). Per-segment `sport_id` override for mixed footage; the server stamps `resolved_sport_id` into stored content so frozen revisions are self-describing for the blind evaluator. Server-side sport/event compatibility (unclassified sources accept only the legacy keys); per-event-type required attributes (`segment.attrs`). Reclassifying a source with incompatible draft segments is refused with the list; the operator remaps explicitly (nothing is deleted); approved revisions and frozen datasets are untouched. `taxonomy_versions` is pinned on every approved revision and in dataset manifests. Evaluation never matches across sports and reports `by_sport` denominators (`eval-1.1.0`). `predictions/v1` events may carry `sport_id` (per event or per source; the exporter sets it only from the ledger or the operator-set `SPORTREEL_SPORT` — never inferred). New sports/event types are added in **הגדרות ענפים** without code changes. Backup/restore carries the registry.
- **Acceptance tests (§18.4):** (1) classify/filter/bulk incl. unknown, (2) incompatible pairs rejected, (3) new sport via configuration, (4) reclassification keeps audit and history, (5) sport-separated evaluation, (6) legacy data readable — `annotation-studio/tests/sports.test.mjs` (SQLite and PostgreSQL) and browser scenarios in `tests/e2e/workflow.mjs`.
- **NOT implemented (future phase, stated so it is not mistaken for done):** model/metadata **suggested** sport with confirmation (there is no AI sport classifier; every classification is operator-made); many-to-many `source_sports` table (mixed footage is covered by the per-segment override, which §18.1 declares authoritative); dataset **stratification** by sport (splits remain group-aware by session, per-sport coverage is reported in evaluations only); sport-specific quality metrics (wave completeness, play context, ball/hoop/court context) — only shared event timing/identity/visibility metrics exist and the tool does not claim to measure unannotated context; `kind/category` hierarchy beyond `parent_key` storage.
