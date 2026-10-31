# SportReel Precision Studio V2 — approved UX implementation contract

**Approved by operator:** 2026-10-31. **Status:** design target, NOT implemented. This document supplements product spec §21; implementation must also comply with §§1–20 and the Ground Truth original design, v1 annotation guidelines and normative design review addendum.

**Approved clickable prototype:** [Precision Studio V2](precision-studio-v2-approved.html). The prototype is self-contained, disconnected from real APIs and uses a **synthetic wave illustration** in place of real source footage. It is a design and interaction reference, never production code or a quality test.

## 1. Visual baseline and primary tasks

Match the accepted Precision Studio V2 composition: compact left navigation plus searchable catalog, large center video with labeled BOX overlays, synchronized zoomable event/surfer lanes and filmstrip underneath, and a persistent right inspector with a simple task order. Palette is dark navy with blue/cyan CTA, state badges and clear contrasts. Desktop targets: 1440×900 and 1920×1080, fully accessible in Hebrew RTL with LTR timecodes/source coordinates. Basic tasks visible without scrolling through advanced panels.

Prominent, literal actions: **שייך סרטון לגולש**, **סמן גולש**, **אמת BOX**, **סמן התחלה**, **סמן סוף**, **שמור טיוטה**, **שלח לבדיקה**, **אשר Ground Truth**. Do not hide critical actions in an unselected segment inspector; when loading existing segments, show the selected segment immediately or explain exactly how to select it. Visual samples are not evidence of working functionality.

## 2. Manual video ownership: mandatory part of cataloging

A **single explicitly assigned catalog owner surfer** is the operator's answer to "לאיזה גולש הסרטון שייך?". It may be unknown/unassigned/uncertain. This answer is NOT the same as: (a) all people visible, (b) the performer in each event, or (c) a cropping/edit target. A source can show several athletes. A video belonging to Surfer A can contain an event performed by Surfer B. Never silently infer owner from a segment, upload filename, camera focus, person detector or a predicted identity.

**Entry points:** the Library card, Cloud video row and video header display the current assignment and a prominent "שייך לגולש" control. Select an existing pseudonymous athlete via searchable dropdown, create one inline or mark Unknown/Needs Review. The workflow works **before any event or bounding box is made**, and displays immediate saving feedback. One-click entry; few actions to complete. Reassignments require confirmation and an optional reason, with history.

**Surfer Workspace:** searchable surfer cards with section "סרטונים שמשויכים אליי" (all catalog-owned videos, even those with zero segments), and separately "סרטונים שבהם הגולש מופיע" (observed appearances); distinct filters, thumbnails, event counts, track QA, progress and last-playback position. Every video has an obvious "Open / Continue annotation" link. Bulk assignment supports dry preview, conflicting-owner warnings, bounded source IDs and an explicit confirmation.

**Data:** additive source-to-catalog-owner relation with exactly one current primary owner per source UUID, a confirmation/review state and concurrency version, operator attribution, timestamps, assignment reason, immutable history of changes. Keep existing athletes and athlete_appearances independently; presence may be uncertain. Do not backfill owner automatically from legacy segment performer. Never overwrite approved revisions or frozen datasets. IDs reference canonical content-based source, not R2 key or display name. Cross-video same-person linking requires human confirmation; no facial templates or biometric match.

Example API additions (adapt to repository conventions): GET/PUT /api/sources/:id/catalog-owner with expected_version, GET /api/athletes/:id/sources with owner/appearance filters, POST /api/sources/catalog-owners/bulk with preview/apply. Implement in both SQLite and PostgreSQL adapters with validation and rollback-safe migration. Auditable reassignment, conflicts and access-denied tests are mandatory.

## 3. BOX on the surfer: verification, not mere interpolation

Current web/js/annotate.js supports manual keyframes and linear position interpolation. A box at an estimated frame is **a candidate**, not an automatically verified actual surfer. Implement clear operator-facing "אמת BOX" workflow adjacent to the video.

1. Select the surfer, event/track and precise source frame.
2. Draw, resize or correct the box on a high-quality **source-mapped** frame, identifying target athlete.
3. Ask the operator: **נכון — על הגולש** / **לא נכון — תקן BOX** / **מוסתר או מחוץ לפריים** / **לא ניתן לקבוע**.
4. Review start, middle and end and further checkpoints for long tracks; include risk points such as two athletes crossing, disappear/reappear, occlusion, rapid motion, predicted switch or box jump. Display exactly **which frame intervals were inspected** and confidence/coverage.
5. A single approved frame must NEVER imply all intervening frames verified. Manually verified, interpolated, AI-suggested, unverified and wrong/needs-correction boxes need different visible styles, including icons/words not just colors.
6. Wrong athlete/box creates a precise review task; correction records original proposed box and new manual box with time, reviewer and reason. After correction, recheck adjacent frames; auto-estimated spans remain unverified unless actually inspected.
7. Record coordinate transform, source frame number, source identity, athlete appearance, visibility/occlusion, origin, review decision, evidence point/range and audit revision. Avoid proxies' pixel coordinates being confused with original 4K coordinate space.
8. No auto-retraining, no inference access to labels, no face recognition. AI tracking suggestions may be added later but MUST NOT be mistaken for ground truth.

## 4. Required field groups (not one ambiguous status)

**Source catalog:** source, sport, catalog-owner surfer, identity/confidence, storage integrity, recording metadata, recording/session and last annotation activity.

**People in footage:** pseudonymous visible athletes, distinct person appearances, uncertain identity, manual same-person linking, start/end visibility, no forced primary if evidence insufficient.

**Event:** sport-aware kind, start/end source frames, performer of this event, important moments (takeoff, maneuver, landing/fall), partial/unobservable evidence, duplicate physical action information and notes.

**Usability:** usable, partially usable, not usable, uncertain; structured reason codes and confidence from the annotation guidelines, including missing beginning/end, unclear identity, occlusion, capture issues, no meaningful action or verified duplication.

**Selection for GT evaluation:** include / exclude / undecided (separate from usability). Do NOT default a newly created event to include. Source owner and event owner decisions are separate.

**BOX QA:** reviewed sample count, verified ranges, athlete identity, visible/partial/occluded/not_visible, manual/interpolated/proposed, incorrect/needs-correction and review notes.

**Editing GT:** crop/framing intent, primary target, wave context, source-to-render mapping, render-quality findings; separate from whether the raw video itself was usable.

**Video workflow:** טרם התחיל, בעבודה, דורש בדיקה, מוכן לאישור, מאושר. Source catalog owner is shown independently as לא שויך, שויך לגולש X or דורש בירור. Draft save / source SHA / immutable approved revision / backup freshness are separate states, clearly explained.

## 5. Quality: preview versus original versus final reel

The current Studio VP9 preview is intentionally reduced to **640px width at CRF 38**. Do not use it as evidence of pipeline render quality. Provide **תצוגה מהירה** and **בדיקת איכות מקור**; in quality mode inspect a high-resolution frame/source-synced derivative via authenticated local service with source-to-proxy mapping, secure memory/disk cache and no exposed R2 secret.

To claim final output quality, compare: authentic DJI source frame, Studio preview frame and **actual pipeline rendered reel** at equivalent times with EDL mapping, metadata (resolution/fps/codecs), crop/zoom/resizing, sharpness and visible athlete. When no real render or reliable mapping exists, mark NOT_TESTED. Do not change production encoder parameters in this design task.

## 6. Workflow and interaction

Library / Cloud -> Assign catalog owner -> Open or resume video -> Identify visible people -> Mark event boundaries -> Choose event performer and type -> Select usability/reason/confidence -> Decide GT inclusion -> Draw/review BOX checkpoints as needed -> Mark reviewed intervals -> Save draft -> Resolve review tasks -> Explicitly approve scoped immutable revision -> Freeze/evaluate downstream only when labels are approved and isolated.

Provide visual guidance for new annotators, but keep fast mouse/keyboard workflows for power users. Persist operator cursor and stable selected segment; autosave, offline queue and conflict handling must remain durable. Do not fabricate partial approvals: if source/interval/segment approval scopes differ, enforce the real semantics and show them accurately. Do not expose AI predictions during blind annotation.

## 7. Scope: implement the entire source-of-truth specification

Before coding, generate a **line-by-line requirement gap matrix** for:
- docs/specs/ground-truth-annotation-studio.md §§1–21
- docs/ground-truth-annotation-system-design.md
- docs/ground-truth-annotation-guidelines-v1.md
- docs/ground-truth-annotation-design-review-addendum-v1.md
- this approved V2 design contract and prototype.

Document superseded mobile/deployment proposals versus the selected Local First desktop model without weakening annotation invariants. Include remaining mandatory identity handling, human usability, confidence and structured reasons, key moments, clip boundaries, multi-sport events, review tasks and operator cursor, duplicate physical-action linkage, versioning, frozen datasets, blind evaluation and editing EDL/quality QA. For features requiring external approval, mark BLOCKED; don't quietly cut scope.

Build sequentially with test/evidence checkpoints:
- **P0 correctness:** direct ownership and Surfer Workspace, BOX QA data and UI, state semantics and integrity/migrations.
- **P1 approved design:** implement full Precision Studio V2 components, complete event/usability/confidence taxonomy and accessible keyboard/desktop interactions, high-quality inspection.
- **P2 full remaining contract:** review/adjudication, physical-action lineage, annotation sets and versioned datasets where mandatory, all required evaluation and editing metrics and robust real-world qualification.
- **Final:** full requirement traceability, CI on final head, screen captures in both desktop resolutions, raw and GT safe read-only qualification, explicit gaps.

## 8. Non-negotiable migration / safety

- No deletion, modification, copy, reprocessing or cleanup of R2 source files. Keep the Studio Object Read only and local SQLite source of GT.
- Before database migrations, snapshot and verify recovery using a separate safe destination; rehearse on a copy, not on live studio.sqlite. Keep history and existing approved/reviewed labels fully readable.
- Do not alter production pipeline, secrets, permissions, cloud resources or paid services; do not merge/redeploy without operator approval.
- Ensure SQLite/PostgreSQL parity, independent backups, SHA-256 validation, server-side secrets, blind evaluator, and PR #312/313 checks remain unaffected.
- Never commit private video frames or Ground Truth to the public repository. The prototype's sample image is synthetic by design.

## 9. Acceptance tests

1. Unannotated cloud DJI video with zero segments -> manually assign Surfer A -> Surfer A workspace displays video -> restart returns owner and zero events.
2. Event performer Surfer B in Surfer A's video, while Surfer C is visible in the background; all 3 identities/roles remain independent after save, approval and export.
3. Reassign owner with reason, verify audit and historical approved revisions unchanged; exercise concurrency conflict and bulk preview.
4. Draw BOX at two manual frames, interpolate, inspect beginning/middle/end; wrong-person crossing is detected, corrected and rechecked; uninspected frames never labeled fully verified.
5. Usability, partial reasons, uncertainty, source-relative frame timecodes and edit targets round-trip through draft, approved revision, frozen manifest and evaluator without silently upgrading undecided to include.
6. Existing videos/drafts/versions survive additive migration; same source in raw or processed keeps identity and catalogue owner; R2 byte hashes unaffected.
7. Precision V2 screenshots at 1440×900 and 1920×1080: navigation-left, filmstrip and multitrack, source/owner info, selected right inspector with direct controls; no clipped action buttons.
8. Actual source + Studio proxy + actual render quality comparison reports evidence or honest NOT_TESTED; never infer final quality from proxy.
9. Playwright tests cover owner-from-card, owner change, surfer workspace, two performers, BOX review uncertainty and wrong boxes, save/reload and keyboard/mouse.
10. No production writes/paid resources; CI checks clean on final head before proposing merge.

## 10. Delivery evidence

Report PASS/FAIL/BLOCKED/NOT_TESTED per requirement, source URL/commit, implementation paths, exact tests and CI links, migration rollback evidence, screenshots, one safe real-video smoke test, differences from approved prototype and outstanding operator gates. No claim of full implementation while any mandatory gap remains.
